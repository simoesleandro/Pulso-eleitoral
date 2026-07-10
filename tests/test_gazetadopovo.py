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


def test_parse_release_sem_uf_usa_permite_regional_false(coletor):
    """Regressão: release nacional (sem menção de UF) continua com permite_regional=False,
    como no comportamento anterior à correção do fallback."""
    with patch.object(coletor, '_parse_com_gemini', return_value=[]) as mock_gemini:
        coletor._parse_release(MOCK_RELEASE_HTML, "https://gazetadopovo.com.br/real-time-presidente/")
        _, kwargs = mock_gemini.call_args
        assert kwargs['permite_regional'] is False


def test_parse_release_com_uf_usa_permite_regional_true(coletor):
    """Release cujo texto/URL menciona um estado deve setar permite_regional=True,
    roteando para o PROMPT_EXTRACAO_REGIONAL em vez do nacional."""
    with patch.object(coletor, '_parse_com_gemini', return_value=[]) as mock_gemini:
        coletor._parse_release(
            "<html><body><p>Lula tem 41,6% no Rio de Janeiro</p></body></html>",
            "https://exame.com/pesquisa-presidencial-rio-de-janeiro/",
        )
        _, kwargs = mock_gemini.call_args
        assert kwargs['permite_regional'] is True


def test_parse_release_fallback_uf_extrai_candidatos(coletor):
    """Cenário do bug reportado: matéria de fallback (domínio não-Gazeta) mencionando
    resultado presidencial recortado por estado deve retornar candidatos preenchidos,
    não mais {"candidatos": []} por cair no prompt nacional."""
    html_exame = (
        "<html><body><h1>Pesquisa presidencial no Rio de Janeiro</h1>"
        "<p>Lula tem 41,6% no Rio de Janeiro, Flávio Bolsonaro aparece com 38,6%</p>"
        "</body></html>"
    )
    resultado = coletor._parse_release(html_exame, "https://exame.com/pesquisa-presidencial-rio-de-janeiro/")
    # _parse_release salva em pesquisas_regionais e retorna [] quando uf é detectada e há dados
    assert resultado == []


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


def test_filtrar_presidenciais_descarta_governador(coletor):
    """Regressão: _filtrar_presidenciais (BaseCollector, usado por _salvar_regional
    em GazetaDoPovo e CnnBrasil) descarta candidatos não-presidenciais. Foi o bug
    do Daniel Vilela (governador de GO) contaminando a visão presidencial por
    estado. Testa o filtro puro sem tocar em banco (mocka a lista de presidenciais
    e a normalização), pra não vazar estado no pulso_test.db compartilhado."""
    dados = [
        {"candidato": "Lula", "percentual": 40.0},
        {"candidato": "Flávio Bolsonaro", "percentual": 35.0},
        {"candidato": "Daniel Vilela", "percentual": 43.0},   # governador GO — deve sair
    ]
    # get_nomes_presidenciais retorna chaves minúsculas; ambos os imports são
    # tardios dentro do método, então patchamos na origem de cada um.
    with patch('database.get_nomes_presidenciais', return_value={"lula", "flávio bolsonaro"}), \
         patch('collectors.gemini_extractor.normalizar_nome', side_effect=lambda n: n):
        filtrados = coletor._filtrar_presidenciais(dados)

    nomes = {d["candidato"] for d in filtrados}
    assert "Daniel Vilela" not in nomes
    assert nomes == {"Lula", "Flávio Bolsonaro"}


def test_filtrar_presidenciais_fail_open_sem_lista(coletor):
    """Se a lista de presidenciais não carregar (vazia), o filtro é no-op:
    não descarta nada (fail-open seguro, mesma política da normalização)."""
    dados = [{"candidato": "Fulano Qualquer", "percentual": 10.0}]
    with patch('database.get_nomes_presidenciais', return_value=set()):
        assert coletor._filtrar_presidenciais(dados) == dados
