"""
INSERÇÃO MANUAL PONTUAL de um confronto REAL de 2º turno — NÃO FAZ PARTE DO
PIPELINE DEFINITIVO.

Insere um par A x B de 2º turno verificado manualmente na tabela
`confrontos_2turno`, que alimenta get_simulacao_segundo_turno (que passa a usar
o número real em vez da simulação por redistribuição). Serve enquanto a
extração automática de 2º turno não existe/não foi validada.

Idempotente: a UNIQUE(instituto_id, cargo, data_pesquisa, candidato_a,
candidato_b) evita duplicar; INSERT OR REPLACE atualiza os percentuais se a
mesma peça for reinserida. Edite CONFRONTO abaixo e rode.

Uso: python scripts/seed_confronto_2turno.py
"""
import sqlite3

DB_PATH = "data/pulso.db"

# instituto_id: use o id já cadastrado do instituto (ver tabela institutos).
CONFRONTO = {
    "instituto_id": 3,            # ex.: 3 = Quaest
    "cargo": "presidente",
    "candidato_a": "Lula",
    "candidato_b": "Flávio Bolsonaro",
    "pct_a": 48.0,
    "pct_b": 45.0,
    "data_pesquisa": "2026-07-05",
    "tamanho_amostra": 2000,
    "fonte_url": "",              # opcional: link da matéria/registro
}


def inserir(conn: sqlite3.Connection, c: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO confrontos_2turno "
        "(instituto_id, cargo, candidato_a, candidato_b, pct_a, pct_b, data_pesquisa, tamanho_amostra, fonte_url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (c["instituto_id"], c["cargo"], c["candidato_a"], c["candidato_b"],
         c["pct_a"], c["pct_b"], c["data_pesquisa"], c["tamanho_amostra"], c["fonte_url"]),
    )
    conn.commit()
    print(f"Confronto inserido: {c['candidato_a']} {c['pct_a']} x {c['pct_b']} {c['candidato_b']} "
          f"({c['cargo']}, {c['data_pesquisa']}, instituto {c['instituto_id']}).")


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        inserir(conn, CONFRONTO)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
