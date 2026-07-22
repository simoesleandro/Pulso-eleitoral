import os
os.environ['TESTING'] = 'True'

import sqlite3

from scripts.migrate_pesquisas_tse import (CNPJ_POR_INSTITUTO, aplicar_migracao,
                                           popular_cnpjs)
from tse.sync import sincronizar


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


def _conn_migrada():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT)")
    conn.execute("CREATE TABLE pesquisas (id INTEGER PRIMARY KEY)")
    aplicar_migracao(conn)
    return conn


def _registro(protocolo="BR000012026", **kwargs):
    base = {
        "protocolo": protocolo,
        "cargo": "presidente",
        "cnpj_empresa": "11111111000111",
        "nome_empresa": "INSTITUTO TESTE",
        "data_inicio": "2026-07-01",
        "data_fim": "2026-07-03",
        "data_divulgacao": "2026-07-05",
        "qt_entrevistado": 2000,
        "abrangencia": "nacional",
    }
    base.update(kwargs)
    return base


def test_sincronizar_insere_registros():
    conn = _conn_migrada()

    resultado = sincronizar(conn, [_registro(), _registro("BR000022026")])

    assert resultado == {"inseridos": 2, "atualizados": 0}
    assert conn.execute("SELECT COUNT(*) FROM pesquisas_tse").fetchone()[0] == 2
    conn.close()


def test_sincronizar_e_idempotente():
    """Rodar o mesmo lote duas vezes não duplica nem conta como inserção."""
    conn = _conn_migrada()

    sincronizar(conn, [_registro()])
    resultado = sincronizar(conn, [_registro()])

    assert resultado == {"inseridos": 0, "atualizados": 1}
    assert conn.execute("SELECT COUNT(*) FROM pesquisas_tse").fetchone()[0] == 1
    conn.close()


def test_sincronizar_atualiza_campo_corrigido_pelo_tse():
    """O TSE pode corrigir um registro; o upsert reflete a correção."""
    conn = _conn_migrada()
    sincronizar(conn, [_registro(qt_entrevistado=2000)])

    sincronizar(conn, [_registro(qt_entrevistado=2500)])

    linha = conn.execute(
        "SELECT qt_entrevistado FROM pesquisas_tse WHERE protocolo = ?",
        ("BR000012026",),
    ).fetchone()
    assert linha["qt_entrevistado"] == 2500
    conn.close()


def test_sincronizar_preserva_o_casamento_ja_feito():
    """Re-sincronizar não pode apagar o pesquisa_id ligado pelo matcher."""
    conn = _conn_migrada()
    conn.execute("INSERT INTO pesquisas (id) VALUES (7)")
    sincronizar(conn, [_registro()])
    conn.execute("UPDATE pesquisas_tse SET pesquisa_id = 7 WHERE protocolo = ?",
                 ("BR000012026",))
    conn.commit()

    sincronizar(conn, [_registro(qt_entrevistado=2500)])

    linha = conn.execute(
        "SELECT pesquisa_id FROM pesquisas_tse WHERE protocolo = ?",
        ("BR000012026",),
    ).fetchone()
    assert linha["pesquisa_id"] == 7, "o upsert não pode zerar o casamento"
    conn.close()
