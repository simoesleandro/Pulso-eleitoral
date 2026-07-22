import os
os.environ['TESTING'] = 'True'

from datetime import date, timedelta

import pytest

from app import app as flask_app
from database import DB_PATH, get_conn, init_db


@pytest.fixture(autouse=True)
def cleanup():
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
    init_db(force_seed=True)
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret-key'
    flask_app.config['WTF_CSRF_ENABLED'] = False
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def logado(client):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'admin'
    return client


def _dia(delta):
    return (date.today() + timedelta(days=delta)).isoformat()


def _registro(protocolo, cnpj, inicio, fim, empresa, cargo='presidente',
              amostra=2000):
    conn = get_conn()
    try:
        conn.execute("""INSERT INTO pesquisas_tse
            (protocolo, cargo, cnpj_empresa, nome_empresa, data_inicio,
             data_fim, data_divulgacao, qt_entrevistado, abrangencia)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'nacional')""",
            (protocolo, cargo, cnpj, empresa, inicio, fim, fim, amostra))
        conn.commit()
    finally:
        conn.close()


def test_cobertura_exige_login(client):
    resposta = client.get('/admin/cobertura')
    assert resposta.status_code in (302, 401)


def test_cobertura_abre_logado(logado):
    resposta = logado.get('/admin/cobertura')
    assert resposta.status_code == 200
    assert 'cobertura' in resposta.get_data(as_text=True).lower()


def test_ligar_exige_login(client):
    resposta = client.post('/admin/cobertura/ligar',
                           data={'protocolo': 'X', 'pesquisa_id': '1'})
    assert resposta.status_code in (302, 401)


def test_avaliar_instituto_exige_login(client):
    resposta = client.post('/admin/cobertura/instituto',
                           data={'cnpj': '999', 'nome': 'X', 'acao': 'aprovar'})
    assert resposta.status_code in (302, 401)


def test_ligar_com_protocolo_inexistente_nao_quebra(logado):
    resposta = logado.post('/admin/cobertura/ligar',
                           data={'protocolo': 'NAOEXISTE', 'pesquisa_id': '1'},
                           follow_redirects=True)
    assert resposta.status_code == 200
    assert 'não encontrado' in resposta.get_data(as_text=True)


def test_aprovar_instituto_pela_rota(logado):
    _registro('X1', '999', _dia(-10), _dia(-8), 'VETOR ARROW LTDA')

    resposta = logado.post('/admin/cobertura/instituto',
                           data={'cnpj': '999', 'nome': 'Vetor Arrow',
                                 'acao': 'aprovar'},
                           follow_redirects=True)

    assert resposta.status_code == 200
    conn = get_conn()
    try:
        linha = conn.execute(
            "SELECT nome, agregar FROM institutos WHERE cnpj = '999'").fetchone()
    finally:
        conn.close()
    assert linha['nome'] == 'Vetor Arrow'
    assert linha['agregar'] == 1


def test_api_em_campo_e_publica(client):
    """Sem login: é conteúdo do dashboard."""
    resposta = client.get('/api/em-campo')
    assert resposta.status_code == 200
    assert isinstance(resposta.get_json(), list)


def test_api_em_campo_nao_traz_agendada(client):
    _registro('AGENDADA', '999', _dia(+10), _dia(+13), 'FUTURA LTDA', amostra=14000)
    _registro('AGORA', '888', _dia(0), _dia(0), 'ATUAL LTDA')

    protocolos = [item['protocolo'] for item in client.get('/api/em-campo').get_json()]

    assert 'AGORA' in protocolos
    assert 'AGENDADA' not in protocolos, "tracking agendado não é 'em campo agora'"
