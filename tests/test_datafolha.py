import os
os.environ['TESTING'] = 'True'

import pytest
import sqlite3
from unittest.mock import patch, MagicMock
from collectors.datafolha import DatafolhaCollector

def test_extract_data_from_title():
    """Testa que _extract_data_from_title extrai dados e percentuais corretos via regex."""
    collector = DatafolhaCollector("dummy_path")
    
    # Caso padrão
    res1 = collector._extract_data_from_title("Lula 38%, Bolsonaro 32%")
    assert res1 == {'Lula': 38.0, 'Bolsonaro': 32.0}
    
    # Caso com múltiplos candidatos e acentos
    res2 = collector._extract_data_from_title("Tarcísio 22% e Ciro 8%, outros candidatos")
    assert res2 == {'Tarcísio': 22.0, 'Ciro': 8.0}
    
    # Caso em branco ou sem correspondência
    res3 = collector._extract_data_from_title("Pesquisa eleitoral sem dados de intenção")
    assert res3 == {}

def test_parse_with_mock_html():
    """Testa que _parse extrai links eleitorais válidos do HTML sem fazer requisições externas."""
    collector = DatafolhaCollector("dummy_path")
    
    mock_html = """
    <html>
      <body>
        <div>
          <a href="/eleicoes/2026/06/15/lula-lidera.shtml">Lula 38%, Bolsonaro 32% no Datafolha</a>
          <a href="/outros-assuntos/noticia.shtml">Notícia aleatória</a>
          <a href="https://datafolha.folha.uol.com.br/eleicoes/presidente/2026/05/12/tarcisio-sobe.shtml">Tarcísio 22%</a>
        </div>
      </body>
    </html>
    """
    
    results = collector._parse(mock_html)
    assert len(results) == 2
    
    assert results[0]['titulo'] == "Lula 38%, Bolsonaro 32% no Datafolha"
    assert results[0]['url'] == "https://datafolha.folha.uol.com.br/eleicoes/2026/06/15/lula-lidera.shtml"
    assert results[0]['data_texto'] == "2026-06-15"
    
    assert results[1]['titulo'] == "Tarcísio 22%"
    assert results[1]['url'] == "https://datafolha.folha.uol.com.br/eleicoes/presidente/2026/05/12/tarcisio-sobe.shtml"
    assert results[1]['data_texto'] == "2026-05-12"

@patch('requests.get')
def test_fetch_with_mock_requests(mock_get):
    """Testa que fetch() funciona corretamente integrando get_listing, parse e extract_data sem crashar."""
    # Configura a resposta mockada do requests.get
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = """
    <html>
      <body>
        <a href="/eleicoes/2026/06/15/lula-lidera.shtml">Lula 38%, Bolsonaro 32% no Datafolha</a>
      </body>
    </html>
    """
    mock_get.return_value = mock_response
    
    collector = DatafolhaCollector("dummy_path")
    data = collector.fetch()
    
    assert len(data) == 2
    assert data[0]['candidato'] == 'Lula'
    assert data[0]['percentual'] == 38.0
    assert data[1]['candidato'] == 'Bolsonaro'
    assert data[1]['percentual'] == 32.0

def test_save_empty_fetch_does_not_error(tmp_path):
    """Testa que se fetch() retornar [], save() funciona sem erros de inserção."""
    db_file = tmp_path / "test_datafolha.db"
    
    # Cria o banco de testes
    conn = sqlite3.connect(db_file)
    schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    conn.close()
    
    collector = DatafolhaCollector(str(db_file))
    collector.save([]) # Não deve dar erro
