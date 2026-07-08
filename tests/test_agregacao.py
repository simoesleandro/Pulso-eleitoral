import os
# Configura o ambiente de testes antes de importar os módulos do projeto
os.environ['TESTING'] = 'True'

from datetime import date, timedelta

import pytest

from database import DB_PATH, init_db, get_conn, get_media_agregada, get_kpis_avancados, get_historico_multi


@pytest.fixture(autouse=True)
def cleanup():
    """Limpa o banco de dados temporário antes e depois de cada teste."""
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass
    yield
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass


_contador_registro = {"n": 0}


def _init_limpo():
    """Inicializa o schema + seed de institutos/candidatos, mas remove as
    pesquisas/intenções de demonstração do seed.sql para isolar os testes
    numéricos (senão o poll-of-polls mistura dados de demo com os seeds
    controlados dos testes)."""
    init_db(force_seed=True)
    conn = get_conn()
    try:
        conn.execute("DELETE FROM intencoes")
        conn.execute("DELETE FROM pesquisas")
        conn.commit()
    finally:
        conn.close()


def _seed_pesquisa(conn, instituto_nome, dias_atras, amostra, candidatos,
                    tipo="estimulada", cargo="presidente"):
    """Insere uma pesquisa com N intenções, `dias_atras` dias antes de hoje.

    candidatos: dict {nome_canonico: percentual}.
    Retorna o id da pesquisa criada.
    """
    inst_row = conn.execute(
        "SELECT id FROM institutos WHERE nome = ?", (instituto_nome,)
    ).fetchone()
    assert inst_row is not None, f"instituto {instituto_nome!r} não existe no seed"
    inst_id = inst_row["id"]

    data_pesquisa = (date.today() - timedelta(days=dias_atras)).isoformat()
    _contador_registro["n"] += 1
    registro_tse = f"TEST-{_contador_registro['n']}"

    cur = conn.execute("""
        INSERT INTO pesquisas
        (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (inst_id, cargo, data_pesquisa, data_pesquisa, amostra, 2.0, "Teste",
          registro_tse, f"http://teste.com/{registro_tse}"))
    pesquisa_id = cur.lastrowid

    for nome, pct in candidatos.items():
        conn.execute(
            "INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) VALUES (?, ?, ?, ?)",
            (pesquisa_id, nome, pct, tipo)
        )
    conn.commit()
    return pesquisa_id


def test_helper_seed_insere_pesquisa_e_intencoes():
    """Sanity check do helper de seed: garante que a infra de teste funciona."""
    _init_limpo()
    conn = get_conn()
    try:
        pid = _seed_pesquisa(conn, "Quaest", dias_atras=1, amostra=2000, candidatos={"Lula": 40.0})
        row = conn.execute("SELECT id FROM pesquisas WHERE id = ?", (pid,)).fetchone()
        assert row is not None
        intencoes = conn.execute(
            "SELECT candidato, percentual FROM intencoes WHERE pesquisa_id = ?", (pid,)
        ).fetchall()
        assert len(intencoes) == 1
        assert intencoes[0]["candidato"] == "Lula"
    finally:
        conn.close()


# ─── get_media_agregada ─────────────────────────────────────────────────────

def test_media_ponderada_basica():
    """2 institutos, 1 pesquisa cada, mesmo dia (hoje-1) — mesma idade cancela
    o peso de recência, sobra só o peso por amostra.
    media = (40*2000 + 34*1000) / (2000 + 1000) = 114000/3000 = 38.0
    """
    _init_limpo()
    conn = get_conn()
    try:
        _seed_pesquisa(conn, "Quaest", dias_atras=1, amostra=2000, candidatos={"Lula": 40.0})
        _seed_pesquisa(conn, "Datafolha", dias_atras=1, amostra=1000, candidatos={"Lula": 34.0})
    finally:
        conn.close()

    resultado = get_media_agregada("presidente", dias=30)
    lula = next(c for c in resultado["candidatos"] if c["candidato"] == "Lula")
    assert lula["media"] == 38.0


def test_decaimento_por_recencia():
    """Mesmo candidato, inst A hoje (X=40, amostra 1000), inst B hoje-7 (X=30,
    amostra 1000). O peso de B é descontado por 0.9**7.
    media = (40*1000*0.9**0 + 30*1000*0.9**7) / (1000*0.9**0 + 1000*0.9**7)
    """
    _init_limpo()
    conn = get_conn()
    try:
        _seed_pesquisa(conn, "Quaest", dias_atras=0, amostra=1000, candidatos={"Lula": 40.0})
        _seed_pesquisa(conn, "Datafolha", dias_atras=7, amostra=1000, candidatos={"Lula": 30.0})
    finally:
        conn.close()

    peso_a = 1000 * (0.9 ** 0)
    peso_b = 1000 * (0.9 ** 7)
    media_esperada = round((40 * peso_a + 30 * peso_b) / (peso_a + peso_b), 1)

    resultado = get_media_agregada("presidente", dias=30)
    lula = next(c for c in resultado["candidatos"] if c["candidato"] == "Lula")
    assert lula["media"] == media_esperada


def test_uma_pesquisa_por_instituto_variacao_usa_todas_entradas():
    """Inst A (Quaest) tem 2 pesquisas na janela (hoje-20 X=30, hoje-1 X=40);
    inst B (Datafolha) tem hoje-1 X=40. Só a mais recente de A entra na média
    (X=40 dos dois -> media 40.0), mas variacao_30d usa as três entradas.
    data_meio (dias=30) = hoje-15: recentes=[40,40] (hoje-1 dos dois),
    anteriores=[30] (hoje-20) -> variacao = round(40-30,1) = 10.0.
    """
    _init_limpo()
    conn = get_conn()
    try:
        _seed_pesquisa(conn, "Quaest", dias_atras=20, amostra=1000, candidatos={"Lula": 30.0})
        _seed_pesquisa(conn, "Quaest", dias_atras=1, amostra=1000, candidatos={"Lula": 40.0})
        _seed_pesquisa(conn, "Datafolha", dias_atras=1, amostra=1000, candidatos={"Lula": 40.0})
    finally:
        conn.close()

    resultado = get_media_agregada("presidente", dias=30)
    lula = next(c for c in resultado["candidatos"] if c["candidato"] == "Lula")
    assert lula["media"] == 40.0
    assert lula["min"] == 40.0
    assert lula["max"] == 40.0
    assert lula["pesquisas_count"] == 2
    assert lula["variacao_30d"] == 10.0


def test_corte_candidato_com_menos_de_duas_entradas():
    """Candidato presente numa única pesquisa deve ficar ausente do retorno,
    mesmo que outro candidato válido (>=2 entradas) esteja na mesma janela."""
    _init_limpo()
    conn = get_conn()
    try:
        _seed_pesquisa(conn, "Quaest", dias_atras=1, amostra=1000,
                        candidatos={"Lula": 40.0, "Simone Tebet": 20.0})
        _seed_pesquisa(conn, "Datafolha", dias_atras=1, amostra=1000,
                        candidatos={"Lula": 38.0})
    finally:
        conn.close()

    resultado = get_media_agregada("presidente", dias=30)
    nomes = [c["candidato"] for c in resultado["candidatos"]]
    assert "Lula" in nomes
    assert "Simone Tebet" not in nomes


def test_amostra_ausente_usa_default_1000():
    """tamanho_amostra=0 deve pesar como 1000 (default), não como 0.
    Ambas pesquisas na mesma idade (hoje-1) -> pesos de recência cancelam.
    Sem o default: media seria (20*0+10*1000)/(0+1000) = 10.0.
    Com o default: media = (20*1000+10*1000)/(1000+1000) = 15.0.
    """
    _init_limpo()
    conn = get_conn()
    try:
        _seed_pesquisa(conn, "Quaest", dias_atras=1, amostra=0, candidatos={"Ciro Gomes": 20.0})
        _seed_pesquisa(conn, "Datafolha", dias_atras=1, amostra=1000, candidatos={"Ciro Gomes": 10.0})
    finally:
        conn.close()

    resultado = get_media_agregada("presidente", dias=30)
    ciro = next(c for c in resultado["candidatos"] if c["candidato"] == "Ciro Gomes")
    assert ciro["media"] == 15.0


def test_filtro_estimulada_exclui_espontanea():
    """Uma intenção tipo='espontanea' não deve entrar na média, mesmo com
    percentual muito diferente das estimuladas."""
    _init_limpo()
    conn = get_conn()
    try:
        _seed_pesquisa(conn, "Quaest", dias_atras=1, amostra=1000,
                        candidatos={"Simone Tebet": 20.0}, tipo="estimulada")
        _seed_pesquisa(conn, "Datafolha", dias_atras=1, amostra=1000,
                        candidatos={"Simone Tebet": 20.0}, tipo="estimulada")
        # Pesquisa espontânea com percentual muito diferente — não deve mover a média.
        _seed_pesquisa(conn, "Atlas", dias_atras=1, amostra=1000,
                        candidatos={"Simone Tebet": 5.0}, tipo="espontanea")
    finally:
        conn.close()

    resultado = get_media_agregada("presidente", dias=30)
    tebet = next(c for c in resultado["candidatos"] if c["candidato"] == "Simone Tebet")
    assert tebet["media"] == 20.0
    # 'tipo IS NULL' (registro legado) não é testável aqui: intencoes.tipo é
    # NOT NULL no schema atual — a cláusula existe só para dados legados
    # anteriores à coluna, inseríveis apenas fora do schema-conformante.


# ─── get_kpis_avancados (caracterização) ────────────────────────────────────

def _seed_kpis_base(conn):
    """3 candidatos com >=2 pesquisas cada, para permitir margem_lideranca e
    tendencia_aceleracao (top 3)."""
    _seed_pesquisa(conn, "Quaest", dias_atras=2, amostra=1000,
                    candidatos={"Lula": 42.0, "Flávio Bolsonaro": 30.0, "Ciro Gomes": 8.0})
    _seed_pesquisa(conn, "Datafolha", dias_atras=20, amostra=1000,
                    candidatos={"Lula": 40.0, "Flávio Bolsonaro": 32.0, "Ciro Gomes": 8.0})


def test_kpis_margem_lideranca_empate_tecnico():
    """Margem < 5pp entre 1º e 2º -> classificacao 'empate_tecnico'."""
    _init_limpo()
    conn = get_conn()
    try:
        _seed_pesquisa(conn, "Quaest", dias_atras=2, amostra=1000,
                        candidatos={"Lula": 38.0, "Flávio Bolsonaro": 36.0})
        _seed_pesquisa(conn, "Datafolha", dias_atras=20, amostra=1000,
                        candidatos={"Lula": 38.0, "Flávio Bolsonaro": 36.0})
    finally:
        conn.close()

    kpis = get_kpis_avancados("presidente")
    assert kpis["margem_lideranca"]["classificacao"] == "empate_tecnico"


def test_kpis_margem_lideranca_moderada():
    """Margem entre 5pp e 10pp -> classificacao 'lideranca_moderada'."""
    _init_limpo()
    conn = get_conn()
    try:
        _seed_pesquisa(conn, "Quaest", dias_atras=2, amostra=1000,
                        candidatos={"Lula": 42.0, "Flávio Bolsonaro": 34.0})
        _seed_pesquisa(conn, "Datafolha", dias_atras=20, amostra=1000,
                        candidatos={"Lula": 42.0, "Flávio Bolsonaro": 34.0})
    finally:
        conn.close()

    kpis = get_kpis_avancados("presidente")
    assert kpis["margem_lideranca"]["classificacao"] == "lideranca_moderada"


def test_kpis_margem_lideranca_confortavel():
    """Margem > 10pp -> classificacao 'lideranca_confortavel'."""
    _init_limpo()
    conn = get_conn()
    try:
        _seed_pesquisa(conn, "Quaest", dias_atras=2, amostra=1000,
                        candidatos={"Lula": 45.0, "Flávio Bolsonaro": 30.0})
        _seed_pesquisa(conn, "Datafolha", dias_atras=20, amostra=1000,
                        candidatos={"Lula": 45.0, "Flávio Bolsonaro": 30.0})
    finally:
        conn.close()

    kpis = get_kpis_avancados("presidente")
    assert kpis["margem_lideranca"]["classificacao"] == "lideranca_confortavel"


def test_kpis_probabilidade_segundo_turno_e_tendencia_shape():
    """Líder com media <50% -> probabilidade_segundo_turno.provavel True;
    tendencia_aceleracao tem um item por candidato do top 3, com as chaves
    tendencia_15d/tendencia_30d/aceleracao."""
    _init_limpo()
    conn = get_conn()
    try:
        _seed_kpis_base(conn)
    finally:
        conn.close()

    kpis = get_kpis_avancados("presidente")
    assert kpis["probabilidade_segundo_turno"]["provavel"] is True

    tendencia = kpis["tendencia_aceleracao"]
    assert len(tendencia) == 3
    for item in tendencia:
        assert "tendencia_15d" in item
        assert "tendencia_30d" in item
        assert "aceleracao" in item


def test_kpis_concentracao_voto():
    """top2_soma > 70 -> classificacao 'bipolar'."""
    _init_limpo()
    conn = get_conn()
    try:
        _seed_pesquisa(conn, "Quaest", dias_atras=2, amostra=1000,
                        candidatos={"Lula": 45.0, "Flávio Bolsonaro": 35.0})
        _seed_pesquisa(conn, "Datafolha", dias_atras=20, amostra=1000,
                        candidatos={"Lula": 45.0, "Flávio Bolsonaro": 35.0})
    finally:
        conn.close()

    kpis = get_kpis_avancados("presidente")
    assert kpis["concentracao_voto"]["top2_soma"] == 80.0
    assert kpis["concentracao_voto"]["classificacao"] == "bipolar"


# ─── get_historico_multi (caracterização) ──────────────────────────────────

def test_historico_multi_series_ordenada_e_filtro_tipo():
    """Uma série por candidato, dados ordenados por data ascendente, cada
    ponto com data/percentual/margem_erro/instituto; tipo='espontanea' filtra
    exato (não mistura com estimulada)."""
    _init_limpo()
    conn = get_conn()
    try:
        _seed_pesquisa(conn, "Quaest", dias_atras=10, amostra=1000,
                        candidatos={"Lula": 38.0}, tipo="estimulada")
        _seed_pesquisa(conn, "Datafolha", dias_atras=1, amostra=1000,
                        candidatos={"Lula": 40.0}, tipo="estimulada")
        _seed_pesquisa(conn, "Atlas", dias_atras=5, amostra=1000,
                        candidatos={"Lula": 25.0}, tipo="espontanea")
    finally:
        conn.close()

    series = get_historico_multi(["Lula"], "presidente", tipo="estimulada")
    assert len(series) == 1
    assert series[0]["candidato"] == "Lula"
    dados = series[0]["dados"]
    assert len(dados) == 2
    # ordenado por data ascendente
    assert dados[0]["data"] < dados[1]["data"]
    for ponto in dados:
        assert set(ponto.keys()) == {"data", "percentual", "margem_erro", "instituto"}
    # a pesquisa espontânea não deve aparecer no filtro estimulada
    percentuais = {p["percentual"] for p in dados}
    assert 25.0 not in percentuais

    series_espontanea = get_historico_multi(["Lula"], "presidente", tipo="espontanea")
    assert len(series_espontanea[0]["dados"]) == 1
    assert series_espontanea[0]["dados"][0]["percentual"] == 25.0


def test_historico_multi_candidato_inexistente_retorna_serie_vazia():
    """Candidato sem nenhuma pesquisa no banco -> série com dados == []."""
    _init_limpo()
    conn = get_conn()
    try:
        _seed_pesquisa(conn, "Quaest", dias_atras=1, amostra=1000, candidatos={"Lula": 38.0})
    finally:
        conn.close()

    series = get_historico_multi(["Candidato Inexistente"], "presidente")
    assert len(series) == 1
    assert series[0]["candidato"] == "Candidato Inexistente"
    assert series[0]["dados"] == []
