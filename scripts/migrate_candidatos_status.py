"""
Migration: adiciona status de corrida à tabela `candidatos`.

Cláudio Castro (governador RJ) renunciou em 24/03/2026 e foi declarado
inelegível por 8 anos pelo TSE no mesmo dia. As colunas `status` e
`data_status` permitem marcar candidatos que saíram da corrida sem apagar
ou alterar as pesquisas históricas em que apareceram enquanto candidatos
de verdade.

ALTER TABLE puro (sem drop/recreate), idempotente — pode rodar 2x sem erro.

Uso: python scripts/migrate_candidatos_status.py
"""
import sqlite3

DB_PATH = "data/pulso.db"

_COLUNAS_NOVAS = [
    ("status", "TEXT NOT NULL DEFAULT 'ativo'"),
    ("data_status", "TEXT"),
]

# (nome_canonico, status, data_status)
_ATUALIZACOES_STATUS = [
    ("Cláudio Castro", "inelegivel", "2026-03-24"),
]


def _colunas_existentes(conn: sqlite3.Connection, tabela: str) -> set:
    cur = conn.execute(f"PRAGMA table_info({tabela})")
    return {row[1] for row in cur.fetchall()}


def aplicar_migracao(conn: sqlite3.Connection) -> None:
    """Adiciona colunas status/data_status em `candidatos` (se ausentes) e
    atualiza o status de candidatos que já saíram da corrida. Idempotente.

    O ALTER TABLE é protegido contra corrida entre processos: no Fly.io mais
    de uma machine pode chamar init_db() ao mesmo tempo, então entre o
    PRAGMA table_info (checagem) e o ALTER TABLE outra instância pode já ter
    adicionado a coluna. Se isso acontecer, o SQLite recusa com
    "duplicate column name" — ignoramos só esse erro específico; qualquer
    outro OperationalError é um problema real e deve propagar.
    """
    existentes = _colunas_existentes(conn, "candidatos")
    for nome, definicao in _COLUNAS_NOVAS:
        if nome not in existentes:
            try:
                conn.execute(f"ALTER TABLE candidatos ADD COLUMN {nome} {definicao}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e):
                    raise
    conn.commit()

    for nome_canonico, status, data_status in _ATUALIZACOES_STATUS:
        conn.execute(
            "UPDATE candidatos SET status = ?, data_status = ? WHERE nome_canonico = ?",
            (status, data_status, nome_canonico)
        )
    conn.commit()


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        aplicar_migracao(conn)
        print("Migração aplicada: colunas status/data_status em `candidatos`; "
              "Cláudio Castro marcado como inelegível (2026-03-24).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
