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


# --- FIX 0: governador RJ recebe a tabela de intenção (PDFs reais) ---

from unittest.mock import MagicMock, patch

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "verita")
PDF_GOV_ABR = "verita_rj_governador_abr2026.pdf"      # RJ-03394, págs. 1–14 do relatório
PDF_PRES_SET = "verita_rj_presidente_set2026.pdf"     # BR-02698: presidente no RJ, sem governador
PDF_BASE = "https://xyz.supabase.co/storage/v1/object/public/pesquisas/pdfs/"


def _html_com_pdf(nome_pdf_publicado):
    return f'<main><a href="{PDF_BASE}{nome_pdf_publicado}">Baixar pesquisa em PDF</a></main>'


def _resposta_pdf(fixture):
    with open(os.path.join(FIXTURES, fixture), "rb") as f:
        conteudo = f.read()
    resp = MagicMock()
    resp.content = conteudo
    resp.raise_for_status = lambda: None
    return resp


def test_listagem_real_so_abre_nacional_e_governador_rj(coletor):
    """Dos 95 links reais, só abre os que podem ter PDF nacional ou de
    governador do RJ; os de presidente no RJ e dos outros estados ficam."""
    with open(os.path.join(FIXTURES, "listagem_amostra.html"), encoding="utf-8") as f:
        links = coletor._extract_links(f.read())

    ids = sorted(l.split("/pesquisa/")[1][:8] for l in links)
    assert ids == sorted([
        "260793c5", "2a8b919a", "8e9d5a6b", "e13762d1",   # "Pesquisa para Presidente no Brasil"
        "0e86847d",                                       # Governador, Presidente e Senador no RJ
    ])


def test_pdf_governador_rj_envia_so_a_tabela_estimulada_sobre_o_total(coletor):
    fake = {"tipo": "estimulada", "data": "2026-04-04",
            "candidatos": [{"nome": "Eduardo Paes", "percentual": 34.0}]}
    with patch("collectors.verita.requests.get",
               return_value=_resposta_pdf(PDF_GOV_ABR)), \
         patch("collectors.gemini_extractor.extrair_governador_rj",
               return_value=fake) as mock_gov, \
         patch.object(coletor, "_parse_com_gemini") as mock_nac:
        itens = coletor._parse_release(
            _html_com_pdf("1777395266072_Relatorio_Rio_de_Janeiro_2026.pdf"),
            "https://eleicoes26.institutoverita.com.br/pesquisa/0e86847d")

    mock_nac.assert_not_called()
    texto = mock_gov.call_args.args[0]
    # Cabeçalho: data de campo, amostra e margem.
    assert "29/03 a 04/04/2026" in texto
    assert "2030 eleitores" in texto
    assert "2,5 pontos percentuais" in texto
    # Tabela estimulada (P03): número de pessoas + percentual sobre o total.
    for linha in ["Eduardo Paes (PSD) 691 34,0", "Douglas Ruas (PL) 454 22,4",
                  "William Siri (PSOL) 114 5,6", "Wilson Witzel (Democrata) 56 2,7",
                  "Cyro Garcia (PSTU) 38 1,9", "Rafael Luz (Missão) 38 1,9"]:
        assert linha in texto
    # Nada de porcentagem válida/acumulada, gráfico, espontânea, 2ª opção ou senador.
    for proibido in ["49,7", "32,7", "94,5", "Fale o nome", "segunda inten",
                     "Senador", "PERGUNTA 04", "Glauber Braga"]:
        assert proibido.lower() not in texto.lower(), proibido
    assert itens and all(i["cargo"] == "governador_rj" for i in itens)


def test_pdf_do_rj_so_de_presidente_e_pulado_sem_chamar_o_gemini(coletor, caplog):
    """BR-02698: pesquisa de presidente feita no RJ. Não tem governador e
    não é nacional — não vai para nenhum extrator."""
    with patch("collectors.verita.requests.get",
               return_value=_resposta_pdf(PDF_PRES_SET)), \
         patch("collectors.gemini_extractor.extrair_governador_rj") as mock_gov, \
         patch.object(coletor, "_parse_com_gemini") as mock_nac:
        itens = coletor._parse_release(
            _html_com_pdf("1790258572255_Relatorio_Rio_de_Janeiro_09.2026.pdf"),
            "https://eleicoes26.institutoverita.com.br/pesquisa/34041b58")

    assert itens == []
    mock_gov.assert_not_called()
    mock_nac.assert_not_called()


_CABECALHO = ("DADOS DA PESQUISA\nRegistro: TRE: RJ-00001/2026\n"
              "Período: 01/09 a 05/09/2026 Amostra: 1000 eleitores\n"
              "Margem de erro: 3,0 pontos percentuais\n")
_ENUNCIADO = ("PERGUNTA 03\nSe a eleição fosse hoje e estes fossem os candidatos em quem "
              "o(a) sr(a) votaria para Governador do Rio de Janeiro?\n")
_TABELA_OK = ("Porcentagem\nFrequência Porcentual Porcentagem válida\nacumulativa\n"
              "Eduardo Paes (PSD) 600 60,0 66,7 66,7\n"
              "Válido Douglas Ruas (PL) 300 30,0 33,3 100,0\n"
              "Total 900 90,0 100,0\nAusente NS/NR 100 10,0\nTotal 1000 100,0\n")


@pytest.mark.parametrize("tabela", [
    # Soma das linhas (600+300) não bate com o Total (950).
    _TABELA_OK.replace("Total 900 90,0 100,0", "Total 950 95,0 100,0"),
    # Sem a linha de Total.
    _TABELA_OK.replace("Total 900 90,0 100,0\n", ""),
    # Linha de candidato sem o número de pessoas.
    _TABELA_OK.replace("Eduardo Paes (PSD) 600 60,0 66,7 66,7", "Eduardo Paes (PSD) 60,0 66,7"),
    # Sem o cabeçalho de colunas (Frequência / Porcentual).
    _TABELA_OK.replace("Frequência Porcentual Porcentagem válida\n", ""),
    # Só o gráfico, com a porcentagem válida — nunca pode ir ao extrator.
    "0 20 40 60 80 100\nEduardo Paes (PSD) 66,7\nDouglas Ruas (PL) 33,3\n",
])
def test_tabela_nao_reconhecida_pula_o_pdf_com_warning(coletor, caplog, tabela):
    """Sem reconhecer cabeçalho + linhas com pessoas e % sobre o total, o PDF
    é pulado. Nunca cai no texto bruto (que traria a porcentagem válida)."""
    log = logging.getLogger("COLLECTOR")
    log.addHandler(caplog.handler)
    try:
        caplog.set_level(logging.WARNING, logger="COLLECTOR")
        with patch.object(coletor, "_download_pdf_text",
                          return_value=_CABECALHO + _ENUNCIADO + tabela), \
             patch("collectors.gemini_extractor.extrair_governador_rj") as mock_gov, \
             patch.object(coletor, "_parse_com_gemini") as mock_nac:
            itens = coletor._parse_release(
                _html_com_pdf("123_Relatorio_Rio_de_Janeiro_09.2026.pdf"), "https://x/pesquisa/1")
    finally:
        log.removeHandler(caplog.handler)

    assert itens == []
    mock_gov.assert_not_called()
    mock_nac.assert_not_called()
    avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Verita" in r.getMessage() and "tabela" in r.getMessage().lower() for r in avisos)


def test_tabela_reconhecida_em_caixa_alta_e_nome_quebrado(coletor):
    """Busca sem diferenciar maiúsculas; nome de candidato quebrado em duas
    linhas em volta dos números (formato dos PDFs de setembro)."""
    texto = (_CABECALHO.upper() +
             "PERGUNTA 01\nSE A ELEIÇÃO FOSSE HOJE E ESSES FOSSEM OS CANDIDATOS, EM QUEM VOCÊ "
             "VOTARIA PARA GOVERNADOR DO RIO DE JANEIRO? (ESTIMULADA)\n"
             "Porcentagem Porcentagem\nFrequência Porcentual\nválida acumulativa\n"
             "EDUARDO PAES - PSD 600 60,0 66,7 66,7\n"
             "CORONEL FULANO DE TAL -\n300 30,0 33,3 100,0\nDEMOCRATA\n"
             "Total 900 90,0 100,0\n")
    with patch.object(coletor, "_download_pdf_text", return_value=texto), \
         patch("collectors.gemini_extractor.extrair_governador_rj",
               return_value={"candidatos": []}) as mock_gov:
        coletor._parse_release(_html_com_pdf("9_Relatorio_RJ_Setembro_2026.pdf"), "https://x/pesquisa/2")

    enviado = mock_gov.call_args.args[0]
    assert "EDUARDO PAES - PSD 600 60,0" in enviado
    assert "CORONEL FULANO DE TAL - DEMOCRATA 300 30,0" in enviado
    assert "66,7" not in enviado and "33,3" not in enviado
