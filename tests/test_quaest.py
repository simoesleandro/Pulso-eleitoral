import os
os.environ['TESTING'] = 'True'

import pytest
import sqlite3
from unittest.mock import patch, MagicMock
from collectors.quaest import QuaestCollector
from collectors.utils import fetch_with_retry

def test_extract_links():
    """Testa que _extract_links extrai links corretos relevantes e ignora irrelevantes."""
    collector = QuaestCollector("dummy_path")
    
    mock_html = """
    <html>
      <body>
        <a href="https://quaest.com.br/pesquisa-presidente-2026">Relevante 1</a>
        <a href="/eleicao-rio-governador">Relevante 2</a>
        <a href="https://quaest.com.br/contato">Irrelevante</a>
        <a href="https://quaest.com.br/category/politica/pesquisa-nacional-junho">Relevante 3</a>
      </body>
    </html>
    """
    
    links = collector._extract_links(mock_html)
    assert len(links) == 3
    assert "https://quaest.com.br/pesquisa-presidente-2026" in links
    assert "https://quaest.com.br/eleicao-rio-governador" in links
    assert "https://quaest.com.br/category/politica/pesquisa-nacional-junho" in links
    assert "https://quaest.com.br/contato" not in links

def test_parse_release():
    """Testa que _parse_release analisa corretamente um release individual."""
    collector = QuaestCollector("dummy_path")
    
    mock_html = """
    <html>
      <body>
        <h1>Pesquisa Quaest de Opinião</h1>
        <p>Lula: 38% | Bolsonaro: 32% | Outros: 30%</p>
        <p>A pesquisa foi divulgada em 15 de junho de 2026.</p>
        <p>A margem de erro de 2 pontos percentuais.</p>
        <p>Foram 2.000 entrevistados.</p>
      </body>
    </html>
    """
    
    results = collector._parse_release(mock_html, "https://quaest.com.br/release-1")
    assert len(results) == 3
    
    # Verifica dados comuns
    for r in results:
        assert r['instituto_id'] == 3
        assert r['cargo'] == 'presidente'
        assert r['data_divulgacao'] == '2026-06-15'
        assert r['tamanho_amostra'] == 2000
        assert r['margem_erro'] == 2.0
        assert r['fonte_url'] == "https://quaest.com.br/release-1"
        assert r['metodologia'] == "Espontânea"
        
    candidatos = {r['candidato']: r['percentual'] for r in results}
    assert candidatos['Lula'] == 38.0
    assert candidatos['Bolsonaro'] == 32.0
    assert candidatos['Outros'] == 30.0

def test_inferir_cargo():
    """Testa a inferência do cargo com base na URL ou no texto do release."""
    collector = QuaestCollector("dummy_path")
    
    # Governador por URL
    assert collector._inferir_cargo("https://quaest.com.br/eleicao-governador-rj", "Texto geral") == 'governador_rj'
    # Governador por texto
    assert collector._inferir_cargo("https://quaest.com.br/release-x", "Corrida para o governo do estado mostra novos dados...") == 'governador_rj'
    # Presidente padrão
    assert collector._inferir_cargo("https://quaest.com.br/release-y", "Texto sobre presidenciáveis") == 'presidente'

@patch('collectors.quaest.QuaestCollector._get_page')
def test_fetch_with_mock_requests(mock_get_page):
    """Testa que fetch() integra o fluxo de listagem e parsing de releases."""
    collector = QuaestCollector("dummy_path")
    
    # Primeira chamada do fetch: obtém listagem
    # Segunda chamada do fetch: obtém o release 1
    mock_get_page.side_effect = [
        # Listagem página 1
        """
        <html>
          <body>
            <a href="https://quaest.com.br/pesquisa-presidente-2026">Link</a>
          </body>
        </html>
        """,
        # Listagem página 2 (vazia)
        """<html><body></body></html>""",
        # Release 1
        """
        <html>
          <body>
            <p>Lula: 38% | Bolsonaro: 32%</p>
            <p>15 de junho de 2026</p>
            <p>2.000 entrevistados</p>
            <p>margem de erro de 2%</p>
          </body>
        </html>
        """
    ]
    
    data = collector.fetch()
    assert len(data) == 2
    candidatos = {r['candidato']: r['percentual'] for r in data}
    assert candidatos['Lula'] == 38.0
    assert candidatos['Bolsonaro'] == 32.0

@patch('requests.get')
def test_fetch_with_retry(mock_get):
    """Testa fetch_with_retry com falhas e sucesso subsequente."""
    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 500
    
    mock_resp_success = MagicMock()
    mock_resp_success.status_code = 200
    mock_resp_success.text = "Sucesso!"
    
    mock_get.side_effect = [mock_resp_fail, mock_resp_fail, mock_resp_success]
    
    res = fetch_with_retry("http://teste.com", headers={}, max_retries=3, delay=0.1)
    assert res == "Sucesso!"
    assert mock_get.call_count == 3
