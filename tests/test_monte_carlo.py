import os
# Configura o ambiente de testes antes de importar os módulos do projeto
os.environ['TESTING'] = 'True'

import pytest
import sqlite3

import random

import database
from database import (
    DB_PATH, get_conn, init_db,
    get_simulacao_monte_carlo, simular_monte_carlo_cenarios, _simular_cenario,
    fator_volatilidade, _redistribuir_indecisos, prob_vitoria_primeiro_turno,
    simular_monte_carlo_cargo, simular_prob_vitoria_1_turno,
)
import scripts.migrate_pesquisas_volatilidade as migrate_pesquisas_volatilidade
from scripts.migrate_pesquisas_volatilidade import aplicar_migracao as aplicar_migracao_volatilidade
from app import app as flask_app, cache as flask_cache


@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Garante que o banco de dados de testes seja limpo antes e depois de cada
    teste, e limpa o cache Flask-Caching (os endpoints de monte-carlo usam
    @cache.cached — sem isso, um teste pega a resposta cacheada de outro)."""
    flask_cache.clear()
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass

    yield

    flask_cache.clear()
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret-key'
    with flask_app.test_client() as client:
        yield client


def _preparar_banco_sem_migracao():
    """Roda schema.sql SEM aplicar a migration de pct_pode_mudar_voto (estado
    "pré-migração"), pra simular corrida entre processos."""
    if not os.path.exists(database.DATA_DIR):
        os.makedirs(database.DATA_DIR, exist_ok=True)
    conn = get_conn()
    with open(os.path.join(database.BASE_DIR, 'schema.sql'), 'r', encoding='utf-8') as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


def _inserir_pesquisa_teste(conn, cargo, data_pesquisa, candidatos_percentuais):
    """Insere instituto + pesquisa + intenções de teste (1 poll, N candidatos)."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO institutos (nome, sigla, site) VALUES (?, ?, ?)",
        ("Instituto Teste", "IT", "http://teste.com")
    )
    instituto_id = cursor.lastrowid
    cursor.execute(
        """INSERT INTO pesquisas
           (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (instituto_id, cargo, data_pesquisa, data_pesquisa, 1000, 2.0, "Contratante Teste",
         f"BR-{instituto_id}-{data_pesquisa}", "http://fonte.com")
    )
    pesquisa_id = cursor.lastrowid
    cursor.executemany(
        "INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES (?, ?, ?, ?, ?)",
        [(pesquisa_id, candidato, "Partido Teste", percentual, "estimulada")
         for candidato, percentual in candidatos_percentuais]
    )
    conn.commit()
    return pesquisa_id


# ─── Regressão: endpoint presidencial em produção ──────────────────────────

def test_endpoint_presidencial_mantem_formato_legado(client):
    """GET /api/monte-carlo continua devolvendo exatamente o mesmo formato de
    antes da generalização do motor (regressão)."""
    init_db(force_seed=True)

    response = client.get('/api/monte-carlo')
    assert response.status_code == 200
    data = response.json

    # Chaves de topo exatamente as de sempre — nada novo (ex.: 'cargo',
    # 'fator_sigma_usado') deve vazar do motor genérico pro contrato legado.
    assert set(data.keys()) == {'cenarios', 'n_simulacoes', 'margem_default_usada', 'lula', 'flavio'}

    assert len(data['cenarios']) == 3
    ids_esperados = {'lula_flavio', 'lula_caiado', 'lula_zema'}
    assert {c['id'] for c in data['cenarios']} == ids_esperados

    for cenario in data['cenarios']:
        assert set(cenario.keys()) == {'id', 'label', 'candidato_a', 'candidato_b'}
        for lado in ('candidato_a', 'candidato_b'):
            campos = cenario[lado]
            assert set(campos.keys()) == {'nome', 'media_direto', 'prob_vitoria', 'favorito'}
            assert 0.0 <= campos['prob_vitoria'] <= 100.0

    lula_flavio = next(c for c in data['cenarios'] if c['id'] == 'lula_flavio')
    assert data['lula'] == lula_flavio['candidato_a']
    assert data['flavio'] == lula_flavio['candidato_b']

    # Vitórias entre o par são complementares (a corrida é bipolar, pct=100-pct)
    for cenario in data['cenarios']:
        soma = cenario['candidato_a']['prob_vitoria'] + cenario['candidato_b']['prob_vitoria']
        assert soma == pytest.approx(100.0, abs=0.2)


def test_get_simulacao_monte_carlo_wrapper_direto():
    """Chamando get_simulacao_monte_carlo() direto (sem passar pelo Flask)
    também preserva o contrato legado."""
    init_db(force_seed=True)

    resultado = get_simulacao_monte_carlo(n_simulacoes=500)

    assert set(resultado.keys()) == {'cenarios', 'n_simulacoes', 'margem_default_usada', 'lula', 'flavio'}
    assert resultado['margem_default_usada'] == 2.0
    assert resultado['lula']['nome'] == 'Lula'
    assert resultado['flavio']['nome'] == 'Flávio Bolsonaro'


# ─── Motor genérico ─────────────────────────────────────────────────────────

def test_motor_generico_prob_alta_para_media_alta_sigma_baixo():
    """Candidato com média alta e sigma baixo (margem de erro pequena) deve
    ter prob_vitoria_primeiro_turno próxima de 1 (100%); o oposto (média
    baixa) deve ficar próximo de 0."""
    candidatos = [
        {'candidato': 'Favorito', 'media': 70.0},
        {'candidato': 'Azarão', 'media': 5.0},
    ]
    margens = {'Favorito': 1.0, 'Azarão': 1.0}

    resultado = _simular_cenario(
        candidatos, margens, 'Favorito', 'Azarão',
        n_simulacoes=2000, fator_sigma=1.0, sigma_minimo=2.0,
    )

    prob_favorito = prob_vitoria_primeiro_turno('Favorito', resultado['runs'])
    prob_azarao = prob_vitoria_primeiro_turno('Azarão', resultado['runs'])

    assert prob_favorito > 95.0
    assert prob_azarao < 5.0
    # A métrica derivada bate com a já embutida no resultado (mesmo array de runs)
    assert resultado['candidato_a']['prob_vitoria_primeiro_turno'] == prob_favorito


def test_motor_generico_retem_runs_completos():
    """Cada run retido deve conter o share de TODOS os candidatos do
    cenário, não só do par a/b."""
    candidatos = [
        {'candidato': 'A', 'media': 40.0},
        {'candidato': 'B', 'media': 30.0},
        {'candidato': 'C', 'media': 20.0},
    ]
    margens = {'A': 2.0, 'B': 2.0, 'C': 2.0}

    resultado = _simular_cenario(candidatos, margens, 'A', 'B', n_simulacoes=50)

    assert len(resultado['runs']) == 50
    for run in resultado['runs']:
        assert set(run.keys()) == {'A', 'B', 'C'}


# ─── Redistribuição do bucket de indecisos ─────────────────────────────────

def test_redistribuicao_bucket_indecisos_soma_bate_100():
    """Depois de redistribuir o bucket de indecisos, a soma dos shares dos
    candidatos reais bate com o total original (candidatos + indecisos)."""
    simulado = {'A': 50.0, 'B': 30.0, 'C': 10.0}  # soma = 90
    pct_indecisos = 10.0  # 90 + 10 = 100

    redistribuido = _redistribuir_indecisos(simulado, pct_indecisos)

    assert sum(redistribuido.values()) == pytest.approx(100.0)
    # Proporção original entre candidatos se mantém (redistribuição é proporcional)
    assert redistribuido['A'] > redistribuido['B'] > redistribuido['C']


def test_redistribuicao_bucket_indecisos_zero_e_no_op():
    """pct_indecisos=0 (ou ausente, caso do cargo 'presidente' hoje) não deve
    alterar o dict simulado."""
    simulado = {'A': 50.0, 'B': 30.0}
    assert _redistribuir_indecisos(simulado, 0.0) == simulado


# ─── fator_volatilidade ─────────────────────────────────────────────────────

def test_fator_volatilidade_neutro_quando_null():
    assert fator_volatilidade(None) == 1.0


def test_fator_volatilidade_inflaciona_quando_presente():
    assert fator_volatilidade(30.0) == pytest.approx(1.30)
    assert fator_volatilidade(0.0) == pytest.approx(1.0)


# ─── Migration pct_pode_mudar_voto ─────────────────────────────────────────

def test_migracao_volatilidade_e_idempotente():
    """A migration pode rodar 2x sem erro e sem duplicar a coluna."""
    init_db(force_seed=False)
    conn = get_conn()

    aplicar_migracao_volatilidade(conn)
    aplicar_migracao_volatilidade(conn)

    colunas = [row[1] for row in conn.execute("PRAGMA table_info(pesquisas)").fetchall()]
    assert colunas.count("pct_pode_mudar_voto") == 1

    conn.close()


def test_migracao_volatilidade_resiliente_a_race_condition(monkeypatch):
    """Corrida entre processos (outra machine já adicionou a coluna) não deve
    quebrar a migration."""
    conn = _preparar_banco_sem_migracao()

    conn.execute("ALTER TABLE pesquisas ADD COLUMN pct_pode_mudar_voto REAL")
    conn.commit()

    monkeypatch.setattr(migrate_pesquisas_volatilidade, "_colunas_existentes", lambda conn, tabela: set())

    aplicar_migracao_volatilidade(conn)  # não deve levantar exceção

    colunas = [row[1] for row in conn.execute("PRAGMA table_info(pesquisas)").fetchall()]
    assert colunas.count("pct_pode_mudar_voto") == 1

    conn.close()


# ─── Endpoint GET /api/monte-carlo/governador_rj ───────────────────────────

def test_endpoint_governador_rj_amostra_limitada_com_seed(client):
    """Com apenas UMA pesquisa recente de governador_rj na janela de 30 dias,
    nenhum candidato tem 2+ pesquisas — então amostra_limitada deve ser True,
    candidatos_simulados vazio e os candidatos caem em dados_insuficientes.
    (Data relativa a hoje para não depender das datas fixas do seed padrão,
    que saem da janela conforme o tempo passa.)"""
    init_db(force_seed=False)
    conn = get_conn()
    conn.execute("DELETE FROM intencoes")
    conn.execute("DELETE FROM pesquisas")
    conn.commit()
    from datetime import date, timedelta
    data_recente = (date.today() - timedelta(days=5)).isoformat()
    _inserir_pesquisa_teste(conn, 'governador_rj', data_recente,
                            [('Candidato X', 40.0), ('Candidato Y', 30.0)])
    conn.close()

    response = client.get('/api/monte-carlo/governador_rj')
    assert response.status_code == 200
    data = response.json

    assert data['cargo'] == 'governador_rj'
    assert data['amostra_limitada'] is True
    assert data['candidatos_simulados'] == []
    assert len(data['candidatos_dados_insuficientes']) > 0
    assert data['aviso'] is not None


def test_endpoint_governador_rj_amostra_nao_limitada_com_dado_suficiente(client):
    """Com 2 pesquisas recentes cobrindo os mesmos 2 candidatos,
    amostra_limitada deve ser False e ambos aparecem em candidatos_simulados
    com prob_vitoria_1_turno válida."""
    init_db(force_seed=False)  # banco vazio ainda dispara o seed.sql — limpa antes de popular
    conn = get_conn()
    conn.execute("DELETE FROM intencoes")
    conn.execute("DELETE FROM pesquisas")
    conn.commit()
    from datetime import date, timedelta
    data_a = (date.today() - timedelta(days=10)).isoformat()
    data_b = (date.today() - timedelta(days=5)).isoformat()
    _inserir_pesquisa_teste(conn, 'governador_rj', data_a, [('Candidato X', 40.0), ('Candidato Y', 30.0)])
    _inserir_pesquisa_teste(conn, 'governador_rj', data_b, [('Candidato X', 42.0), ('Candidato Y', 32.0)])
    conn.close()

    response = client.get('/api/monte-carlo/governador_rj')
    assert response.status_code == 200
    data = response.json

    assert data['amostra_limitada'] is False
    nomes = {c['nome'] for c in data['candidatos_simulados']}
    assert nomes == {'Candidato X', 'Candidato Y'}
    for c in data['candidatos_simulados']:
        assert 0.0 <= c['prob_vitoria_1_turno'] <= 100.0
    assert data['candidatos_dados_insuficientes'] == []


def test_endpoint_governador_rj_sem_chaves_legadas(client):
    """O formato de resposta do novo endpoint não tem nenhuma chave do
    contrato legado do endpoint presidencial (lula/flavio/cenarios/etc)."""
    init_db(force_seed=True)

    response = client.get('/api/monte-carlo/governador_rj')
    data = response.json

    chaves_legadas = {'lula', 'flavio', 'margem_default_usada', 'n_simulacoes', 'cenarios'}
    assert not (set(data.keys()) & chaves_legadas)
    assert set(data.keys()) == {
        'cargo', 'candidatos_simulados', 'candidatos_dados_insuficientes',
        'amostra_limitada', 'aviso',
    }


def test_simular_monte_carlo_cargo_exclui_candidato_inelegivel_de_insuficientes():
    """Candidato com status != 'ativo' (ex.: Cláudio Castro, inelegível) não
    deve aparecer em candidatos_dados_insuficientes mesmo tendo pesquisa na
    janela — ele já foi descartado da corrida, não está "aguardando mais
    pesquisas"."""
    init_db(force_seed=False)  # já aplica a migration de status automaticamente
    conn = get_conn()
    from datetime import date, timedelta
    data_a = (date.today() - timedelta(days=10)).isoformat()
    _inserir_pesquisa_teste(conn, 'governador_rj', data_a,
                             [('Eduardo Paes', 40.0), ('Cláudio Castro', 5.0)])
    conn.close()

    resultado = simular_monte_carlo_cargo('governador_rj')

    assert 'Cláudio Castro' not in resultado['candidatos_dados_insuficientes']


# ─── simular_prob_vitoria_1_turno (bug do caso degenerado com 1 candidato) ──

def test_simular_prob_vitoria_1_turno_nao_satura_em_100_com_1_candidato():
    """Reprodução exata do bug relatado: candidato com média 53.2 e margem
    2.5 (sigma=6.0) deve devolver algo entre 65-75%, nunca mais 100%."""
    random.seed(123)
    resultado = simular_prob_vitoria_1_turno(
        {'Eduardo Paes': {'media': 53.2, 'margem': 2.5}}, n_simulacoes=10000
    )
    prob = resultado['Eduardo Paes']
    assert 65.0 <= prob <= 75.0


def test_simular_prob_vitoria_1_turno_bate_com_baseline_manual():
    """Com o mesmo seed e parâmetros da investigação anterior (10k amostras
    gauss(53.2, 6.0), contagem > 50), o baseline manual validado foi 70.4%.
    A função formalizada deve bater com tolerância de ±2pp."""
    random.seed(123)
    resultado = simular_prob_vitoria_1_turno(
        {'Eduardo Paes': {'media': 53.2, 'margem': 2.5}}, n_simulacoes=10000
    )
    assert resultado['Eduardo Paes'] == pytest.approx(70.4, abs=2.0)


def test_simular_prob_vitoria_1_turno_independe_de_outros_candidatos():
    """O resultado de um candidato não deve depender de quantos outros
    candidatos estão no dict de entrada — sem caso degenerado, sem pool
    compartilhado. Mesma seed, mesmo candidato-alvo, resultado idêntico com
    1 ou com múltiplos candidatos."""
    entrada_1 = {'A': {'media': 53.2, 'margem': 2.5}}
    entrada_multi = {
        'A': {'media': 53.2, 'margem': 2.5},
        'B': {'media': 20.0, 'margem': 2.0},
        'C': {'media': 10.0, 'margem': 3.0},
    }

    random.seed(42)
    resultado_1 = simular_prob_vitoria_1_turno(entrada_1, n_simulacoes=5000)
    random.seed(42)
    resultado_multi = simular_prob_vitoria_1_turno(entrada_multi, n_simulacoes=5000)

    assert resultado_1['A'] == resultado_multi['A']
    # Candidato com média baixa (10%) deve ficar perto de 0%
    assert resultado_multi['C'] < 5.0


def test_simular_prob_vitoria_1_turno_fator_volatilidade_infla_sigma():
    """Quando pct_pode_mudar_voto é informado, o sigma inflado deve alargar
    a distribuição — candidato com média exatamente 50 deve ficar mais
    perto de 50% de chance (mais incerteza) do que sem o fator."""
    random.seed(7)
    sem_volatilidade = simular_prob_vitoria_1_turno(
        {'X': {'media': 53.2, 'margem': 2.5, 'pct_pode_mudar_voto': None}},
        n_simulacoes=5000,
    )
    random.seed(7)
    com_volatilidade = simular_prob_vitoria_1_turno(
        {'X': {'media': 53.2, 'margem': 2.5, 'pct_pode_mudar_voto': 50.0}},
        n_simulacoes=5000,
    )
    # fator_volatilidade(50.0) = 1.5x sigma -> distribuição mais espalhada
    # -> probabilidade de ficar acima de 50% se aproxima mais de 50%
    assert abs(com_volatilidade['X'] - 50.0) < abs(sem_volatilidade['X'] - 50.0)


def test_simular_monte_carlo_cargo_nao_usa_mais_hack_de_nome_duplicado():
    """simular_monte_carlo_cargo() com exatamente 1 candidato suficiente não
    deve mais saturar em 100% (regressão do bug investigado)."""
    init_db(force_seed=False)
    conn = get_conn()
    conn.execute("DELETE FROM intencoes")
    conn.execute("DELETE FROM pesquisas")
    conn.commit()
    from datetime import date, timedelta
    data_a = (date.today() - timedelta(days=10)).isoformat()
    data_b = (date.today() - timedelta(days=5)).isoformat()
    _inserir_pesquisa_teste(conn, 'governador_rj', data_a, [('Único Candidato', 53.2)])
    _inserir_pesquisa_teste(conn, 'governador_rj', data_b, [('Único Candidato', 53.2)])
    conn.close()

    resultado = simular_monte_carlo_cargo('governador_rj', n_simulacoes=5000)

    assert len(resultado['candidatos_simulados']) == 1
    prob = resultado['candidatos_simulados'][0]['prob_vitoria_1_turno']
    assert prob < 95.0  # não satura mais em 100%


def test_endpoint_presidencial_nao_afetado_pelo_fix(client):
    """get_simulacao_monte_carlo() (endpoint presidencial em produção)
    continua idêntico — o fix é isolado à função nova de 1º turno, não
    tocou em _simular_cenario nem no prob_vitoria pairwise legado."""
    init_db(force_seed=True)

    resultado = get_simulacao_monte_carlo(n_simulacoes=500)

    assert set(resultado.keys()) == {'cenarios', 'n_simulacoes', 'margem_default_usada', 'lula', 'flavio'}
    for cenario in resultado['cenarios']:
        for lado in ('candidato_a', 'candidato_b'):
            assert set(cenario[lado].keys()) == {'nome', 'media_direto', 'prob_vitoria', 'favorito'}
