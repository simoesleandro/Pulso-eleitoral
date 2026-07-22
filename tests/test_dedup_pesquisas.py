import os
os.environ['TESTING'] = 'True'

import sqlite3

from scripts.migrate_dedup_pesquisas import deduplicar


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE pesquisas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, instituto_id INTEGER, cargo TEXT,
        data_pesquisa TEXT, data_publicacao TEXT, tamanho_amostra INTEGER,
        margem_erro REAL, registro_tse TEXT UNIQUE, fonte_url TEXT)""")
    conn.execute("""CREATE TABLE intencoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, pesquisa_id INTEGER,
        candidato TEXT, partido TEXT, percentual REAL, tipo TEXT)""")
    return conn


def _pesquisa(conn, registro, candidatos, amostra=2000, data="2026-07-20"):
    cur = conn.execute("""INSERT INTO pesquisas
        (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra,
         margem_erro, registro_tse, fonte_url)
        VALUES (7, 'presidente', ?, ?, ?, 2.0, ?, ?)""",
        (data, data, amostra, registro, f"http://x/{registro}"))
    pid = cur.lastrowid
    for nome, pct in candidatos.items():
        conn.execute("""INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo)
                        VALUES (?, ?, ?, 'estimulada')""", (pid, nome, pct))
    conn.commit()
    return pid


def test_funde_duplicata_truncada_preservando_a_completa():
    """Reproduz os ids 27/28 reais: mesma pesquisa, uma extração truncada."""
    conn = _conn()
    truncada = _pesquisa(conn, "GEN-a", {"Lula": 40.0, "Flávio Bolsonaro": 33.0})
    completa = _pesquisa(conn, "GEN-b", {
        "Lula": 40.0, "Flávio Bolsonaro": 33.0, "Renan Santos": 9.0,
        "Ronaldo Caiado": 7.0, "Romeu Zema": 2.0, "Augusto Cury": 1.0})

    resultado = deduplicar(conn)

    assert resultado["fundidas"] == 1
    restantes = [r["id"] for r in conn.execute("SELECT id FROM pesquisas")]
    assert restantes == [completa], "a extração completa deve sobreviver"
    assert conn.execute("SELECT COUNT(*) FROM intencoes WHERE pesquisa_id = ?",
                        (completa,)).fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM intencoes WHERE pesquisa_id = ?",
                        (truncada,)).fetchone()[0] == 0
    conn.close()


def test_move_intencao_exclusiva_da_perdedora():
    """Se a perdedora tem um candidato que a vencedora não tem, ele migra."""
    conn = _conn()
    _pesquisa(conn, "GEN-a", {"Lula": 40.0, "Ciro Gomes": 5.0})
    vencedora = _pesquisa(conn, "GEN-b", {
        "Lula": 40.0, "Flávio Bolsonaro": 33.0, "Renan Santos": 9.0})

    deduplicar(conn)

    candidatos = {r["candidato"] for r in conn.execute(
        "SELECT candidato FROM intencoes WHERE pesquisa_id = ?", (vencedora,))}
    assert "Ciro Gomes" in candidatos
    conn.close()


def test_nao_funde_pesquisas_de_datas_diferentes():
    conn = _conn()
    _pesquisa(conn, "GEN-a", {"Lula": 40.0}, data="2026-07-20")
    _pesquisa(conn, "GEN-b", {"Lula": 41.0}, data="2026-07-25")

    resultado = deduplicar(conn)

    assert resultado["fundidas"] == 0
    assert conn.execute("SELECT COUNT(*) FROM pesquisas").fetchone()[0] == 2
    conn.close()


def test_e_idempotente():
    conn = _conn()
    _pesquisa(conn, "GEN-a", {"Lula": 40.0})
    _pesquisa(conn, "GEN-b", {"Lula": 40.0, "Flávio Bolsonaro": 33.0})

    deduplicar(conn)
    resultado = deduplicar(conn)

    assert resultado["fundidas"] == 0
    conn.close()
