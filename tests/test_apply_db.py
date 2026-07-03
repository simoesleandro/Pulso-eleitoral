import os
# Configura o ambiente de testes antes de importar os módulos do projeto
os.environ['TESTING'] = 'True'

import sqlite3
from unittest.mock import patch

import pytest
from app import app as flask_app


@pytest.fixture
def client():
    """Retorna um cliente de testes do Flask."""
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret-key'
    with flask_app.test_client() as client:
        yield client


@pytest.fixture
def data_dir():
    """Garante /data (caminho hardcoded em apply_db) e limpa só o que este
    teste criou — não mexe em nada que já existisse ali antes."""
    existia = os.path.isdir('/data')
    if not existia:
        os.makedirs('/data')
    criados = []
    yield criados
    for path in criados:
        if os.path.exists(path):
            os.remove(path)
    if not existia and os.path.isdir('/data') and not os.listdir('/data'):
        os.rmdir('/data')


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


def test_troca_bem_sucedida_invalida_cache(client, monkeypatch, data_dir):
    """Troca bem-sucedida do banco (arquivo SQLite válido com tabela
    `pesquisas`) deve chamar cache.clear() logo depois do shutil.move."""
    monkeypatch.setenv('ADMIN_PASS', 'senha-de-teste-006')

    filename = 'pulso_upload_teste_sucesso.db'
    new_db_path = f'/data/{filename}'
    current_db_path = '/data/pulso.db'
    data_dir.append(new_db_path)
    data_dir.append(current_db_path)

    conn = sqlite3.connect(new_db_path)
    conn.execute("CREATE TABLE pesquisas (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    with patch('app.cache.clear') as mock_clear:
        resp = client.post(
            '/admin/apply-db',
            json={'filename': filename},
            headers={'X-Admin-Pass': 'senha-de-teste-006'},
        )
        assert resp.status_code == 200
        assert resp.json['ok'] is True
        mock_clear.assert_called_once()


def test_falha_integridade_nao_invalida_cache(client, monkeypatch, data_dir):
    """Se a validação de integridade falhar (arquivo não é um SQLite válido
    do Pulso), cache.clear() NÃO deve ser chamado — não invalida cache bom
    por causa de um sync que falhou."""
    monkeypatch.setenv('ADMIN_PASS', 'senha-de-teste-007')

    filename = 'pulso_upload_teste_falha.db'
    new_db_path = f'/data/{filename}'
    data_dir.append(new_db_path)

    with open(new_db_path, 'wb') as f:
        f.write(b'isso nao e um banco sqlite valido')

    with patch('app.cache.clear') as mock_clear:
        resp = client.post(
            '/admin/apply-db',
            json={'filename': filename},
            headers={'X-Admin-Pass': 'senha-de-teste-007'},
        )
        assert resp.status_code == 422
        mock_clear.assert_not_called()
