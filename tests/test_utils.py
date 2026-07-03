import os
os.environ['TESTING'] = 'True'

from collectors.utils import detectar_uf


def test_detectar_uf_menciona_estado_na_url():
    """URL com slug de estado deve retornar a sigla correta."""
    assert detectar_uf("https://exame.com/pesquisa-presidencial-rio-de-janeiro/", "") == "RJ"


def test_detectar_uf_menciona_estado_no_texto():
    """Texto mencionando o estado (sem estar na URL) também deve ser detectado."""
    assert detectar_uf("https://exame.com/pesquisa-lula-41/", "Lula tem 41,6% no Rio de Janeiro") == "RJ"


def test_detectar_uf_sigla_isolada():
    """Sigla de UF (token isolado) também deve ser reconhecida."""
    assert detectar_uf("https://site.com/pesquisa-sp-2026/", "") == "SP"


def test_detectar_uf_ausencia_de_mencao():
    """Texto/URL sem nenhuma menção de estado deve retornar None."""
    assert detectar_uf("https://site.com/pesquisa-presidencial-nacional/", "Pesquisa nacional com Lula e Flávio Bolsonaro") is None


def test_detectar_uf_nao_confunde_para_com_parana():
    """'para' (PA) não deve dar falso positivo dentro de 'parana' (PR)."""
    assert detectar_uf("https://site.com/parana-pesquisas-presidente/", "") == "PR"
