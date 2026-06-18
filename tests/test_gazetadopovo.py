import os
os.environ['TESTING'] = 'True'

import pytest
from unittest.mock import patch, MagicMock
from collectors.gazetadopovo import GazetaDoPovoColetor

DB_PATH = "data/pulso_test.db"

MOCK_LISTING_HTML = """
<html><body>
  <a href="/eleicoes/2026/pesquisa-eleitoral-2026/real-time-big-data-presidente-junho-2026/">Real Time Big Data: pesquisa presidente junho 2026</a>
  <a href="/eleicoes/2026/pesquisa-eleitoral-2026/real-time-big-data-governador-sp-2026/">Real Time: governador SP</a>
  <a href="/eleicoes/2026/pesquisa-eleitoral-2026/atlas-pesquisa-presidente-2026/">Atlas Intel: pesquisa presidente 2026</a>
  <a href="/eleicoes/2026/pesquisa-eleitoral-2026/quaest-presidente-maio-2026/">Quaest: presidente maio 2026</a>
  <a href="https://www.gazetadopovo.com.br/eleicoes/2026/pesquisa-eleitoral-2026/doxa-presidente-junho-2026/">Doxa: pesquisa presidente</a>
  <a href="/outras-noticias/sem-instituto/">Notícia genérica</a>
</body></html>
"""

MOCK_RELEASE_HTML = """
<html><body>
  <h1>Real Time Big Data divulgou pesquisa para presidente</h1>
  <p>Lula: 45% | Flávio Bolsonaro: 40% | Ronaldo Caiado: 5%</p>
  <p>2.000 entrevistados. Margem de erro: 2 pontos percentuais.</p>
  <p>Pesquisa realizada entre 10/06/2026 e 12/06/2026.</p>
</body></html>
"""


@pytest.fixture
def coletor():
    return GazetaDoPovoColetor(db_path=DB_PATH)


def test_extract_links_filtra_governador(coletor):
    """Links de governador/senador/deputado devem ser excluídos."""
    links = coletor._extract_links(MOCK_LISTING_HTML)
    assert not any('governador' in l for l in links)
    assert not any('senador' in l for l in links)


def test_extract_links_institutos_alvo(coletor):
    """Inclui real-time e atlas, exclui quaest (não está em INSTITUTOS_ALVO)."""
    links = coletor._extract_links(MOCK_LISTING_HTML)
    # real-time e atlas devem estar
    assert any('real-time' in l for l in links)
    assert any('atlas' in l for l in links)
    # quaest não está em INSTITUTOS_ALVO
    assert not any('quaest' in l for l in links)


def test_extract_links_url_absoluta(coletor):
    """Todos os links retornados devem ser URLs absolutas."""
    links = coletor._extract_links(MOCK_LISTING_HTML)
    for link in links:
        assert link.startswith('http'), f"Link não absoluto: {link}"


def test_extract_links_max_10(coletor):
    """Não retorna mais de 20 links."""
    html = "<html><body>" + "".join(
        f'<a href="/eleicoes/2026/pesquisa-eleitoral-2026/real-time-presidente-{i}/">Real Time presidente {i}</a>'
        for i in range(25)
    ) + "</body></html>"
    links = coletor._extract_links(html)
    assert len(links) <= 20


def test_detectar_instituto_real_time(coletor):
    """Texto com 'real time' deve retornar id=7."""
    assert coletor._detectar_instituto_id("Real Time Big Data pesquisa presidente", "") == 7


def test_detectar_instituto_atlas(coletor):
    """Texto com 'atlas' deve retornar id=5."""
    assert coletor._detectar_instituto_id("AtlasIntel divulga pesquisa", "") == 5


def test_detectar_instituto_parana(coletor):
    """Texto com 'parana' deve retornar id=6."""
    assert coletor._detectar_instituto_id("Paraná Pesquisas aponta", "") == 6


def test_detectar_instituto_nexus(coletor):
    """Texto com 'nexus' deve retornar id=8."""
    assert coletor._detectar_instituto_id("Nexus BTG Pactual pesquisa presidente", "") == 8

def test_detectar_instituto_btg(coletor):
    """Texto com 'btg' deve retornar id=8."""
    assert coletor._detectar_instituto_id("pesquisa BTG Pactual junho", "") == 8

def test_detectar_instituto_verita(coletor):
    """Texto com 'verita' deve retornar id=9."""
    assert coletor._detectar_instituto_id("Verita pesquisa nacional", "") == 9

def test_detectar_instituto_fallback(coletor):
    """Texto sem instituto reconhecido retorna id=7 (Real Time) e loga warning."""
    assert coletor._detectar_instituto_id("pesquisa genérica sem instituto", "") == 7


def test_parse_release_usa_gemini(coletor):
    """_parse_release deve chamar _parse_com_gemini com o instituto_id correto."""
    with patch.object(coletor, '_parse_com_gemini', return_value=[]) as mock_gemini:
        coletor._parse_release(MOCK_RELEASE_HTML, "https://gazetadopovo.com.br/real-time-presidente/")
        mock_gemini.assert_called_once()
        _, kwargs = mock_gemini.call_args
        assert 'instituto_id' in kwargs
        assert kwargs['instituto_id'] == 7


def test_fetch_com_mock(coletor):
    """fetch() com _get_page mockado deve retornar lista de resultados."""
    mock_dados = [{'candidato': 'Lula', 'percentual': 45.0, 'instituto_id': 7, 'data_divulgacao': '2026-06-12'}]

    with patch.object(coletor, '_get_page', side_effect=[MOCK_LISTING_HTML, MOCK_LISTING_HTML, MOCK_RELEASE_HTML, MOCK_RELEASE_HTML, MOCK_RELEASE_HTML]):
        with patch.object(coletor, '_parse_release', return_value=mock_dados):
            resultado = coletor.fetch()

    assert isinstance(resultado, list)
    assert len(resultado) > 0


def test_fetch_pagina_vazia(coletor):
    """fetch() com listagem vazia retorna lista vazia sem crashar."""
    with patch.object(coletor, '_get_page', return_value=""):
        resultado = coletor.fetch()
    assert resultado == []
