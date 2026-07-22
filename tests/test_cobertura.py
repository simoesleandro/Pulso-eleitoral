import os
os.environ['TESTING'] = 'True'

import sqlite3
from datetime import date, timedelta

# `import database` precisa vir antes de qualquer `db.*`: db/core.py importa
# `database` no topo, então entrar por um módulo de db/ direto pega
# db.core parcialmente inicializado (vale para todo o pacote, não só aqui —
# `import db.pesquisas` isolado falha igual). A façade é o ponto de entrada.
import database  # noqa: F401
from db.cobertura import (_agendadas, _contar_fila, _em_campo_hoje,
                          _fila_de_trabalho, _institutos_para_descobrir)
from scripts.migrate_pesquisas_tse import aplicar_migracao


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT, agregar INTEGER DEFAULT 0)")
    conn.execute("""CREATE TABLE pesquisas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, instituto_id INTEGER, cargo TEXT,
        data_pesquisa TEXT, data_publicacao TEXT, tamanho_amostra INTEGER,
        margem_erro REAL, registro_tse TEXT UNIQUE, fonte_url TEXT)""")
    aplicar_migracao(conn)
    return conn


def _reg(conn, protocolo, cnpj, inicio, fim, cargo="presidente",
         abrangencia="nacional", pesquisa_id=None, empresa="EMPRESA X"):
    conn.execute("""INSERT INTO pesquisas_tse
        (protocolo, cargo, cnpj_empresa, nome_empresa, data_inicio, data_fim,
         data_divulgacao, qt_entrevistado, abrangencia, pesquisa_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1200, ?, ?)""",
        (protocolo, cargo, cnpj, empresa, inicio, fim, fim, abrangencia, pesquisa_id))
    conn.commit()


def _dia(delta):
    return (date.today() + timedelta(days=delta)).isoformat()


def test_fila_traz_so_encerradas_de_instituto_aprovado():
    conn = _conn()
    conn.execute("INSERT INTO institutos (nome, agregar, cnpj) VALUES ('Aprovado', 1, '111')")
    conn.execute("INSERT INTO institutos (nome, agregar, cnpj) VALUES ('Rejeitado', 0, '222')")
    conn.commit()

    _reg(conn, "P1", "111", _dia(-10), _dia(-8))          # entra
    _reg(conn, "P2", "222", _dia(-10), _dia(-8))          # instituto rejeitado
    _reg(conn, "P3", "333", _dia(-10), _dia(-8))          # instituto desconhecido
    _reg(conn, "P4", "111", _dia(-2), _dia(+2))           # ainda em campo
    _reg(conn, "P5", "111", _dia(-10), _dia(-8), pesquisa_id=1)  # já ligada

    fila = _fila_de_trabalho(conn, cargo="presidente")

    assert [f["protocolo"] for f in fila] == ["P1"]
    assert _contar_fila(conn, cargo="presidente") == 1
    conn.close()


def test_fila_exclui_municipal():
    conn = _conn()
    conn.execute("INSERT INTO institutos (nome, agregar, cnpj) VALUES ('Aprovado', 1, '111')")
    conn.commit()
    _reg(conn, "R1", "111", _dia(-10), _dia(-8), cargo="governador_rj",
         abrangencia="estadual")
    _reg(conn, "R2", "111", _dia(-10), _dia(-8), cargo="governador_rj",
         abrangencia="municipal")

    fila = _fila_de_trabalho(conn, cargo="governador_rj")

    assert [f["protocolo"] for f in fila] == ["R1"], "pesquisa municipal não é série estadual"
    conn.close()


def test_fila_ordena_por_fim_de_campo_decrescente():
    conn = _conn()
    conn.execute("INSERT INTO institutos (nome, agregar, cnpj) VALUES ('Aprovado', 1, '111')")
    conn.commit()
    _reg(conn, "VELHA", "111", _dia(-40), _dia(-38))
    _reg(conn, "NOVA", "111", _dia(-5), _dia(-3))

    fila = _fila_de_trabalho(conn, cargo="presidente")

    assert [f["protocolo"] for f in fila] == ["NOVA", "VELHA"]
    conn.close()


def test_fila_pagina():
    conn = _conn()
    conn.execute("INSERT INTO institutos (nome, agregar, cnpj) VALUES ('Aprovado', 1, '111')")
    conn.commit()
    for n in range(5):
        _reg(conn, f"P{n}", "111", _dia(-20 - n), _dia(-18 - n))

    primeira = _fila_de_trabalho(conn, cargo="presidente", limite=2, offset=0)
    segunda = _fila_de_trabalho(conn, cargo="presidente", limite=2, offset=2)

    assert len(primeira) == 2
    assert len(segunda) == 2
    assert {f["protocolo"] for f in primeira} & {f["protocolo"] for f in segunda} == set()
    assert _contar_fila(conn, cargo="presidente") == 5, "contagem ignora a paginação"
    conn.close()


def test_descoberta_traz_so_cnpj_sem_instituto():
    conn = _conn()
    conn.execute("INSERT INTO institutos (nome, agregar, cnpj) VALUES ('Conhecido', 1, '111')")
    conn.commit()
    _reg(conn, "A1", "111", _dia(-10), _dia(-8), empresa="CONHECIDO")
    _reg(conn, "B1", "999", _dia(-10), _dia(-8), empresa="NOVO INSTITUTO LTDA")
    _reg(conn, "B2", "999", _dia(-20), _dia(-18), empresa="NOVO INSTITUTO LTDA")

    descoberta = _institutos_para_descobrir(conn)

    assert len(descoberta) == 1
    assert descoberta[0]["cnpj_empresa"] == "999"
    assert descoberta[0]["registros"] == 2
    assert descoberta[0]["nome_empresa"] == "NOVO INSTITUTO LTDA"
    conn.close()


def test_descoberta_nao_traz_instituto_rejeitado():
    """Rejeitar cria linha com agregar=0 justamente para sumir da descoberta."""
    conn = _conn()
    conn.execute("INSERT INTO institutos (nome, agregar, cnpj) VALUES ('Rejeitado', 0, '999')")
    conn.commit()
    _reg(conn, "B1", "999", _dia(-10), _dia(-8))

    assert _institutos_para_descobrir(conn) == []
    conn.close()


def test_em_campo_hoje_exclui_agendada():
    conn = _conn()
    _reg(conn, "AGORA", "111", _dia(-1), _dia(+1))
    _reg(conn, "AGENDADA", "111", _dia(+10), _dia(+13))
    _reg(conn, "ENCERRADA", "111", _dia(-10), _dia(-8))

    assert [r["protocolo"] for r in _em_campo_hoje(conn)] == ["AGORA"]
    assert [r["protocolo"] for r in _agendadas(conn)] == ["AGENDADA"]
    conn.close()
