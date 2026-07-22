import os
os.environ['TESTING'] = 'True'

import sqlite3

import pytest

from database import DB_PATH, get_conn, init_db
from scripts.migrate_curadoria import (INSTITUTOS_AGREGADOS,
                                       promover_institutos_do_seed)


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


def test_init_db_promove_institutos_do_seed():
    """Guarda contra o dashboard zerar: depois do init_db nenhum instituto
    do seed pode ficar fora do agregado."""
    init_db(force_seed=True)
    conn = get_conn()
    try:
        fora = conn.execute(
            "SELECT nome FROM institutos WHERE agregar = 0"
        ).fetchall()
    finally:
        conn.close()
    assert [r["nome"] for r in fora] == [], "instituto do seed ficou fora do agregado"


def test_promocao_e_idempotente():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT, agregar INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO institutos (nome) VALUES ('Datafolha')")
    conn.commit()

    primeira = promover_institutos_do_seed(conn)
    segunda = promover_institutos_do_seed(conn)

    assert primeira == 1
    assert segunda == 0, "segunda passada não deve mexer em nada"
    conn.close()


def test_promocao_nao_ressuscita_instituto_rejeitado():
    """Instituto descoberto pelo TSE e rejeitado tem agregar=0 de propósito.
    A migração roda a cada init_db e não pode desfazer essa decisão."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT, agregar INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO institutos (nome, agregar) VALUES ('Vetor Arrow', 0)")
    conn.commit()

    promover_institutos_do_seed(conn)

    agregar = conn.execute(
        "SELECT agregar FROM institutos WHERE nome = 'Vetor Arrow'").fetchone()[0]
    assert agregar == 0, "rejeição manual não pode ser desfeita pela migração"
    conn.close()


def test_lista_cobre_os_institutos_do_seed():
    """A lista explícita e o seed.sql não podem divergir em silêncio."""
    init_db(force_seed=True)
    conn = get_conn()
    try:
        nomes = {r["nome"] for r in conn.execute("SELECT nome FROM institutos")}
    finally:
        conn.close()
    assert nomes == set(INSTITUTOS_AGREGADOS), (
        "seed.sql e INSTITUTOS_AGREGADOS divergiram — "
        "instituto novo no seed precisa de decisão explícita de curadoria"
    )
