import os
os.environ['TESTING'] = 'True'

from pathlib import Path

from tse.dataset import parsear_csv, detectar_abrangencia

FIXTURE = Path(__file__).parent / "fixtures" / "tse_amostra.csv"


def _conteudo():
    return FIXTURE.read_bytes()


def test_parseia_presidente_e_ignora_outros_cargos():
    regs = parsear_csv(_conteudo(), cargo="presidente")

    assert regs, "fixture deve conter pesquisas de presidente"
    for r in regs:
        assert r["cargo"] == "presidente"
        assert r["protocolo"].startswith("BR")
        assert r["qt_entrevistado"] > 0


def test_datas_sao_normalizadas_para_iso_curto():
    """O CSV traz '2026-03-31 00:00:00'; queremos '2026-03-31'."""
    regs = parsear_csv(_conteudo(), cargo="presidente")

    for r in regs:
        assert len(r["data_inicio"]) == 10
        assert len(r["data_fim"]) == 10
        assert r["data_inicio"][4] == "-"


def test_sentinela_nulo_vira_none():
    """NM_EMPRESA_FANTASIA == '#NULO#' não pode virar a string literal."""
    regs = parsear_csv(_conteudo(), cargo="governador_rj")

    for r in regs:
        assert r["nome_empresa"] != "#NULO#"
        assert r["nome_empresa"], "nome_empresa nunca pode ser vazio"


def test_governador_rj_filtra_por_cargo():
    regs = parsear_csv(_conteudo(), cargo="governador_rj")

    assert regs
    for r in regs:
        assert r["cargo"] == "governador_rj"
        assert r["protocolo"].startswith("RJ")


def test_governador_de_outro_estado_nao_entra_como_rj():
    """A fixture tem uma pesquisa de Governador do PI. Mesmo que o arquivo
    errado seja passado, ela não pode virar governador_rj."""
    regs = parsear_csv(_conteudo(), cargo="governador_rj")

    assert all(not r["protocolo"].startswith("PI") for r in regs)


def test_detectar_abrangencia_municipal():
    metodologia = "Pesquisa realizada no município de Angra dos Reis, Estado do Rio de Janeiro."
    assert detectar_abrangencia(metodologia, "") == "municipal"


def test_detectar_abrangencia_estadual_nao_confunde_capital():
    """'município do Rio de Janeiro' é a capital, mas 'Estado do Rio' é estadual."""
    metodologia = "Amostra representativa do eleitorado do Estado do Rio de Janeiro."
    assert detectar_abrangencia(metodologia, "") == "estadual"
