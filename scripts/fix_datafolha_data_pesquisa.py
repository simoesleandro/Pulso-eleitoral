"""
Corrige data_pesquisa nas pesquisas Datafolha que ficaram com a data de coleta
em vez da data real da pesquisa.

Critério para identificar registros errados:
  data_pesquisa == DATE(coletado_em)  AND  data_publicacao IS NOT NULL  AND  data_publicacao != data_pesquisa

Correção: data_pesquisa = data_publicacao (melhor proxy disponível; Gemini extraiu
corretamente a data do release e gravou em data_publicacao).
"""
import sqlite3
import sys


DB_PATH = "data/pulso.db"


def main(dry_run: bool = True):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT id, instituto_id, cargo, data_pesquisa, data_publicacao, coletado_em, fonte_url
        FROM pesquisas
        WHERE data_publicacao IS NOT NULL
          AND data_publicacao != ''
          AND DATE(coletado_em) = data_pesquisa
          AND data_publicacao != data_pesquisa
        ORDER BY id
    """)
    candidatos = cur.fetchall()

    if not candidatos:
        print("Nenhum registro com data_pesquisa errada encontrado.")
        conn.close()
        return

    print(f"{'DRY RUN' if dry_run else 'APLICANDO'}: {len(candidatos)} registro(s) a corrigir\n")
    print(f"{'ID':>4}  {'inst':>5}  {'cargo':<14}  {'data_pesquisa (antes)':<22}  {'data_pesquisa (depois)':<22}  URL")
    print("-" * 110)

    for r in candidatos:
        url_short = (r["fonte_url"] or "")
        idx = url_short.find("/eleicoes")
        url_short = url_short[idx:idx + 60] if idx != -1 else url_short[-50:]
        print(f"{r['id']:>4}  {r['instituto_id']:>5}  {r['cargo']:<14}  "
              f"{r['data_pesquisa']:<22}  {r['data_publicacao']:<22}  ...{url_short}")

    if not dry_run:
        cur.executemany(
            "UPDATE pesquisas SET data_pesquisa=? WHERE id=?",
            [(r["data_publicacao"], r["id"]) for r in candidatos]
        )
        conn.commit()
        print(f"\n{len(candidatos)} registro(s) corrigido(s).")
    else:
        print("\n[dry-run] Nenhuma alteração feita. Passe --apply para executar.")

    conn.close()


if __name__ == "__main__":
    dry_run = "--apply" not in sys.argv
    main(dry_run=dry_run)
