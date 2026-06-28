import os
os.environ['TESTING'] = 'True'
# Fixa uma senha admin conhecida ANTES do seed (init_db lê ADMIN_PASS no seed).
# Sem isso, em ambientes sem .env/secret (ex.: CI) o admin é semeado com senha
# aleatória (plano 005 removeu o default 'pulso2026') e os testes de login falham.
os.environ.setdefault('ADMIN_PASS', 'test-admin-pass')

import pytest
from database import (
    get_conn, init_db, DB_PATH, criar_usuario, verificar_usuario, 
    listar_usuarios, remover_usuario, toggle_usuario
)
from app import app as flask_app

@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Garante que o banco de dados de testes seja limpo antes e depois de cada teste."""
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass
            
    # Inicializa o banco de dados e cria a tabela usuarios
    init_db(force_seed=False)
    
    yield
    
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

def test_criar_e_verificar_usuario():
    """Valida a criação e verificação básica de usuário com bcrypt (hashing)."""
    # 1. Cria usuário
    sucesso = criar_usuario("user_teste", "senha_secreta", "Usuário Teste")
    assert sucesso is True
    
    # 2. Verifica senha correta
    user = verificar_usuario("user_teste", "senha_secreta")
    assert user is not None
    assert user['username'] == "user_teste"
    assert user['nome'] == "Usuário Teste"
    assert user['ativo'] == 1
    
    # 3. Verifica se o login atualizou 'ultimo_login'
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT ultimo_login FROM usuarios WHERE username = 'user_teste'")
    ultimo_login = cursor.fetchone()[0]
    assert ultimo_login is not None
    conn.close()

def test_impedimento_duplicados():
    """Garante que não é possível criar nomes de usuários duplicados."""
    sucesso1 = criar_usuario("duplicate_user", "senha1", "User 1")
    assert sucesso1 is True
    
    sucesso2 = criar_usuario("duplicate_user", "senha2", "User 2")
    assert sucesso2 is False

def test_validacao_senha_incorreta():
    """Garante que tentar verificar com senha incorreta retorna None."""
    criar_usuario("valid_user", "correct_pass", "Valid User")
    
    # Senha incorreta
    user = verificar_usuario("valid_user", "wrong_pass")
    assert user is None
    
    # Usuário inexistente
    user = verificar_usuario("non_existing", "any_pass")
    assert user is None

def test_bloqueio_conta_desativada():
    """Garante que contas inativas (ativo = 0) não conseguem fazer login."""
    criar_usuario("inactive_user", "some_pass", "Inactive User")
    
    # 1. Desativa a conta
    conn = get_conn()
    conn.execute("UPDATE usuarios SET ativo = 0 WHERE username = 'inactive_user'")
    conn.commit()
    conn.close()
    
    # 2. Tenta fazer login
    user = verificar_usuario("inactive_user", "some_pass")
    assert user is None

def test_remover_usuario():
    """Garante que remoção de usuário funciona e retorna status correto."""
    criar_usuario("remove_me", "pass", "Remove Me")
    
    # 1. Pega o ID
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM usuarios WHERE username = 'remove_me'")
    user_id = cursor.fetchone()[0]
    conn.close()
    
    # 2. Remove o usuário
    sucesso = remover_usuario(user_id)
    assert sucesso is True
    
    # 3. Verifica que não existe mais no banco
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM usuarios WHERE username = 'remove_me'")
    count = cursor.fetchone()[0]
    conn.close()
    assert count == 0

def test_toggle_usuario():
    """Garante que ativação/desativação funciona perfeitamente."""
    criar_usuario("toggle_user", "pass", "Toggle")
    
    # 1. Pega o ID e verifica ativo = 1
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, ativo FROM usuarios WHERE username = 'toggle_user'")
    row = cursor.fetchone()
    user_id = row['id']
    assert row['ativo'] == 1
    conn.close()
    
    # 2. Desativa via toggle_usuario
    sucesso = toggle_usuario(user_id)
    assert sucesso is True
    
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT ativo FROM usuarios WHERE id = ?", (user_id,))
    assert cursor.fetchone()[0] == 0
    conn.close()
    
    # 3. Ativa via toggle_usuario novamente
    sucesso = toggle_usuario(user_id)
    assert sucesso is True
    
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT ativo FROM usuarios WHERE id = ?", (user_id,))
    assert cursor.fetchone()[0] == 1
    conn.close()

def test_inicializacao_admin_padrao():
    """Valida que o admin padrão é criado na inicialização inicial do banco."""
    # init_db() já roda no fixture setup_and_teardown, então admin padrão já deve estar lá
    admin_pass = os.getenv('ADMIN_PASS', 'pulso2026')
    user = verificar_usuario("admin", admin_pass)
    assert user is not None
    assert user['username'] == "admin"
    assert user['nome'] == "Administrador"

def test_integracao_login_post(client):
    """Valida a rota /login com requisições POST com credenciais corretas e incorretas."""
    # 1. POST com senha incorreta
    response = client.post('/login', data={'username': 'admin', 'password': 'incorrect_password'}, follow_redirects=True)
    assert "Usuário ou senha incorretos".encode('utf-8') in response.data or b"incorretos" in response.data
    
    # 2. POST com credenciais corretas
    admin_pass = os.getenv('ADMIN_PASS', 'pulso2026')
    response = client.post('/login', data={'username': 'admin', 'password': admin_pass}, follow_redirects=True)
    # Deve redirecionar para a index (ou dashboard) e a sessão estar logada
    assert response.status_code == 200
    # Verifica se a página contém links/conteúdos da dashboard
    assert b"Dashboard" in response.data or "Visão Geral".encode('utf-8') in response.data or b"presidente" in response.data

def test_bloqueio_acesso_sem_sessao(client):
    """Garante que o acesso a /admin/usuarios sem sessão ativa seja redirecionado para /login."""
    response = client.get('/admin/usuarios', follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers['Location']
    
    # E com sessão ativa deve passar
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'admin'
        sess['nome'] = 'Administrador'
        
    response = client.get('/admin/usuarios', follow_redirects=False)
    assert response.status_code == 200
