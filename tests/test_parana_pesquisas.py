import os
os.environ['TESTING'] = 'True'

import pytest
from unittest.mock import patch
from collectors.paraná_pesquisas import (
    ParanaPesquisasCollector, _e_release_rj, _e_pdf_registro,
)

DB_PATH = "data/pulso_test.db"

LISTING_HTML = """
<html><body>
  <a href="/pesquisas/parana-pesquisas-rio-de-janeiro-governador-e-senador-julho-2026/">RJ governador</a>
  <a href="/pesquisas/parana-pesquisas-sao-paulo-governador-2026/">SP governador</a>
  <a href="/pesquisas/parana-pesquisas-presidente-nacional-2026/">Nacional</a>
</body></html>
"""

RELEASE_HTML = """
<html><body>
  <a href="https://cdn.paranapesquisas.com.br/RJ_Jul2026.pdf">Relatório completo</a>
  <a href="https://cdn.paranapesquisas.com.br/1-JOB026_116_RJ_-RegistroTSE_RJ-04259.pdf">Registro TSE</a>
</body></html>
"""


@pytest.fixture
def coletor():
    return ParanaPesquisasCollector(db_path=DB_PATH)


def test_helpers_marcadores_rj():
    assert _e_release_rj("/pesquisas/algo-rio-de-janeiro-governador/") is True
    assert _e_release_rj("/pesquisas/algo-sao-paulo-governador/") is False
    assert _e_pdf_registro("1-JOB026_116_RJ_-RegistroTSE_RJ-04259.pdf") is True
    assert _e_pdf_registro("RJ_Jul2026.pdf") is False


_BASE = "https://paranapesquisas.com.br/pesquisas/"


@pytest.mark.parametrize("slug", [
    # Slugs reais da listagem (2026-09-29): "rio" solto casava com todos.
    "parana-pesquisas-registra-pesquisa-no-estado-do-rio-grande-do-sul-para-os-cargos-de-governador-e-senador-registro-tse-n-o-rs-03898-2026-agosto-2026/",
    "parana-pesquisas-registra-pesquisa-no-estado-do-rio-grande-do-norte-para-os-cargos-de-governador-e-senador-registro-tse-n-o-rn-01234-2026-agosto-2026/",
    "cenarios-presidente-brasil-setembro-2026/",
    # Pesquisa de PRESIDENTE feita no RJ: é do RJ, mas não é de governador.
    # Mandar ao extrator de governador gravaria presidenciáveis como governador_rj.
    "parana-pesquisas-registra-pesquisa-no-estado-do-rio-de-janeiro-para-o-cargo-de-presidente-registro-tse-n-o-br-01920-2026-abril-2026/",
])
def test_release_rj_rejeita_outros_estados_e_presidente(slug):
    assert _e_release_rj(_BASE + slug) is False


@pytest.mark.parametrize("slug", [
    "parana-pesquisas-registra-pesquisa-no-estado-do-rio-de-janeiro-para-os-cargos-de-governador-e-senador-registro-tse-n-o-rj-04036-2026-setembro-2026/",
    "parana-pesquisas-registra-pesquisa-no-estado-do-rio-de-janeiro-para-os-cargos-de-governador-e-senador-registro-tse-n-o-rj-05645-2026-junho-2026/",
    "pesquisa-governador-rj-setembro-2026/",
    "pesquisa-governador_rj_setembro/",
])
def test_release_rj_aceita_releases_do_rio(slug):
    assert _e_release_rj(_BASE + slug) is True


def test_extract_links_listagem_real(coletor):
    """Amostra real das páginas 1–8 da listagem: só os 6 releases de
    governador do RJ passam (nenhum RS, nenhum presidente-no-RJ)."""
    caminho = os.path.join(os.path.dirname(__file__), "fixtures", "parana", "listagem_amostra.html")
    with open(caminho, encoding="utf-8") as f:
        links = coletor._extract_links(f.read())

    registros = sorted(l.split("registro-tse-n-o-")[1][:11] for l in links)
    assert registros == [
        "rj-01671-20", "rj-02422-20", "rj-04036-20",
        "rj-04259-20", "rj-05645-20", "rj-09303-20",
    ]


def test_extract_links_so_rj(coletor):
    """Só releases do RJ entram; SP e nacional são descartados."""
    links = coletor._extract_links(LISTING_HTML)
    assert any('rio-de-janeiro' in l for l in links)
    assert not any('sao-paulo' in l for l in links)
    assert not any('presidente-nacional' in l for l in links)


def test_extract_pdf_url_ignora_registro(coletor):
    """Pega o PDF do relatório, não o do registro no TSE."""
    pdf = coletor._extract_pdf_url(RELEASE_HTML)
    assert pdf is not None
    assert pdf.endswith('RJ_Jul2026.pdf')


def test_parse_release_monta_itens_governador(coletor):
    """_parse_release monta itens com cargo=governador_rj a partir da saída do extrator."""
    fake = {
        "cargo": "governador_rj", "tipo": "estimulada", "data": "2026-07-01",
        "tamanho_amostra": 1600, "margem_erro": 2.5,
        "candidatos": [
            {"nome": "Eduardo Paes", "percentual": 54.2},
            {"nome": "Douglas Ruas", "percentual": 14.6},
        ],
    }
    with patch.object(coletor, '_download_pdf_text', return_value="texto do pdf governador rj"), \
         patch('collectors.gemini_extractor.extrair_governador_rj', return_value=fake):
        itens = coletor._parse_release(RELEASE_HTML, "https://paranapesquisas.com.br/pesquisas/rj/")

    assert len(itens) == 2
    assert all(i['cargo'] == 'governador_rj' for i in itens)
    assert {i['candidato'] for i in itens} == {"Eduardo Paes", "Douglas Ruas"}
    assert all(i['instituto_id'] == 6 for i in itens)
    assert all(i['data_pesquisa'] == "2026-07-01" for i in itens)


def test_parse_release_sem_pdf_retorna_vazio(coletor):
    """Release sem link de PDF → lista vazia, sem crashar."""
    assert coletor._parse_release("<html><body>sem pdf aqui</body></html>", "url") == []


def test_parse_release_pdf_vazio_retorna_vazio(coletor):
    """PDF que não extrai texto → lista vazia (não chama o extrator)."""
    with patch.object(coletor, '_download_pdf_text', return_value=""):
        assert coletor._parse_release(RELEASE_HTML, "url") == []


def test_fetch_sem_rede_retorna_vazio(coletor):
    """fetch() com _get_page vazio (sem rede) retorna [] sem crashar."""
    with patch.object(coletor, '_get_page', return_value=""):
        assert coletor.fetch() == []
