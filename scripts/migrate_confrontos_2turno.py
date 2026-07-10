"""
Migration: cria a tabela `confrontos_2turno` (par A x B de 2º turno vindo das
próprias pesquisas), se ausente.

Alimenta get_simulacao_segundo_turno com números reais de confronto direto
quando existem; sem linhas, a função cai na simulação por redistribuição
(comportamento legado). CREATE TABLE IF NOT EXISTS puro, idempotente — pode
rodar em toda inicialização e é seguro sob corrida entre machines (mesmo padrão
de scripts/migrate_pesquisas_volatilidade.py).

Uso: python scripts/migrate_confrontos_2turno.py
"""
import sqlite3

DB_PATH = "data/pulso.db"

_CREATE = """
CREATE TABLE IF NOT EXISTS confrontos_2turno (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    instituto_id  INTEGER,
    cargo         TEXT NOT NULL DEFAULT 'presidente',
    candidato_a   TEXT NOT NULL,
    candidato_b   TEXT NOT NULL,
    pct_a         REAL NOT NULL,
    pct_b         REAL NOT NULL,
    data_pesquisa TEXT NOT NULL,
    tamanho_amostra INTEGER,
    fonte_url     TEXT,
    UNIQUE(instituto_id, cargo, data_pesquisa, candidato_a, candidato_b)
);
"""


def aplicar_migracao(conn: sqlite3.Connection) -> None:
    """Cria a tabela confrontos_2turno (se ausente). Idempotente."""
    conn.execute(_CREATE)
    conn.commit()


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        aplicar_migracao(conn)
        print("Migração aplicada: tabela `confrontos_2turno`.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
