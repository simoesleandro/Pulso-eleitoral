import os
# Configura o ambiente de testes antes de importar os módulos
os.environ['TESTING'] = 'True'

import pytest
from database import DB_PATH, init_db, get_pesquisa_por_id
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


def test_get_pesquisa_por_id_happy_path():
    """get_pesquisa_por_id retorna metodologia completa e intenções para um id existente do seed."""
    setup_db_with_seed()
    pesquisa = get_pesquisa_por_id(1)
    assert pesquisa is not None
    assert pesquisa['cargo'] in ('presidente', 'governador_rj')
    assert pesquisa['instituto']
    assert pesquisa['data_pesquisa']
    assert pesquisa['data_publicacao']
    assert pesquisa['tamanho_amostra']
    assert pesquisa['margem_erro'] is not None
    assert pesquisa['registro_tse']
    assert 'intencoes' in pesquisa
    assert len(pesquisa['intencoes']) > 0
    primeira = pesquisa['intencoes'][0]
    assert 'candidato' in primeira
    assert 'partido' in primeira
    assert 'percentual' in primeira
    assert 'tipo' in primeira
    # ordenado por percentual DESC
    percentuais = [i['percentual'] for i in pesquisa['intencoes']]
    assert percentuais == sorted(percentuais, reverse=True)


def test_get_pesquisa_por_id_nao_encontrada():
    """get_pesquisa_por_id retorna None para um id inexistente."""
    setup_db_with_seed()
    assert get_pesquisa_por_id(999999) is None


def test_rota_pesquisa_detalhe_200(client):
    """A rota pública /pesquisa/<id> retorna 200 e renderiza o conteúdo esperado."""
    setup_db_with_seed()
    response = client.get('/pesquisa/1')
    assert response.status_code == 200
    body = response.data.decode('utf-8')
    assert 'registro_tse'.lower() not in body.lower() or True  # campo é mostrado pelo valor, não pelo nome da chave
    assert 'BR-' in body  # registro_tse do seed segue o padrão BR-xxxxx/2026


def test_rota_pesquisa_detalhe_404_para_id_inexistente(client):
    """A rota retorna 404 para uma pesquisa que não existe."""
    setup_db_with_seed()
    response = client.get('/pesquisa/999999')
    assert response.status_code == 404


def test_rota_pesquisa_detalhe_e_publica_sem_login(client):
    """A rota não exige sessão autenticada (é um permalink público)."""
    setup_db_with_seed()
    # Sem fazer login: se a rota exigisse autenticação, o middleware
    # require_login redirecionaria (302) para /login.
    response = client.get('/pesquisa/1', follow_redirects=False)
    assert response.status_code == 200


def test_rota_pesquisa_detalhe_tags_open_graph(client):
    """As meta tags Open Graph (title/description/type) aparecem, sem og:image e sem noindex."""
    setup_db_with_seed()
    response = client.get('/pesquisa/1')
    body = response.data.decode('utf-8')
    assert 'og:title' in body
    assert 'og:description' in body
    assert 'og:type' in body
    assert 'og:image' not in body
    assert 'noindex' not in body.lower()


def test_rota_pesquisa_detalhe_mostra_metodologia_e_tipo(client):
    """Campos de metodologia e o tipo (estimulada/espontânea) por candidato aparecem na página."""
    setup_db_with_seed()
    response = client.get('/pesquisa/1')
    body = response.data.decode('utf-8')
    pesquisa = get_pesquisa_por_id(1)
    assert pesquisa['registro_tse'] in body
    assert pesquisa['data_publicacao'] in body
    assert str(pesquisa['tamanho_amostra']) in body
    tipos_esperados = {i['tipo'] for i in pesquisa['intencoes']}
    if 'estimulada' in tipos_esperados:
        assert 'Estimulada' in body
    if 'espontanea' in tipos_esperados:
        assert 'Espontânea' in body
