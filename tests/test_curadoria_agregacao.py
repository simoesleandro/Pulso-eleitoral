import os
os.environ['TESTING'] = 'True'

from datetime import date, timedelta

import pytest

from database import (DB_PATH, get_conn, get_media_agregada,
                      get_pesquisa_por_id, init_db)


@pytest.fixture(autouse=True)
def cleanup():
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass
    yield
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass


def _base():
    """Schema + seed, sem as pesquisas de demonstração."""
    init_db(force_seed=True)
    conn = get_conn()
    conn.execute("DELETE FROM intencoes")
    conn.execute("DELETE FROM pesquisas")
    conn.commit()
    return conn


def _instituto(conn, nome, agregar):
    cur = conn.execute(
        "INSERT INTO institutos (nome, sigla, agregar) VALUES (?, ?, ?)",
        (nome, nome, agregar))
    conn.commit()
    return cur.lastrowid


def _pesquisa(conn, instituto_id, pct, amostra=1000, dias=1):
    data = (date.today() - timedelta(days=dias)).isoformat()
    cur = conn.execute(
        "INSERT INTO pesquisas (instituto_id, cargo, data_pesquisa, "
        "data_publicacao, tamanho_amostra, margem_erro, registro_tse, fonte_url) "
        "VALUES (?, 'presidente', ?, ?, ?, 2.0, ?, 'http://x')",
        (instituto_id, data, data, amostra, f"GEN-{instituto_id}-{pct}"))
    pid = cur.lastrowid
    conn.execute(
        "INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) "
        "VALUES (?, 'Lula', ?, 'estimulada')", (pid, pct))
    conn.execute(
        "INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) "
        "VALUES (?, 'Tarcísio', ?, 'estimulada')", (pid, 100 - pct))
    conn.commit()
    return pid


def test_instituto_nao_aprovado_fica_fora_da_media():
    conn = _base()
    try:
        _pesquisa(conn, _instituto(conn, "Aprovado A", agregar=1), pct=40)
        _pesquisa(conn, _instituto(conn, "Aprovado B", agregar=1), pct=40)
        # Instituto não aprovado com número absurdo: se entrasse, a média
        # de Lula sairia bem longe de 40.
        _pesquisa(conn, _instituto(conn, "Nao Aprovado", agregar=0), pct=90)
    finally:
        conn.close()

    media = get_media_agregada(cargo='presidente')
    lula = next(c for c in media['candidatos'] if c['candidato'] == 'Lula')

    assert lula['media'] == pytest.approx(40.0, abs=0.5)


def test_instituto_nao_aprovado_continua_visivel_no_detalhe():
    """O outro lado da decisão: fora da média, mas não escondido."""
    conn = _base()
    try:
        pid = _pesquisa(conn, _instituto(conn, "Nao Aprovado", agregar=0), pct=90)
    finally:
        conn.close()

    detalhe = get_pesquisa_por_id(pid)

    assert detalhe is not None, "pesquisa de instituto não aprovado sumiu do detalhe"
    assert detalhe['instituto'] == "Nao Aprovado"


def test_media_ignora_completamente_instituto_nao_aprovado():
    """Com apenas institutos não aprovados, não há agregado.

    Duas pesquisas de propósito: `get_media_agregada` descarta candidato com
    menos de duas entradas na janela, então uma pesquisa só sairia vazia
    mesmo com o instituto aprovado — o teste passaria sem provar nada.
    """
    conn = _base()
    try:
        nao_aprovado = _instituto(conn, "Nao Aprovado", agregar=0)
        _pesquisa(conn, nao_aprovado, pct=90, dias=1)
        _pesquisa(conn, nao_aprovado, pct=88, dias=5)
    finally:
        conn.close()

    media = get_media_agregada(cargo='presidente')

    assert media['candidatos'] == []
