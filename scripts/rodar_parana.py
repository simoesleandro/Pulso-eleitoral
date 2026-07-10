"""
Runner de validação do ParanaPesquisasCollector (governador RJ via PDF).

O coletor está FORA do ALL_COLLECTORS até validação ao vivo. Este script roda
ele isolado:

  - dry-run (padrão): faz fetch(), imprime os itens extraídos e NÃO grava nada.
  - com --salvar: grava no banco (mesma persistência do run() automático).

Pré-requisitos:
  - GEMINI_API_KEY no .env (o coletor extrai o PDF via Gemini)
  - Chromium do Playwright instalado (se precisar: playwright install chromium)

Uso:
  python scripts/rodar_parana.py            # dry-run: só mostra o que extraiu
  python scripts/rodar_parana.py --salvar   # grava no banco local
"""
import os
import sys
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')


def main():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))

    if not os.getenv("GEMINI_API_KEY"):
        print("ERRO: GEMINI_API_KEY não está no ambiente/.env — a extração do PDF não vai funcionar.")
        sys.exit(1)

    import database
    from collectors.paraná_pesquisas import ParanaPesquisasCollector

    coletor = ParanaPesquisasCollector(db_path=database.DB_PATH)

    print("\n=== fetch() (dry-run — nada gravado ainda) ===")
    itens = coletor.fetch()

    if not itens:
        print("\nNenhum item extraído. Verifique o log acima (listagem RJ vazia? PDF não achado? "
              "extração retornou vazio?).")
        return

    print(f"\n=== {len(itens)} intenção(ões) extraída(s) ===")
    for it in itens:
        print(f"  [{it.get('cargo')}] {it.get('candidato'):<25} {it.get('percentual'):>5}%  "
              f"| {it.get('data_pesquisa')} | {it.get('fonte_url', '')[:70]}")

    if '--salvar' in sys.argv:
        print("\n=== --salvar: gravando no banco ===")
        resultado = coletor.save(itens)
        print(f"  status: {resultado}")
        print("\nPara subir pro Fly.io depois de conferir: python scripts/sync_db.py")
    else:
        print("\nDry-run: nada foi gravado. Se os números acima estiverem corretos, rode de novo com --salvar.")


if __name__ == "__main__":
    main()
