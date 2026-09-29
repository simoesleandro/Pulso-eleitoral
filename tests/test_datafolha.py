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


# --- Governador do RJ: roteamento e texto enviado ao extrator (bug #4) ---

from collectors.datafolha import _e_governador_rj

_DF = "https://datafolha.folha.uol.com.br/eleicoes/2026/"


@pytest.mark.parametrize("url", [
    # Real (listagem de 2026-09-29): "rio" de "cenarios" + "governador" de SP.
    _DF + "03/tarcisio-de-freitas-republicanos-lidera-todos-os-cenarios-de-intencao-de-voto-para-governador-de-sp.shtml",
    # Exemplo da auditoria: "cenarios" + "governo".
    _DF + "09/lula-lidera-em-todos-os-cenarios-e-governo-tem-aprovacao-estavel.shtml",
    # Reais: governo de outro estado, avaliação de governo.
    "https://www1.folha.uol.com.br/poder/2025/04/datafolha-alckmin-e-marcal-lideram-cenarios-em-eventual-disputa-ao-governo-de-sp-sem-tarcisio.shtml",
    _DF + "08/celina-leao-30-e-arruda-28-empatam-na-disputa-pelo-governo-do-df.shtml",
    _DF + "09/lula-pt-lidera-no-estado-do-rio-grande-do-sul-e-governador-eduardo-leite.shtml",
    "https://datafolha.folha.uol.com.br/rj",
])
def test_nao_roteia_para_governador_rj(url):
    assert _e_governador_rj(url) is False


@pytest.mark.parametrize("url", [
    # Formato dos slugs de governador do Datafolha, com o RJ no lugar de SP/DF.
    _DF + "09/eduardo-paes-psd-lidera-com-45-das-intencoes-de-voto-para-governador-do-rio-de-janeiro.shtml",
    _DF + "09/paes-e-ruas-disputam-o-governo-do-rio.shtml",
    _DF + "09/paes-lidera-disputa-para-governador-do-rj.shtml",
])
def test_roteia_release_do_rj_para_governador(url):
    assert _e_governador_rj(url) is True


def test_extract_links_listagem_real_nao_marca_sp_como_rj():
    """Listagem real: o release de governador de SP com "cenarios" no slug
    não pode escapar do filtro estadual como se fosse do RJ."""
    caminho = os.path.join(os.path.dirname(__file__), "fixtures", "datafolha", "listagem_amostra.html")
    with open(caminho, encoding="utf-8") as f:
        links = DatafolhaCollector("dummy_path")._extract_links(f.read())

    assert links, "a amostra real tem releases nacionais"
    assert not any("governador-de-sp" in l for l in links)


RELEASE_RJ_HTML = """<!DOCTYPE html>
<html><head>
  <meta charset="utf-8"><title>Paes lidera para governador do RJ</title>
  <script>window.dataLayer = [{"page": "governador"}];</script>
  <style>.x { color: red }</style>
</head><body>
  <header>Menu Folha</header><nav>Eleições | Avaliação de governo</nav>
  <article><h1>Paes lidera para governador do RJ</h1>
  <p>Eduardo Paes (PSD) tem 45% das intenções de voto, e Douglas Ruas (PL), 20%.</p></article>
  <footer>Copyright Folha</footer>
</body></html>"""


def test_texto_enviado_ao_extrator_de_governador_e_limpo():
    collector = DatafolhaCollector("dummy_path")
    url = _DF + "09/paes-lidera-disputa-para-governador-do-rj.shtml"
    fake = {"tipo": "estimulada", "data": "2026-09-20",
            "candidatos": [{"nome": "Eduardo Paes", "percentual": 45.0}]}

    with patch("collectors.gemini_extractor.extrair_governador_rj", return_value=fake) as mock_gov:
        itens = collector._parse_release(RELEASE_RJ_HTML, url)

    texto = mock_gov.call_args.args[0]
    assert "<head" not in texto.lower()
    assert "<" not in texto and ">" not in texto
    assert "dataLayer" not in texto and "color: red" not in texto
    assert "Eduardo Paes (PSD) tem 45%" in texto
    assert itens and all(i["cargo"] == "governador_rj" for i in itens)


def test_release_nacional_com_cenarios_nao_chama_extrator_de_governador():
    collector = DatafolhaCollector("dummy_path")
    url = _DF + "09/lula-lidera-em-todos-os-cenarios-e-governo-tem-aprovacao-estavel.shtml"

    with patch("collectors.gemini_extractor.extrair_governador_rj") as mock_gov, \
         patch.object(collector, "_parse_com_gemini", return_value=[]) as mock_nac:
        collector._parse_release("<html><body>texto nacional</body></html>", url)

    mock_gov.assert_not_called()
    mock_nac.assert_called_once()
