import os
# Configura o ambiente de testes antes de importar
os.environ['TESTING'] = 'True'

import pytest
import sqlite3
import json
from unittest.mock import patch
from database import get_conn, init_db, DB_PATH, salvar_log_scheduler, buscar_ultimo_log
from app import app as flask_app, run_all_collectors, scheduler

@pytest.fixture(autouse=True)
def setup_db():
    """Garante que o banco de dados de teste seja recriado limpo antes de cada teste."""
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass
            
    init_db(force_seed=False)
    yield
    
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass

@pytest.fixture
def client():
    """Retorna o cliente de testes Flask e configura a sessão como logada por padrão."""
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret-key'
    with flask_app.test_client() as client:
        with client.session_transaction() as sess:
            sess['logged_in'] = True
        yield client

def test_run_all_collectors():
    """Testa que run_all_collectors() executa e retorna lista estruturada com pelo menos um item."""
    resultados = run_all_collectors()
    assert isinstance(resultados, list)
    assert len(resultados) >= 1
    
    for item in resultados:
        assert 'coletor' in item
        assert 'status' in item
        # 'vazio' = rodou sem exceção e não salvou nada; 'parcial' = alguns
        # releases falharam. Antes ambos vinham como 'ok' e a quebra sumia.
        assert item['status'] in ['ok', 'vazio', 'parcial', 'erro']

def test_salvar_e_buscar_ultimo_log():
    """Testa salvar_log_scheduler() e buscar_ultimo_log() no banco de dados temporário."""
    mock_resultados = [
        {"coletor": "DatafolhaCollector", "status": "ok"},
        {"coletor": "FakeCollector", "status": "erro", "msg": "timeout"}
    ]
    
    # Grava o log
    salvar_log_scheduler(mock_resultados)
    
    # Recupera o log mais recente
    ultimo = buscar_ultimo_log()
    assert ultimo is not None
    assert ultimo['job'] == 'coleta_diaria'
    assert len(ultimo['resultado']) == 2
    assert ultimo['resultado'][0]['coletor'] == 'DatafolhaCollector'
    assert ultimo['resultado'][0]['status'] == 'ok'
    assert ultimo['resultado'][1]['coletor'] == 'FakeCollector'
    assert ultimo['resultado'][1]['status'] == 'erro'
    assert 'executado_em' in ultimo

def test_scheduler_does_not_start_in_testing():
    """Testa que o scheduler não foi iniciado/startado quando em modo de teste."""
    assert scheduler.running is False

def test_route_admin_coletar(client):
    """Testa que a rota GET/POST /admin/coletar dispara a coleta e retorna JSON formatado."""
    # Como queremos testar a rota sem chamar a rede, podemos mockar o run_all_collectors
    with patch('app.run_all_collectors') as mock_run:
        mock_run.return_value = [{"coletor": "DatafolhaCollector", "status": "ok"}]
        
        response = client.get('/admin/coletar')
        assert response.status_code == 200
        data = response.json
        assert data['status'] == 'ok'
        assert 'timestamp' in data
        assert data['coletores'] == 1
        assert len(data['resultados']) == 1
        assert data['resultados'][0]['coletor'] == 'DatafolhaCollector'

def test_route_admin_logs(client):
    """Testa que a rota /admin/logs retorna a chave 'logs' no JSON."""
    response = client.get('/admin/logs')
    assert response.status_code == 200
    data = response.json
    assert 'logs' in data
    assert isinstance(data['logs'], list)
