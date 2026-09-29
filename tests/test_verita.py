import os
os.environ['TESTING'] = 'True'

from datetime import date

import pytest

from collectors.verita import VeritaCollector

DB_PATH = "data/pulso_test.db"


@pytest.fixture
def coletor():
    return VeritaCollector(db_path=DB_PATH)


def test_build_items_gov_com_um_candidato(coletor):
    """Com candidato, _build_items_gov monta o item de governador RJ. Antes
    levantava NameError (date usado sem import) em todo PDF do RJ."""
    resultado = {
        "candidatos": [{"nome": "Eduardo Paes", "percentual": 48.6}],
        "tipo": "estimulada",
    }
    itens = coletor._build_items_gov(resultado, "https://exemplo/pesquisa/rj")

    assert len(itens) == 1
    item = itens[0]
    assert item["cargo"] == "governador_rj"
    assert item["candidato"] == "Eduardo Paes"
    assert item["percentual"] == 48.6
    assert item["instituto_id"] == 9
    # Sem data extraída, cai na data de hoje (é aqui que o import faltava).
    assert item["data_pesquisa"] == date.today().isoformat()
    assert item["data_coleta"] == date.today().isoformat()


import logging
import sqlite3

L1 = "https://eleicoes26.institutoverita.com.br/pesquisa/rj-1"
L2 = "https://eleicoes26.institutoverita.com.br/pesquisa/rj-quebrado"
L3 = "https://eleicoes26.institutoverita.com.br/pesquisa/rj-3"


def _item_gov(coletor, url):
    return coletor._build_items_gov(
        {"candidatos": [{"nome": "Eduardo Paes", "percentual": 40.0}], "data": "2026-09-01"},
        url,
    )


@pytest.fixture
def fetch_com_um_pdf_quebrado(monkeypatch):
    """Listagem com 3 PDFs; o do meio levanta exceção no parse. Rede e
    Playwright ficam de fora: _get_page devolve a própria URL como HTML."""
    import collectors.verita as verita_mod
    monkeypatch.setattr(verita_mod, "URLS_CONHECIDAS", [])
    monkeypatch.setattr(verita_mod.time, "sleep", lambda s: None)

    def preparar(coletor):
        monkeypatch.setattr(coletor, "_get_page", lambda url, wait_selector=None: url)
        monkeypatch.setattr(coletor, "_extract_links", lambda html: [L1, L2, L3])

        def parse(html, url):
            if url == L2:
                raise RuntimeError("PDF corrompido")
            return _item_gov(coletor, url)
        monkeypatch.setattr(coletor, "_parse_release", parse)
        return coletor
    return preparar


@pytest.fixture
def log_coletor(caplog):
    """O logger COLLECTOR tem propagate=False — o caplog precisa ser
    pendurado nele diretamente para enxergar os registros."""
    logger = logging.getLogger("COLLECTOR")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.ERROR, logger="COLLECTOR")
    yield caplog
    logger.removeHandler(caplog.handler)


def test_fetch_isola_falha_de_um_pdf(coletor, fetch_com_um_pdf_quebrado, log_coletor):
    """Uma exceção num PDF não aborta o fetch: os outros PDFs seguem, e a
    falha fica registrada (lista + log.error com instituto, URL e exceção)."""
    fetch_com_um_pdf_quebrado(coletor)

    dados = coletor.fetch()

    assert [d["fonte_url"] for d in dados] == [L1, L3]
    assert coletor.falhas_coleta == [(L2, "RuntimeError: PDF corrompido")]
    erros = [r.getMessage() for r in log_coletor.records if r.levelno == logging.ERROR]
    assert any("Verita" in m and L2 in m and "PDF corrompido" in m for m in erros), erros


def test_run_grava_demais_pdfs_e_reporta_falha_no_resumo(tmp_path, fetch_com_um_pdf_quebrado):
    """Ponta a ponta: com um PDF quebrado, os outros dois são gravados e o
    resumo do run() sai "parcial" com a falha contada."""
    import database
    db_file = str(tmp_path / "verita_falha_isolada.db")
    original = database.DB_PATH
    try:
        database.DB_PATH = db_file
        database.init_db(force_seed=False)
    finally:
        database.DB_PATH = original
    conn = sqlite3.connect(db_file)
    conn.execute("DELETE FROM intencoes")
    conn.execute("DELETE FROM pesquisas")
    conn.commit()
    conn.close()

    coletor = fetch_com_um_pdf_quebrado(VeritaCollector(db_path=db_file))
    resumo = coletor.run()

    assert resumo["status"] == "parcial"
    assert resumo["salvas"] == 2
    assert [url for url, _ in resumo["falhas"]] == [L2]

    conn = sqlite3.connect(db_file)
    urls = {r[0] for r in conn.execute(
        "SELECT fonte_url FROM pesquisas WHERE cargo = 'governador_rj'")}
    conn.close()
    assert urls == {L1, L3}
