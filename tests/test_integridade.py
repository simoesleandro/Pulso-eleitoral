import os
# Configura o ambiente de testes antes de importar os módulos do projeto
os.environ['TESTING'] = 'True'

from datetime import date, timedelta

import pytest

from database import DB_PATH, init_db, get_conn, get_integridade_geral


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
    """Schema + seed de institutos/candidatos, sem as pesquisas de demo
    (mesmo padrão de tests/test_agregacao.py)."""
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
    """Copiado de tests/test_agregacao.py — insere pesquisa + intenções."""
    inst_row = conn.execute(
        "SELECT id FROM institutos WHERE nome = ?", (instituto_nome,)
    ).fetchone()
    assert inst_row is not None, f"instituto {instituto_nome!r} não existe no seed"
    inst_id = inst_row["id"]

    data_pesquisa = (date.today() - timedelta(days=dias_atras)).isoformat()
    _contador_registro["n"] += 1
    registro_tse = f"TEST-INTEG-{_contador_registro['n']}"

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


# Ruído determinístico com média ~0 e desvio ~1.4pp (compatível com a dispersão
# binomial de amostras de 2000) e dígitos finais variados — série "honesta".
_RUIDO = [0.0, 1.3, -1.1, 2.4, -2.2, 0.7, -0.6, 1.8, -1.7, 0.9, -0.4, 2.1, -1.9, 0.2, 1.5]


def _seed_instituto_limpo(conn, nome, rotacao=0):
    """15 pesquisas com ruído realista em torno de Lula 40 / Bolsonaro 31."""
    ruido = _RUIDO[rotacao:] + _RUIDO[:rotacao]
    for k, r in enumerate(ruido):
        _seed_pesquisa(conn, nome, dias_atras=2 + k * 5, amostra=2000, candidatos={
            "Lula": round(40.0 + r, 1),
            "Bolsonaro": round(31.0 - r, 1),
        })


def _seed_instituto_fabricador(conn, nome):
    """12 pesquisas idênticas, tudo terminado em .0: variância zero (subdispersão)
    e dígito final degenerado — assinatura clássica de série fabricada."""
    for k in range(12):
        _seed_pesquisa(conn, nome, dias_atras=2 + k * 5, amostra=2000, candidatos={
            "Lula": 40.0,
            "Bolsonaro": 31.0,
            "Ciro": 8.0,
        })


def test_fabricador_anomalo_e_limpos_sem_indicios():
    _init_limpo()
    conn = get_conn()
    try:
        _seed_instituto_fabricador(conn, "Quaest")
        _seed_instituto_limpo(conn, "Atlas", rotacao=0)
        _seed_instituto_limpo(conn, "Datafolha", rotacao=7)
    finally:
        conn.close()

    resultado = get_integridade_geral(cargo="presidente")
    por_nome = {i["instituto"]: i for i in resultado["institutos"]}

    quaest = por_nome["Quaest"]
    assert quaest["categoria"] == "anomalo"
    assert quaest["testes"]["digito_final"]["p_valor"] < 0.01
    assert quaest["testes"]["subdispersao"]["p_subdispersao"] < 0.01

    for nome in ("Atlas", "Datafolha"):
        limpo = por_nome[nome]
        assert limpo["categoria"] == "sem_indicios", \
            f"{nome} não deveria ter indícios: {limpo['testes']}"


def test_divergencia_tse_flagada():
    _init_limpo()
    conn = get_conn()
    try:
        pid = _seed_pesquisa(conn, "Quaest", dias_atras=3, amostra=1200,
                             candidatos={"Lula": 40.0})
        # registro TSE com amostra registrada 40% maior que a realizada
        conn.execute("""
            INSERT INTO pesquisas_tse
            (protocolo, cargo, cnpj_empresa, nome_empresa, data_inicio, data_fim,
             qt_entrevistado, pesquisa_id)
            VALUES ('BR-00001/2026', 'presidente', '22445600000104', 'QUAEST',
                    ?, ?, 2000, ?)
        """, ((date.today() - timedelta(days=4)).isoformat(),
              (date.today() - timedelta(days=3)).isoformat(), pid))
        conn.commit()
    finally:
        conn.close()

    resultado = get_integridade_geral(cargo="presidente")
    divergencias = resultado["divergencias_tse"]
    assert len(divergencias) == 1
    assert divergencias[0]["divergente"] is True
    assert divergencias[0]["divergencia_pct"] == 40.0
    assert divergencias[0]["pesquisa_id"] == pid

    # a divergência também aparece no score da pesquisa individual
    pesquisa = next(p for p in resultado["pesquisas"] if p["id"] == pid)
    assert pesquisa["divergencia_tse"] == 40.0
    assert pesquisa["score"] >= 1


def test_dados_insuficientes_nao_geram_veredito():
    """Instituto com 1 pesquisa: nenhum teste tem N — categoria sem indícios,
    testes marcados como dados insuficientes."""
    _init_limpo()
    conn = get_conn()
    try:
        _seed_pesquisa(conn, "Quaest", dias_atras=3, amostra=2000,
                       candidatos={"Lula": 40.0, "Bolsonaro": 31.0})
    finally:
        conn.close()

    resultado = get_integridade_geral(cargo="presidente")
    quaest = next(i for i in resultado["institutos"] if i["instituto"] == "Quaest")
    assert quaest["categoria"] == "sem_indicios"
    assert quaest["testes"]["digito_final"].get("status") == "dados_insuficientes"
    assert quaest["testes"]["subdispersao"].get("status") == "dados_insuficientes"


def test_contrato_do_json():
    _init_limpo()
    resultado = get_integridade_geral(cargo="presidente")
    for chave in ("cargo", "institutos", "pesquisas", "zscores",
                  "divergencias_tse", "disclaimer", "atualizado_em"):
        assert chave in resultado
    assert "fraude" not in str(resultado["disclaimer"]).split("prova de")[0].lower()
