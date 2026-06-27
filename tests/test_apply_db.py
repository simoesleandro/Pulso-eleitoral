import os
# Configura o ambiente de testes antes de importar os módulos do projeto
os.environ['TESTING'] = 'True'

import pytest
from app import app as flask_app


@pytest.fixture
def client():
    """Retorna um cliente de testes do Flask."""
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret-key'
    with flask_app.test_client() as client:
        yield client


def test_sem_admin_pass_e_sem_header_recusa(client, monkeypatch):
    """Regressão do bypass None==None: sem ADMIN_PASS no ambiente e sem header → 401."""
    monkeypatch.delenv('ADMIN_PASS', raising=False)
    resp = client.post('/admin/apply-db', json={'filename': 'pulso_upload_1.db'})
    assert resp.status_code == 401
    assert resp.json['error'] == 'unauthorized'


def test_header_errado_recusa(client, monkeypatch):
    """ADMIN_PASS setada + header errado → 401."""
    monkeypatch.setenv('ADMIN_PASS', 'senha-de-teste-003')
    resp = client.post(
        '/admin/apply-db',
        json={'filename': 'pulso_upload_1.db'},
        headers={'X-Admin-Pass': 'errada'},
    )
    assert resp.status_code == 401


def test_filename_com_traversal_recusa(client, monkeypatch):
    """Header correto + filename com separador de caminho → 400 (path traversal)."""
    monkeypatch.setenv('ADMIN_PASS', 'senha-de-teste-003')
    resp = client.post(
        '/admin/apply-db',
        json={'filename': 'pulso_upload_/../../etc/passwd.db'},
        headers={'X-Admin-Pass': 'senha-de-teste-003'},
    )
    assert resp.status_code == 400


def test_filename_valido_arquivo_inexistente(client, monkeypatch):
    """Header correto + filename válido + arquivo inexistente → 404."""
    monkeypatch.setenv('ADMIN_PASS', 'senha-de-teste-003')
    resp = client.post(
        '/admin/apply-db',
        json={'filename': 'pulso_upload_inexistente.db'},
        headers={'X-Admin-Pass': 'senha-de-teste-003'},
    )
    assert resp.status_code == 404
