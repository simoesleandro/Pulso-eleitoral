import os
os.environ['TESTING'] = 'True'

import pytest
import sqlite3
from unittest.mock import patch, MagicMock
from collectors.poder360 import Poder360Collector

MOCK_LISTING_HTML = """
<html>
  <body>
    <div>
      <a href="https://poder360.com.br/pesquisas-de-opiniao/pesquisa-presidente-2026">Presidente 2026</a>
      <a href="/pesquisas-de-opiniao/eleicao-governador">Governador</a>
      <a href="https://poder360.com.br/category/politica">Categoria Politica</a>
      <a href="/tag/lula">Tag Lula</a>
      <a href="/page/2">Pagina 2</a>
    </div>
  </body>
</html>
"""

MOCK_RELEASE_HTML = """
<html>
  <body>
    <h1>Pesquisa de Opinião</h1>
    <p>Pesquisa Quaest divulgada em 10 de junho de 2026.</p>
    <p>Lula: 41% | Bolsonaro: 35% | Ciro: 8% | Outros: 16%</p>
    <p>Margem de erro de 2 pontos.</p>
    <p>Foram 2.000 entrevistados.</p>
  </body>
</html>
"""

def test_extract_links():
    """Testa que _extract_links extrai links relevantes e filtra fora categorias, tags, etc."""
    collector = Poder360Collector("dummy_path")
    links = collector._extract_links(MOCK_LISTING_HTML)
    
    assert len(links) == 2
    assert "https://poder360.com.br/pesquisas-de-opiniao/pesquisa-presidente-2026" in links
    assert "https://poder360.com.br/pesquisas-de-opiniao/eleicao-governador" in links
    assert "https://poder360.com.br/category/politica" not in links

def test_detectar_instituto():
    """Testa a detecção do instituto correto a partir do texto do release."""
    collector = Poder360Collector("dummy_path")
    
    assert collector._detectar_instituto("Resultado da pesquisa Quaest mostra...") == 3
    assert collector._detectar_instituto("Nova pesquisa Datafolha indica...") == 1
    assert collector._detectar_instituto("Pesquisa realizada pelo instituto xpto...") == 1  # Fallback

def test_parse_release():
    """Testa que _parse_release extrai os candidatos, margem de erro, tamanho amostral do HTML do release."""
    collector = Poder360Collector("dummy_path")
    results = collector._parse_release(MOCK_RELEASE_HTML, "https://poder360.com.br/release-1")
    
    assert len(results) == 4
    candidatos = {r['candidato']: r['percentual'] for r in results}
    assert candidatos['Lula'] == 41.0
    assert candidatos['Bolsonaro'] == 35.0
    assert candidatos['Ciro'] == 8.0
    assert candidatos['Outros'] == 16.0
    
    for r in results:
        assert r['tamanho_amostra'] == 2000
        assert r['margem_erro'] == 2.0
        assert r['data_divulgacao'] == '2026-06-10'
        assert r['metodologia'] == 'Espontânea'

def test_parse_instituto_correto():
    """Testa que o ID do instituto é detectado e atribuído corretamente aos resultados (Quaest = 3)."""
    collector = Poder360Collector("dummy_path")
    results = collector._parse_release(MOCK_RELEASE_HTML, "https://poder360.com.br/release-1")
    
    assert len(results) > 0
    for r in results:
        assert r['instituto_id'] == 3

def test_fetch_desabilitado_retorna_vazio():
    """Poder360 está desabilitado (agregador migrou para produto pago — Poder Drive).
    fetch() deve retornar [] sem crashar enquanto o coletor estiver desligado."""
    collector = Poder360Collector("dummy_path")
    assert collector.fetch() == []

def test_fetch_vazio_nao_crasha():
    """Testa que fetch() com html vazio retorna [] e não crasha."""
    collector = Poder360Collector("dummy_path")
    with patch.object(collector, '_get_page', return_value=""):
        data = collector.fetch()
        assert data == []
