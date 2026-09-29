import os
os.environ['TESTING'] = 'True'

import json
import logging
import sqlite3

import pytest

import database
from database import DB_PATH, get_conn, init_db, _popular_candidatos
from db.candidatos import _CANDIDATOS_SEED
from scripts.migrate_candidatos_status import aplicar_migracao as _migrar_status

_SEED = {nome: (apelidos, esp, cor, pres, ativo)
         for nome, apelidos, esp, cor, pres, ativo in _CANDIDATOS_SEED}


def _remover_banco():
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass


@pytest.fixture(autouse=True)
def banco_limpo():
    _remover_banco()
    yield
    database._cache_candidatos = None
    _remover_banco()


def _banco_antigo(linhas):
    """Banco "existente": schema + colunas de status + só as linhas dadas.

    Reproduz o estado de produção, onde o roster foi gravado quando o seed
    tinha menos candidatos e nunca mais foi completado.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open(os.path.join(database.BASE_DIR, 'schema.sql'), encoding='utf-8') as f:
        conn.executescript(f.read())
    _migrar_status(conn)
    for nome, apelidos, espectro, cor, pres, ativo, status in linhas:
        conn.execute(
            "INSERT INTO candidatos (nome_canonico, apelidos, espectro, cor_hex, "
            "is_presidencial, ativo, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nome, json.dumps(apelidos, ensure_ascii=False), espectro, cor, pres, ativo, status))
    conn.commit()
    return conn


def _estado(conn):
    return [tuple(r) for r in conn.execute(
        "SELECT nome_canonico, apelidos, espectro, cor_hex, is_presidencial, ativo, "
        "status, data_status FROM candidatos ORDER BY nome_canonico")]


def _linha(conn, nome):
    return conn.execute("SELECT * FROM candidatos WHERE nome_canonico = ?", (nome,)).fetchone()


_ROSTER_ANTIGO = [
    ("Eduardo Paes", ["eduardo paes"], "centro", "#0A2240", 0, 1, "ativo"),
    ("Marcelo Freixo", ["marcelo freixo"], "esquerda", "#1D9E75", 0, 1, "ativo"),
]


def test_candidato_novo_do_seed_entra_em_banco_existente_com_a_cor_do_seed():
    conn = _banco_antigo(_ROSTER_ANTIGO)

    _popular_candidatos(conn)

    garotinho = _linha(conn, "Anthony Garotinho")
    ruas = _linha(conn, "Douglas Ruas")
    assert garotinho is not None and ruas is not None
    assert garotinho["cor_hex"] == _SEED["Anthony Garotinho"][2] == "#BA7517"
    assert ruas["cor_hex"] == _SEED["Douglas Ruas"][2]
    assert json.loads(garotinho["apelidos"]) == ["anthony garotinho", "garotinho"]
    assert garotinho["is_presidencial"] == 0 and garotinho["ativo"] == 1
    total = conn.execute("SELECT COUNT(*) FROM candidatos").fetchone()[0]
    assert total == len(_CANDIDATOS_SEED)


def test_migracao_do_roster_e_idempotente():
    conn = _banco_antigo(_ROSTER_ANTIGO)

    _popular_candidatos(conn)
    depois_da_primeira = _estado(conn)
    resumo = _popular_candidatos(conn)

    assert _estado(conn) == depois_da_primeira
    assert resumo == {"inseridos": [], "apelidos_adicionados": {}}


def test_candidato_existente_editado_a_mao_nao_e_alterado():
    """status, ativo, cor, espectro e is_presidencial editados à mão ficam."""
    conn = _banco_antigo([
        ("Marcelo Freixo", ["marcelo freixo"], "centro", "#000000", 1, 0, "desistiu"),
    ])
    conn.execute("UPDATE candidatos SET data_status = '2026-08-01'")
    conn.commit()

    _popular_candidatos(conn)

    freixo = _linha(conn, "Marcelo Freixo")
    assert freixo["status"] == "desistiu"
    assert freixo["data_status"] == "2026-08-01"
    assert freixo["ativo"] == 0
    assert freixo["cor_hex"] == "#000000"
    assert freixo["espectro"] == "centro"
    assert freixo["is_presidencial"] == 1


def test_apelidos_novos_do_seed_sao_somados_sem_remover_os_existentes():
    conn = _banco_antigo([
        # "claudio castro" (sem acento) está no seed e falta aqui;
        # "castrinho" foi adicionado à mão e não está no seed.
        ("Cláudio Castro", ["cláudio castro", "castrinho"], "direita", "#C0392B", 0, 1, "ativo"),
    ])

    resumo = _popular_candidatos(conn)

    apelidos = json.loads(_linha(conn, "Cláudio Castro")["apelidos"])
    assert apelidos == ["cláudio castro", "castrinho", "claudio castro"]
    assert resumo["apelidos_adicionados"]["Cláudio Castro"] == ["claudio castro"]


def test_apelido_do_seed_que_ja_pertence_a_outro_candidato_nao_e_duplicado():
    """Edição manual moveu "garotinho" para outro nome: o seed não cria
    ambiguidade no mapa de normalização dando o mesmo apelido a dois."""
    conn = _banco_antigo([
        ("Rosinha Garotinho", ["rosinha garotinho", "garotinho"], "centro", "#111111", 0, 1, "ativo"),
    ])

    _popular_candidatos(conn)

    assert json.loads(_linha(conn, "Anthony Garotinho")["apelidos"]) == ["anthony garotinho"]
    assert json.loads(_linha(conn, "Rosinha Garotinho")["apelidos"]) == [
        "rosinha garotinho", "garotinho"]


def test_apelidos_ilegiveis_nao_sao_sobrescritos():
    conn = _banco_antigo([])
    conn.execute(
        "INSERT INTO candidatos (nome_canonico, apelidos, espectro, cor_hex, is_presidencial, ativo) "
        "VALUES ('Eduardo Paes', 'isso não é json', 'centro', '#0A2240', 0, 1)")
    conn.commit()

    _popular_candidatos(conn)

    assert _linha(conn, "Eduardo Paes")["apelidos"] == "isso não é json"


def test_init_db_completa_o_roster_de_banco_existente_e_loga(caplog):
    init_db()
    conn = get_conn()
    conn.execute("DELETE FROM candidatos WHERE nome_canonico IN ('Anthony Garotinho', 'Douglas Ruas')")
    conn.commit()
    conn.close()
    database._cache_candidatos = None

    with caplog.at_level(logging.INFO, logger="db.candidatos"):
        init_db()

    cores = database.get_cores_candidatos()
    assert cores["Anthony Garotinho"] == "#BA7517"
    assert cores["Douglas Ruas"] == _SEED["Douglas Ruas"][2]
    assert database.get_mapa_apelidos()["garotinho"] == "Anthony Garotinho"
    log = caplog.text
    assert "Anthony Garotinho" in log and "Douglas Ruas" in log
