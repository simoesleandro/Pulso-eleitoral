import sqlite3

conn = sqlite3.connect('data/pulso.db')
cur = conn.cursor()

print("=== PESQUISAS DATAFOLHA (instituto_id=1) ===")
cur.execute("""
    SELECT p.id, p.data_pesquisa, p.data_publicacao, p.coletado_em,
           p.tamanho_amostra, p.margem_erro, p.fonte_url
    FROM pesquisas p
    WHERE p.instituto_id = 1
    ORDER BY p.data_pesquisa DESC
""")
rows = cur.fetchall()
for r in rows:
    url = (r[6] or '')
    url_short = url[url.find('/eleicoes'):][:70] if '/eleicoes' in url else url[-60:]
    print(f"  id={r[0]}  data_pesquisa={r[1]}  data_publicacao={r[2]}  "
          f"coletado={str(r[3])[:10]}  amostra={r[4]}  me={r[5]}  url=...{url_short}")

print(f"\nTotal: {len(rows)} pesquisas Datafolha")

print("\n=== INTENCOES DAS PESQUISAS DATAFOLHA ===")
cur.execute("""
    SELECT i.candidato, i.percentual, p.data_pesquisa, p.data_publicacao, p.fonte_url
    FROM intencoes i
    JOIN pesquisas p ON i.pesquisa_id = p.id
    WHERE p.instituto_id = 1
    ORDER BY p.data_pesquisa DESC, i.percentual DESC
""")
rows2 = cur.fetchall()
for r in rows2:
    url = (r[4] or '')
    url_short = url[url.find('/eleicoes'):][:55] if '/eleicoes' in url else url[-40:]
    print(f"  {r[0]:<28}  {r[1]:>5.1f}%  pesquisa={r[2]}  pub={r[3]}  ...{url_short}")

conn.close()
