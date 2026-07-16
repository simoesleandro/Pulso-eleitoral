import os
# Configura o ambiente de testes antes de importar os módulos do projeto
os.environ['TESTING'] = 'True'
# Fixa uma senha admin conhecida ANTES do seed (init_db lê ADMIN_PASS no seed) —
# mesmo cuidado de tests/test_usuarios.py, embora aqui a senha usada no POST
# seja sempre incorreta (só o retorno 200 vs 429 importa, não o login em si).
os.environ.setdefault('ADMIN_PASS', 'test-admin-pass')

import pytest

from database import DB_PATH, init_db
from app import app as flask_app, limiter


@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Garante que o banco de testes exista antes de cada teste, seguindo o
    mesmo padrão de tests/test_database.py e tests/test_usuarios.py: DB_PATH
    é um arquivo compartilhado por todo o processo de pytest (não isolado por
    teste), e outros arquivos de teste apagam esse arquivo no próprio
    teardown — sem recriar aqui, uma requisição a /login vira
    'OperationalError: no such table: usuarios' dependendo da ordem de
    execução dos arquivos."""
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
    """Retorna um cliente de testes do Flask (padrão usado em tests/test_apply_db.py)."""
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret-key'
    with flask_app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def _reset_limiter_storage():
    """Zera o storage do Flask-Limiter antes e depois de cada teste deste
    arquivo.

    O decorator `@limiter.limit("5 per minute")` em /login (app.py) não é
    neutralizado por TESTING=True — só o limite *padrão* (`default_limits`)
    é. Isso é intencional (é o próprio mecanismo de defesa sendo testado),
    mas como o storage é em memória e compartilhado pelo processo inteiro de
    pytest, sem o reset a quota consumida aqui vazaria para
    tests/test_database.py e tests/test_usuarios.py (que também fazem POST
    em /login), fazendo-os falhar com 429 dependendo da ordem de execução.
    """
    limiter.reset()
    yield
    limiter.reset()


def test_login_bloqueia_apos_5_tentativas_por_minuto(client):
    """/login aceita no máximo 5 requisições por minuto (mesmo IP) — a 6a
    deve retornar 429, confirmando a mitigação de força bruta do plano 020."""
    respostas = []
    for _ in range(6):
        resp = client.post(
            '/login',
            data={'username': 'admin', 'password': 'senha-errada'},
        )
        respostas.append(resp.status_code)

    assert respostas[:5] == [200, 200, 200, 200, 200]
    assert respostas[5] == 429


def test_api_status_nao_e_bloqueado_por_requisicao_unica(client):
    """Uma única requisição normal a um endpoint público (/api/status) não
    deve ser afetada pelo rate limiting — confirma que o limite não quebra
    uso legítimo."""
    resp = client.get('/api/status')
    assert resp.status_code == 200
