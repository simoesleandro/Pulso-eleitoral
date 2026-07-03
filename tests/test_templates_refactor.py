import os
os.environ['TESTING'] = 'True'

import pytest
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
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret-key'
    with flask_app.test_client() as client:
        yield client


@pytest.fixture
def logged_in_client(client):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'admin'
        sess['nome'] = 'Administrador'
    return client


def setup_db_with_seed():
    init_db(force_seed=True)


# ─── Regressão funcional: rotas continuam 200 com conteúdo específico ──────

def test_dashboard_extends_base_mantem_conteudo(client):
    """/dashboard (agora via extends base.html) continua 200 e mantém as seções."""
    setup_db_with_seed()
    response = client.get('/dashboard')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert 'Presidente' in html
    assert 'secao-visao-geral' in html
    assert 'secao-governador' in html
    assert 'id="chart-presidente"' in html


def test_admin_painel_extends_base_mantem_conteudo(logged_in_client):
    """/admin (painel do scheduler, agora via extends base.html) continua 200."""
    setup_db_with_seed()
    response = logged_in_client.get('/admin')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert 'Painel de Controle do Scheduler' in html
    assert 'Últimos 10 Logs de Execução' in html
    assert 'btn-coletar' in html


def test_admin_usuarios_extends_base_mantem_conteudo(logged_in_client):
    """/admin/usuarios (agora via extends base.html) continua 200."""
    setup_db_with_seed()
    response = logged_in_client.get('/admin/usuarios')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert 'Gerenciamento de Usuários' in html
    assert 'Novo Usuário' in html


def test_admin_coletar_url_extends_base_mantem_conteudo(logged_in_client):
    """/admin/coletar-url (agora via extends base.html) continua 200."""
    response = logged_in_client.get('/admin/coletar-url')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert 'Coletar URL Específica' in html
    assert 'cu-btn' in html


def test_metodologia_extends_base_mantem_conteudo(client):
    """/metodologia (agora via extends base.html, com before_content/footer) continua 200."""
    response = client.get('/metodologia')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert 'Como o Pulso Eleitoral funciona' in html
    assert 'id="monte-carlo"' in html
    assert 'Voltar ao Dashboard' in html
    assert 'id="topbar-burger"' in html
    assert html.count('class="pe-topbar"') == 1


# ─── Navbar compartilhada: hambúrguer + logo chegam de graça nas páginas ───

def test_admin_painel_ganha_hamburguer_da_base(logged_in_client):
    """admin.html não tinha o botão hambúrguer antes do refactor — agora vem de base.html."""
    setup_db_with_seed()
    response = logged_in_client.get('/admin')
    html = response.data.decode('utf-8')
    assert 'id="topbar-burger"' in html
    assert 'id="topbar-nav"' in html


def test_admin_usuarios_ganha_hamburguer_da_base(logged_in_client):
    setup_db_with_seed()
    response = logged_in_client.get('/admin/usuarios')
    html = response.data.decode('utf-8')
    assert 'id="topbar-burger"' in html


def test_admin_coletar_url_ganha_hamburguer_da_base(logged_in_client):
    response = logged_in_client.get('/admin/coletar-url')
    html = response.data.decode('utf-8')
    assert 'id="topbar-burger"' in html


def test_admin_usa_pe_grid_3(logged_in_client):
    """admin.html usa pe-grid-3 pros 3 KPI cards do scheduler — classe agora existe em base.css."""
    setup_db_with_seed()
    response = logged_in_client.get('/admin')
    html = response.data.decode('utf-8')
    assert 'pe-grid-3' in html


# ─── Sem duplicação: nenhum style inline reimplementando o que base.css já faz ─

def test_admin_sem_navbar_duplicada_no_html(logged_in_client):
    """admin.html não deve mais definir sua própria <nav class="pe-topbar"> — só herda de base.html."""
    setup_db_with_seed()
    response = logged_in_client.get('/admin')
    html = response.data.decode('utf-8')
    assert html.count('class="pe-topbar"') == 1


def test_dashboard_sem_navbar_duplicada_no_html(client):
    setup_db_with_seed()
    response = client.get('/dashboard')
    html = response.data.decode('utf-8')
    assert html.count('class="pe-topbar"') == 1


def test_dashboard_sem_style_inline_no_logo(client):
    """O style inline do logo (display:flex...) que só existia em dashboard.html
    deve ter sumido — a regra agora vive em base.css (.pe-topbar__logo)."""
    setup_db_with_seed()
    response = client.get('/dashboard')
    html = response.data.decode('utf-8')
    assert 'pe-topbar__logo" href="/" style=' not in html


# ─── CSS: .pe-topbar__logo e .pe-grid-3 existem com as regras esperadas ────

def _read_base_css():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'css', 'base.css')
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def test_pe_topbar_logo_tem_flex_em_base_css():
    css = _read_base_css()
    assert '.pe-topbar__logo {' in css
    bloco = css.split('.pe-topbar__logo {')[1].split('}')[0]
    assert 'display: flex' in bloco
    assert 'align-items: center' in bloco
    assert 'gap:' in bloco


def test_pe_grid_3_existe_e_colapsa_em_mobile():
    css = _read_base_css()
    assert '.pe-grid-3 {' in css
    bloco = css.split('.pe-grid-3 {')[1].split('}')[0]
    assert 'display: grid' in bloco
    assert 'repeat(3, 1fr)' in bloco
    # breakpoint mobile (mesmo padrão de 767px usado no resto do arquivo)
    assert '@media (max-width: 767px)' in css
