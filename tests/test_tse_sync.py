import os
os.environ['TESTING'] = 'True'

import sqlite3

from scripts.migrate_pesquisas_tse import (CNPJ_POR_INSTITUTO, aplicar_migracao,
                                           popular_cnpjs)


def _colunas(conn, tabela):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}


def test_migracao_cria_tabela_e_colunas():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT)")

    aplicar_migracao(conn)

    assert "pesquisas_tse" in {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    cols = _colunas(conn, "pesquisas_tse")
    assert {"protocolo", "cargo", "cnpj_empresa", "data_inicio",
            "data_fim", "qt_entrevistado", "abrangencia", "pesquisa_id"} <= cols
    assert {"cnpj", "agregar"} <= _colunas(conn, "institutos")
    conn.close()


def test_migracao_e_idempotente():
    """Rodar duas vezes não pode levantar (ALTER TABLE repetido é erro no SQLite)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT)")

    aplicar_migracao(conn)
    aplicar_migracao(conn)  # não deve levantar

    assert {"cnpj", "agregar"} <= _colunas(conn, "institutos")
    conn.close()


def test_popular_cnpjs_preenche_institutos_conhecidos():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT)")
    conn.execute("INSERT INTO institutos (id, nome) VALUES (1, 'Datafolha')")
    conn.execute("INSERT INTO institutos (id, nome) VALUES (3, 'Quaest')")
    aplicar_migracao(conn)

    popular_cnpjs(conn)

    linhas = {r["nome"]: r["cnpj"] for r in conn.execute("SELECT nome, cnpj FROM institutos")}
    assert linhas["Datafolha"] == "07630546000175"
    assert linhas["Quaest"] == "22445600000104"
    conn.close()


def test_popular_cnpjs_nao_sobrescreve_valor_existente():
    """Correção manual de CNPJ não pode ser desfeita pela migração."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT)")
    conn.execute("INSERT INTO institutos (id, nome) VALUES (1, 'Datafolha')")
    aplicar_migracao(conn)
    conn.execute("UPDATE institutos SET cnpj = '99999999000199' WHERE nome = 'Datafolha'")
    conn.commit()

    popular_cnpjs(conn)

    cnpj = conn.execute("SELECT cnpj FROM institutos WHERE nome = 'Datafolha'").fetchone()["cnpj"]
    assert cnpj == "99999999000199"
    conn.close()


def test_todo_cnpj_do_mapa_tem_14_digitos():
    for nome, cnpj in CNPJ_POR_INSTITUTO.items():
        assert cnpj.isdigit() and len(cnpj) == 14, f"CNPJ inválido para {nome}: {cnpj}"


def test_init_db_deixa_cnpjs_preenchidos(tmp_path, monkeypatch):
    """Regressão: a migração roda antes do seed.sql, então popular_cnpjs
    precisa ser chamado DEPOIS do seed — senão o UPDATE não acha linha e o
    casador nunca casa nada."""
    import database

    monkeypatch.setattr(database, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "pulso_test.db"))

    database.init_db(force_seed=False)

    conn = sqlite3.connect(str(tmp_path / "pulso_test.db"))
    conn.row_factory = sqlite3.Row
    preenchidos = conn.execute(
        "SELECT COUNT(*) FROM institutos WHERE cnpj IS NOT NULL AND cnpj != ''"
    ).fetchone()[0]
    conn.close()

    assert preenchidos >= 10, (
        f"esperado ao menos 10 institutos com CNPJ, veio {preenchidos}"
    )
