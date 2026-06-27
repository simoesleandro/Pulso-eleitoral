import os
# Configura o ambiente de testes antes de importar os módulos do projeto
os.environ['TESTING'] = 'True'

import pytest
import sqlite3
from database import get_conn, init_db, DB_PATH
from app import app as flask_app

@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Garante que o banco de dados de testes seja limpo antes e depois de cada teste."""
    # Apaga o banco de testes se ele existir antes de rodar o teste
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass
            
    yield
    
    # Limpa o banco de testes após o término do teste
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass

@pytest.fixture
def client():
    """Retorna um cliente de testes do Flask."""
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret-key'
    with flask_app.test_client() as client:
        yield client

def test_get_conn():
    """Teste 1: Verifica se get_conn retorna uma conexão SQLite válida com row_factory configurado."""
    conn = get_conn()
    assert isinstance(conn, sqlite3.Connection)
    assert conn.row_factory == sqlite3.Row
    
    # Valida se foreign keys estão habilitadas
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys")
    fk_enabled = cursor.fetchone()[0]
    assert fk_enabled == 1
    conn.close()

def test_schema_creates_tables():
    """Teste 2: Verifica se o schema.sql cria corretamente todas as 6 tabelas requeridas."""
    # Inicializa apenas o esquema (sem forçar o seed)
    init_db(force_seed=False)
    
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row['name'] for row in cursor.fetchall()]
    conn.close()
    
    expected_tables = ['institutos', 'pesquisas', 'intencoes', 'eventos', 'alertas', 'analises_ia']
    for table in expected_tables:
        assert table in tables, f"Tabela '{table}' não foi criada pelo schema.sql"

def test_seed_inserts_institutos():
    """Teste 3: Verifica se o seed.sql insere os 7 institutos corretamente no banco."""
    # Inicializa o banco rodando o schema e forçando a carga do seed.sql
    init_db(force_seed=True)
    
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, sigla FROM institutos ORDER BY id")
    institutos = cursor.fetchall()
    conn.close()
    
    assert len(institutos) == 9
    nomes_esperados = [
        'Datafolha', 'Ibope/IPEC', 'Quaest', 'Genial/Quaest', 
        'Atlas', 'Paraná', 'Real Time'
    ]
    for idx, nome in enumerate(nomes_esperados):
        assert institutos[idx]['nome'] == nome

def test_insert_and_read_research():
    """Teste 4: Valida a inserção e leitura de uma pesquisa e suas intenções de voto correspondentes."""
    init_db(force_seed=False)
    
    conn = get_conn()
    cursor = conn.cursor()
    
    # 1. Insere instituto
    cursor.execute(
        "INSERT INTO institutos (nome, sigla, site) VALUES (?, ?, ?)",
        ("Instituto Teste", "IT", "http://teste.com")
    )
    instituto_id = cursor.lastrowid
    
    # 2. Insere pesquisa
    cursor.execute(
        """INSERT INTO pesquisas 
           (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (instituto_id, "presidente", "2026-06-15", "2026-06-16", 1000, 3.0, "Contratante Teste", "BR-99999/2026", "http://fonte.com")
    )
    pesquisa_id = cursor.lastrowid
    
    # 3. Insere intenções de voto
    intencoes_data = [
        (pesquisa_id, "Candidato A", "Partido A", 45.5, "estimulada"),
        (pesquisa_id, "Candidato B", "Partido B", 35.0, "estimulada")
    ]
    cursor.executemany(
        "INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES (?, ?, ?, ?, ?)",
        intencoes_data
    )
    conn.commit()
    
    # 4. Lê dados de volta e verifica correspondência
    cursor.execute("SELECT * FROM pesquisas WHERE id = ?", (pesquisa_id,))
    pesquisa_row = cursor.fetchone()
    assert pesquisa_row['registro_tse'] == "BR-99999/2026"
    assert pesquisa_row['margem_erro'] == 3.0
    
    cursor.execute("SELECT * FROM intencoes WHERE pesquisa_id = ? ORDER BY percentual DESC", (pesquisa_id,))
    intencoes_rows = cursor.fetchall()
    assert len(intencoes_rows) == 2
    assert intencoes_rows[0]['candidato'] == "Candidato A"
    assert intencoes_rows[0]['percentual'] == 45.5
    assert intencoes_rows[1]['candidato'] == "Candidato B"
    assert intencoes_rows[1]['percentual'] == 35.0
    
    conn.close()

def test_auth_blocks_routes_without_login(client, monkeypatch):
    """Teste 5: Verifica se a autenticação bloqueia rotas protegidas e permite acesso a rotas livres."""
    # Define a senha admin explicitamente (não depende de .env / CI)
    monkeypatch.setenv('ADMIN_PASS', 'senha-de-teste-005')
    # Inicializa o banco de testes
    init_db(force_seed=True)
    
    # Acesso a rota livre (/api/status) deve retornar 200 OK sem necessidade de login
    response_status = client.get('/api/status')
    assert response_status.status_code == 200
    assert response_status.json["online"] is True
    assert "ultima_coleta" in response_status.json
    
    # Acesso a rota protegida (/) deve redirecionar (302) para /login
    response_root = client.get('/')
    assert response_root.status_code == 302
    assert response_root.headers['Location'].endswith('/login')
    
    # Login incorreto deve retornar 200 com mensagem de erro na tela
    response_login_fail = client.post('/login', data={'username': 'admin', 'password': 'wrongpass'})
    assert response_login_fail.status_code == 200
    assert b"Usu\xc3\xa1rio ou senha incorretos" in response_login_fail.data
    
    # Login correto deve redirecionar (302) para a raiz (/) e dar acesso
    response_login_success = client.post('/login', data={'username': 'admin', 'password': 'senha-de-teste-005'})
    assert response_login_success.status_code == 302
    assert response_login_success.headers['Location'].endswith('/')
    
    # Agora que está logado (na sessão do cliente de testes), acesso a (/) deve redirecionar (302) para /dashboard
    response_root_after = client.get('/')
    assert response_root_after.status_code == 302
    assert response_root_after.headers['Location'].endswith('/dashboard')
