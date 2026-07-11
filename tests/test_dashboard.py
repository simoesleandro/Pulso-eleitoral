import os
# Configura o ambiente de testes antes de importar os módulos
os.environ['TESTING'] = 'True'

import pytest
import sqlite3
from database import DB_PATH, init_db
from app import app as flask_app

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

@pytest.fixture
def client():
    """Retorna o cliente de testes Flask."""
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret-key'
    with flask_app.test_client() as client:
        yield client

def setup_db_with_seed():
    """Recria o banco de testes contendo a carga inicial (seed)."""
    init_db(force_seed=True)

def setup_db_empty():
    """Recria o banco de testes contendo apenas o esquema (sem seed)."""
    conn = sqlite3.connect(DB_PATH)
    schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    conn.close()

def test_dashboard_route(client):
    """Testa que a rota /dashboard carrega com sucesso (200 OK) e de forma pública."""
    setup_db_with_seed()
    response = client.get('/dashboard')
    assert response.status_code == 200
    assert b"Pulso Eleitoral" in response.data

def test_api_presidente(client):
    """Testa o endpoint público /api/pesquisas/presidente com dados do seed."""
    setup_db_with_seed()
    response = client.get('/api/pesquisas/presidente')
    assert response.status_code == 200
    data = response.json
    assert 'candidatos' in data
    assert 'percentuais' in data
    assert 'data_coleta' in data
    assert 'instituto' in data
    assert 'margem_erro' in data
    
    # Com o seed, deve conter os candidatos mais recentes
    assert len(data['candidatos']) > 0
    assert 'Lula' in data['candidatos']

def test_api_governador_rj(client):
    """Testa o endpoint público /api/pesquisas/governador-rj com dados do seed."""
    setup_db_with_seed()
    response = client.get('/api/pesquisas/governador-rj')
    assert response.status_code == 200
    data = response.json
    assert 'candidatos' in data
    assert 'percentuais' in data
    assert 'data_coleta' in data
    assert 'instituto' in data
    
    assert len(data['candidatos']) > 0
    assert 'Eduardo Paes' in data['candidatos']

def test_api_historico(client):
    """Testa o endpoint /api/pesquisas/historico?candidato=Lula com dados do seed."""
    setup_db_with_seed()
    response = client.get('/api/pesquisas/historico?candidato=Lula')
    assert response.status_code == 200
    data = response.json
    assert data['candidato'] == 'Lula'
    assert 'historico' in data
    assert len(data['historico']) > 0
    
    # Verifica chaves de um item do histórico
    first = data['historico'][0]
    assert 'data' in first
    assert 'percentual' in first
    assert 'instituto' in first

def test_api_institutos(client):
    """Testa o endpoint /api/institutos com dados do seed."""
    setup_db_with_seed()
    response = client.get('/api/institutos')
    assert response.status_code == 200
    data = response.json
    assert 'institutos' in data
    assert len(data['institutos']) == 14
    
    # Verifica a estrutura do primeiro item
    first = data['institutos'][0]
    assert 'nome' in first
    assert 'total' in first
    assert 'ultima_coleta' in first

def test_empty_database_handling(client):
    """Testa se as rotas da API se comportam de forma segura sem crashar quando o banco está sem dados (sem seed)."""
    setup_db_empty()
    
    # 1. Presidente
    res_pres = client.get('/api/pesquisas/presidente')
    assert res_pres.status_code == 200
    assert res_pres.json == {
        "candidatos": [],
        "percentuais": [],
        "data_coleta": None,
        "instituto": None,
        "margem_erro": None
    }
    
    # 2. Governador RJ
    res_gov = client.get('/api/pesquisas/governador-rj')
    assert res_gov.status_code == 200
    assert res_gov.json == {
        "candidatos": [],
        "percentuais": [],
        "data_coleta": None,
        "instituto": None,
        "margem_erro": None,
        "tipo": None
    }
    
    # 3. Histórico
    res_hist = client.get('/api/pesquisas/historico?candidato=Lula')
    assert res_hist.status_code == 200
    assert res_hist.json == {
        "candidato": "Lula",
        "historico": []
    }
    
    # 4. Institutos
    res_inst = client.get('/api/institutos')
    assert res_inst.status_code == 200
    assert res_inst.json == {
        "institutos": []
    }

def test_api_historico_multi(client):
    """Testa /api/pesquisas/historico-multi?cargo=presidente com dados do seed."""
    setup_db_with_seed()
    response = client.get('/api/pesquisas/historico-multi?cargo=presidente')
    assert response.status_code == 200
    data = response.json
    assert 'series' in data
    assert data['cargo'] == 'presidente'
    assert isinstance(data['series'], list)
    if data['series']:
        s = data['series'][0]
        assert 'candidato' in s
        assert 'cor' in s
        assert 'dados' in s

def test_api_comparativo(client):
    """Testa /api/comparativo?candidato=Lula&cargo=presidente com dados do seed."""
    setup_db_with_seed()
    response = client.get('/api/comparativo?candidato=Lula&cargo=presidente')
    assert response.status_code == 200
    data = response.json
    assert 'institutos' in data
    assert data['candidato'] == 'Lula'
    assert data['cargo'] == 'presidente'
    # Seed tem Lula como candidato; deve retornar lista (pode ser vazia se seed não tiver dados)
    assert isinstance(data['institutos'], list)

def test_api_alertas(client):
    """Testa GET /api/alertas?cargo=presidente&limiar=3.0 retorna JSON com chave alertas."""
    setup_db_with_seed()
    response = client.get('/api/alertas?cargo=presidente&limiar=3.0')
    assert response.status_code == 200
    data = response.json
    assert 'alertas' in data
    assert isinstance(data['alertas'], list)

def test_api_media_agregada(client):
    """Testa GET /api/media-agregada?cargo=presidente retorna candidatos."""
    setup_db_with_seed()
    # Janela larga o bastante para cobrir o seed (data máx 2026-06-10) independente do relógio
    import datetime
    dias = (datetime.date.today() - datetime.date(2026, 6, 10)).days + 30
    response = client.get(f'/api/media-agregada?cargo=presidente&dias={max(dias, 30)}')
    assert response.status_code == 200
    data = response.json
    assert 'candidatos' in data
    assert isinstance(data['candidatos'], list)
    assert 'cargo' in data
    assert data['cargo'] == 'presidente'
    assert 'total_pesquisas' in data
    assert 'institutos_incluidos' in data
    assert 'atualizado_em' in data
    primeiro = data['candidatos'][0]
    assert 'candidato' in primeiro
    assert 'media' in primeiro
    assert 'min' in primeiro
    assert 'max' in primeiro
    assert 'pesquisas_count' in primeiro

def test_api_media_agregada_dias_nao_numerico_nao_quebra(client):
    """Testa que ?dias=abc (não-numérico) não gera 500 — cai no default."""
    setup_db_with_seed()
    response = client.get('/api/media-agregada?cargo=presidente&dias=abc')
    assert response.status_code == 200
    data = response.json
    assert 'candidatos' in data

def test_api_alertas_params_nao_numericos_nao_quebram(client):
    """Testa que ?limiar=x&janela=y (não-numéricos) não geram 500 — caem no default."""
    setup_db_with_seed()
    response = client.get('/api/alertas?cargo=presidente&limiar=x&janela=y')
    assert response.status_code == 200
    data = response.json
    assert 'alertas' in data
    assert isinstance(data['alertas'], list)

from unittest.mock import patch, MagicMock

def test_api_visao_geral(client):
    """Testa o endpoint /api/visao-geral com dados do seed."""
    setup_db_with_seed()
    response = client.get('/api/visao-geral')
    assert response.status_code == 200
    data = response.json
    assert 'kpis' in data
    assert 'lider_presidente' in data
    assert 'lider_governador' in data
    assert 'tendencias' in data
    # Chaves do aviso de defasagem (plano 017): aninhadas sob kpis
    assert 'dias_desde_ultima' in data['kpis']
    assert 'ultima_atualizacao' in data['kpis']

    assert data['kpis']['total_pesquisas'] > 0
    assert data['lider_presidente']['candidato'] is not None
    assert len(data['tendencias']) > 0

def test_api_kpis_avancados(client):
    """Testa GET /api/kpis-avancados?cargo=presidente retorna as 6 chaves esperadas."""
    setup_db_with_seed()
    response = client.get('/api/kpis-avancados?cargo=presidente')
    assert response.status_code == 200
    data = response.json
    for chave in ('margem_lideranca', 'probabilidade_segundo_turno',
                  'tendencia_aceleracao', 'campo_minado',
                  'concentracao_voto', 'volatilidade'):
        assert chave in data, f"Chave ausente: {chave}"
    assert isinstance(data['tendencia_aceleracao'], list)
    assert isinstance(data['campo_minado'], list)
    assert isinstance(data['volatilidade']['candidatos'], list)
    assert data['volatilidade']['cenario_geral'] in ('estavel', 'moderado', 'volatil')

def test_api_simulacao(client):
    """Testa GET /api/simulacao-segundo-turno retorna JSON com chaves corretas."""
    setup_db_with_seed()
    response = client.get('/api/simulacao-segundo-turno')
    assert response.status_code == 200
    data = response.json
    assert 'primeiro_turno' in data
    assert 'segundo_turno' in data
    assert 'candidatos' in data['primeiro_turno']
    assert isinstance(data['primeiro_turno']['candidatos'], list)
    st = data['segundo_turno']
    for chave in ('lula', 'flavio', 'indefinido', 'nota'):
        assert chave in st, f"Chave ausente em segundo_turno: {chave}"
    assert 'total_estimado' in st['lula']
    assert 'total_estimado' in st['flavio']

def test_api_regional(client):
    """Testa GET /api/regional/presidente retorna JSON com chaves candidatos e estados."""
    setup_db_with_seed()
    response = client.get('/api/regional/presidente')
    assert response.status_code == 200
    data = response.json
    assert 'candidatos' in data
    assert 'estados' in data
    assert isinstance(data['candidatos'], list)
    assert isinstance(data['estados'], dict)

@patch('google.genai.Client')
def test_api_analise_cache(mock_client_class, client):
    """Testa o endpoint /api/visao-geral/analise com cache e mock do Gemini."""
    setup_db_with_seed()
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Esta é uma análise de IA mockada para testes."
    mock_client.models.generate_content.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    os.environ['GEMINI_API_KEY'] = 'fake-api-key-123'
    
    # 1. Primeira chamada: chama Gemini e salva em cache
    response = client.get('/api/visao-geral/analise')
    assert response.status_code == 200
    data = response.json
    assert 'analise' in data
    assert data['analise'] == "Esta é uma análise de IA mockada para testes."
    assert 'gerado_em' in data
    
    mock_client_class.assert_called_once()
    mock_client.models.generate_content.assert_called_once()
    
    # 2. Segunda chamada: lê do cache SQLite diretamente
    mock_client_class.reset_mock()
    mock_client.models.generate_content.reset_mock()
    
    response2 = client.get('/api/visao-geral/analise')
    assert response2.status_code == 200
    data2 = response2.json
    assert data2['analise'] == "Esta é uma análise de IA mockada para testes."
    
    mock_client_class.assert_not_called()
    mock_client.models.generate_content.assert_not_called()



# ─── Eventos da campanha (plano 015) ───────────────────────────────────────

def test_api_eventos_publico(client):
    """GET /api/eventos é público e retorna {"eventos": [...]}."""
    setup_db_with_seed()
    resp = client.get('/api/eventos')
    assert resp.status_code == 200
    assert 'eventos' in resp.json
    assert isinstance(resp.json['eventos'], list)


def test_criar_evento_exige_login(client):
    """POST /admin/eventos/criar sem sessão redireciona para /login."""
    resp = client.post('/admin/eventos/criar', data={
        'data': '2026-08-01', 'titulo': 'X', 'cargo': 'presidente', 'impacto': 'neutro'
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def _login(client):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'admin'
        sess['nome'] = 'Administrador'


def test_fluxo_criar_listar_remover_evento(client):
    """Criar evento válido → aparece na API; impacto inválido → nada criado;
    remover → some da lista."""
    setup_db_with_seed()
    _login(client)

    # cria válido
    resp = client.post('/admin/eventos/criar', data={
        'data': '2026-08-01', 'titulo': 'Debate Globo', 'cargo': 'presidente',
        'impacto': 'positivo', 'descricao': 'primeiro debate'
    }, follow_redirects=False)
    assert resp.status_code == 302

    eventos = client.get('/api/eventos?cargo=presidente').json['eventos']
    achado = [e for e in eventos if e['titulo'] == 'Debate Globo']
    assert len(achado) == 1
    ev_id = achado[0]['id']

    # impacto inválido não cria nada
    antes = len(client.get('/api/eventos').json['eventos'])
    client.post('/admin/eventos/criar', data={
        'data': '2026-08-02', 'titulo': 'Y', 'cargo': 'presidente', 'impacto': 'INVALIDO'
    }, follow_redirects=False)
    depois = len(client.get('/api/eventos').json['eventos'])
    assert depois == antes

    # remove
    client.post(f'/admin/eventos/{ev_id}/remover', follow_redirects=False)
    eventos2 = client.get('/api/eventos?cargo=presidente').json['eventos']
    assert not any(e['id'] == ev_id for e in eventos2)


def test_api_house_effects(client):
    """GET /api/house-effects é público e retorna shape com 'institutos' (lista)."""
    setup_db_with_seed()
    resp = client.get('/api/house-effects')
    assert resp.status_code == 200
    assert 'institutos' in resp.json
    assert isinstance(resp.json['institutos'], list)
    assert resp.json['cargo'] == 'presidente'
