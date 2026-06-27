import os
os.environ['TESTING'] = 'True'

import pytest
import sqlite3
from unittest.mock import patch, MagicMock
from collectors.atlas import AtlasCollector
from collectors.utils import fetch_with_retry

def test_extract_links():
    """Testa que _extract_links extrai links corretos relevantes e ignora irrelevantes."""
    collector = AtlasCollector("dummy_path")
    
    mock_html = """
    <html>
      <body>
        <a href="https://atlaspolitico.com.br/pesquisa-presidente-2026">Relevante 1</a>
        <a href="/eleicao-rio-governador">Relevante 2</a>
        <a href="https://atlaspolitico.com.br/contato">Irrelevante</a>
        <a href="https://atlaspolitico.com.br/pesquisas/pesquisa-nacional-junho">Relevante 3</a>
      </body>
    </html>
    """
    
    links = collector._extract_links(mock_html)
    assert len(links) == 3
    assert "https://atlaspolitico.com.br/pesquisa-presidente-2026" in links
    assert "https://atlaspolitico.com.br/eleicao-rio-governador" in links
    assert "https://atlaspolitico.com.br/pesquisas/pesquisa-nacional-junho" in links
    assert "https://atlaspolitico.com.br/contato" not in links

def test_parse_release():
    """Testa que _parse_release analisa corretamente um release individual."""
    collector = AtlasCollector("dummy_path")
    
    mock_html = """
    <html>
      <body>
        <h1>Pesquisa Atlas de Opinião</h1>
        <p>Lula: 38% | Bolsonaro: 32% | Outros: 30%</p>
        <p>A pesquisa foi divulgada em 15 de junho de 2026.</p>
        <p>A margem de erro de 2 pontos percentuais.</p>
        <p>Foram 2.000 entrevistados.</p>
      </body>
    </html>
    """
    
    results = collector._parse_release(mock_html, "https://atlaspolitico.com.br/release-1")
    assert len(results) == 3
    
    # Verifica dados comuns
    for r in results:
        assert r['instituto_id'] == 5
        assert r['cargo'] == 'presidente'
        assert r['data_divulgacao'] == '2026-06-15'
        assert r['tamanho_amostra'] == 2000
        assert r['margem_erro'] == 2.0
        assert r['fonte_url'] == "https://atlaspolitico.com.br/release-1"
        assert r['metodologia'] == "Espontânea"
        
    candidatos = {r['candidato']: r['percentual'] for r in results}
    assert candidatos['Lula'] == 38.0
    assert candidatos['Bolsonaro'] == 32.0
    assert candidatos['Outros'] == 30.0

def test_inferir_cargo():
    """Testa a inferência do cargo com base na URL ou no texto do release."""
    collector = AtlasCollector("dummy_path")
    
    # Governador por URL
    assert collector._inferir_cargo("https://atlaspolitico.com.br/eleicao-governador-rj", "Texto geral") == 'governador_rj'
    # Governador por texto
    assert collector._inferir_cargo("https://atlaspolitico.com.br/release-x", "Corrida para o governo do estado mostra novos dados...") == 'governador_rj'
    # Presidente padrão
    assert collector._inferir_cargo("https://atlaspolitico.com.br/release-y", "Texto sobre presidenciáveis") == 'presidente'

def test_fetch_desabilitado_retorna_vazio():
    """Atlas está desabilitado (domínio atlaspolitico.com.br fora do ar/DNS).
    fetch() deve retornar [] sem crashar enquanto o coletor estiver desligado."""
    collector = AtlasCollector("dummy_path")
    assert collector.fetch() == []
