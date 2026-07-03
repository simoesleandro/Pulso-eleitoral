"""
Migration: adiciona pct_pode_mudar_voto (REAL, nullable) à tabela `pesquisas`.

Captura o "% de eleitores que podem mudar de voto" quando o instituto
divulga esse dado explicitamente (ex.: Quaest divulgou esse número pro RJ).
Quando a matéria não menciona esse dado com clareza, o extrator
(collectors/gemini_extractor.py) grava null — nunca infere ou estima.

ALTER TABLE puro (sem drop/recreate), idempotente — pode rodar 2x sem erro,
e é resiliente a corrida entre processos (mesmo padrão de
scripts/migrate_candidatos_status.py: ALTER protegido contra
"duplicate column name", qualquer outro erro propaga).

Uso: python scripts/migrate_pesquisas_volatilidade.py
"""
import sqlite3

DB_PATH = "data/pulso.db"

_COLUNAS_NOVAS = [
    ("pct_pode_mudar_voto", "REAL"),
]


def _colunas_existentes(conn: sqlite3.Connection, tabela: str) -> set:
    cur = conn.execute(f"PRAGMA table_info({tabela})")
    return {row[1] for row in cur.fetchall()}


def aplicar_migracao(conn: sqlite3.Connection) -> None:
    """Adiciona pct_pode_mudar_voto em `pesquisas` (se ausente). Idempotente
    e resiliente a corrida entre machines (ver docstring do módulo)."""
    existentes = _colunas_existentes(conn, "pesquisas")
    for nome, definicao in _COLUNAS_NOVAS:
        if nome not in existentes:
            try:
                conn.execute(f"ALTER TABLE pesquisas ADD COLUMN {nome} {definicao}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e):
                    raise
    conn.commit()


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        aplicar_migracao(conn)
        print("Migração aplicada: coluna pct_pode_mudar_voto em `pesquisas`.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
