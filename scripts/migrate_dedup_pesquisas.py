"""
Migration: funde pesquisas duplicadas criadas pela chave sintética de
`collectors/base.py`.

A chave `GEN-{instituto}-{cargo}-{data_coleta}-{sha1(url)}` usa a URL da
matéria, então duas reportagens sobre a mesma pesquisa viravam duas linhas —
e frequentemente uma delas é uma extração truncada. Confirmado em produção nos
ids 27 e 28 (Real Time, 2026-07-20, n=2000): a cópia extra tinha 2 candidatos
contra 6 da completa.

Sobrevive a pesquisa com mais intenções (extração mais completa); empate
desempata pelo maior id. Intenções exclusivas da perdedora migram antes de ela
ser apagada.

Idempotente: rodar de novo sobre um banco já limpo não muda nada.

Uso: python scripts/migrate_dedup_pesquisas.py
"""
import logging
import sqlite3

logger = logging.getLogger(__name__)

DB_PATH = "data/pulso.db"


def deduplicar(conn: sqlite3.Connection) -> dict:
    """Funde duplicatas. Devolve {"fundidas": int, "intencoes_movidas": int}."""
    grupos = conn.execute("""
        SELECT instituto_id, cargo, data_pesquisa, tamanho_amostra,
               GROUP_CONCAT(id) AS ids
        FROM pesquisas
        GROUP BY instituto_id, cargo, data_pesquisa, tamanho_amostra
        HAVING COUNT(*) > 1
    """).fetchall()

    fundidas = 0
    movidas = 0

    for grupo in grupos:
        ids = [int(x) for x in grupo["ids"].split(",")]

        contagens = {
            pid: conn.execute(
                "SELECT COUNT(*) FROM intencoes WHERE pesquisa_id = ?", (pid,)
            ).fetchone()[0]
            for pid in ids
        }
        vencedora = max(ids, key=lambda pid: (contagens[pid], pid))

        candidatos_vencedora = {
            r[0] for r in conn.execute(
                "SELECT candidato FROM intencoes WHERE pesquisa_id = ?", (vencedora,)
            )
        }

        for perdedora in ids:
            if perdedora == vencedora:
                continue

            exclusivas = conn.execute(
                "SELECT id, candidato FROM intencoes WHERE pesquisa_id = ?",
                (perdedora,),
            ).fetchall()
            for intencao in exclusivas:
                if intencao["candidato"] in candidatos_vencedora:
                    conn.execute("DELETE FROM intencoes WHERE id = ?", (intencao["id"],))
                else:
                    conn.execute(
                        "UPDATE intencoes SET pesquisa_id = ? WHERE id = ?",
                        (vencedora, intencao["id"]),
                    )
                    candidatos_vencedora.add(intencao["candidato"])
                    movidas += 1

            conn.execute("DELETE FROM pesquisas WHERE id = ?", (perdedora,))
            fundidas += 1
            logger.info("Pesquisa %d fundida em %d (duplicata).", perdedora, vencedora)

    conn.commit()
    return {"fundidas": fundidas, "intencoes_movidas": movidas}


def aplicar_migracao(conn: sqlite3.Connection) -> None:
    """Ponto de entrada para o init_db. Idempotente."""
    deduplicar(conn)


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        resultado = deduplicar(conn)
        print(f"Deduplicação: {resultado['fundidas']} pesquisas fundidas, "
              f"{resultado['intencoes_movidas']} intenções movidas.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
