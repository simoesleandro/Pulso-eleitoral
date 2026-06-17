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
    assert b"PULSO ELEITORAL" in response.data

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
    assert len(data['institutos']) == 7
    
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
        "margem_erro": None
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
    
    assert data['kpis']['total_pesquisas'] > 0
    assert data['lider_presidente']['candidato'] is not None
    assert len(data['tendencias']) > 0

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

