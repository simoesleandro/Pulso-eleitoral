import os
# Configura o ambiente de testes antes de importar os módulos do projeto
os.environ['TESTING'] = 'True'

import pytest
import sqlite3

import database
from database import (
    DB_PATH, get_conn, init_db,
    get_simulacao_monte_carlo, simular_monte_carlo_cenarios, _simular_cenario,
    fator_volatilidade, _redistribuir_indecisos, prob_vitoria_primeiro_turno,
)
import scripts.migrate_pesquisas_volatilidade as migrate_pesquisas_volatilidade
from scripts.migrate_pesquisas_volatilidade import aplicar_migracao as aplicar_migracao_volatilidade
from app import app as flask_app


@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Garante que o banco de dados de testes seja limpo antes e depois de cada teste."""
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
