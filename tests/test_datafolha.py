import os
os.environ['TESTING'] = 'True'

import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from collectors.datafolha import DatafolhaCollector


MOCK_HTML_LINKS = """
<html><body>
  <a href="https://datafolha.folha.uol.com.br/eleicoes/2026/01/lula-lidera.shtml">
    Lula lidera intenção de voto para presidente
  </a>
  <a href="https://datafolha.folha.uol.com.br/eleicoes/2026/01/pernambuco-lula.shtml">
    Em Pernambuco, Lula lidera
  </a>
  <a href="https://datafolha.folha.uol.com.br/eleicoes/2026/01/bolsonaro-2t.shtml">
    Pesquisa nacional aponta Bolsonaro em 2º
  </a>
</body></html>
"""


def test_extract_links_filtra_estadual():
    collector = DatafolhaCollector("dummy_path")
    links = collector._extract_links(MOCK_HTML_LINKS)
    assert len(links) == 2
    assert all('pernambuco' not in l for l in links)


def test_extract_links_vazio():
    collector = DatafolhaCollector("dummy_path")
    assert collector._extract_links("") == []
    assert collector._extract_links(None) == []


def test_parse_release_usa_gemini():
    collector = DatafolhaCollector("dummy_path")
    with patch.object(collector, '_parse_com_gemini', return_value=[]) as mock:
        collector._parse_release("<html>texto</html>", "https://datafolha.folha.uol.com.br/test")
        mock.assert_called_once_with(
            "<html>texto</html>",
            "https://datafolha.folha.uol.com.br/test",
            instituto_id=1
        )


def test_save_empty_fetch_does_not_error(tmp_path):
    db_file = tmp_path / "test_datafolha.db"
    conn = sqlite3.connect(db_file)
    schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.close()

    collector = DatafolhaCollector(str(db_file))
    collector.save([])  # não deve lançar exceção
