"""
Sincroniza o registro oficial de pesquisas do TSE e casa com o que já foi
coletado.

Diferente de `coletar.py`, este script **não chama o Gemini** — é só download
de CSV e escrita em SQLite. Por isso pode rodar diariamente sem consumir a cota
mensal que limita a coleta a 2x/semana.

Uso:
    python scripts/sync_tse.py            # dry-run: mostra o que casaria
    python scripts/sync_tse.py --aplicar  # grava casamentos e backfill
"""
import argparse
import logging
import os
import sys

# Rodar `python scripts/sync_tse.py` coloca scripts/ no sys.path, não a raiz do
# repo — sem isso, `import db.core` falha. Funciona também via
# `python -m scripts.sync_tse`, onde a raiz já está no path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Entra pela façade `database`, não por `db.core`: db/core.py importa
# `database` no topo, então importar db.core primeiro dispara ImportError de
# import circular. A façade é o ponto de entrada documentado (CLAUDE.md).
from database import get_conn  # noqa: E402
from tse.dataset import (ARQUIVO_GOVERNADOR_RJ, ARQUIVO_PRESIDENTE,  # noqa: E402
                         baixar_zip, extrair_csv, parsear_csv)
from tse.matcher import casar  # noqa: E402
from tse.sync import sincronizar  # noqa: E402

logger = logging.getLogger(__name__)

_CARGOS = [
    ("presidente", ARQUIVO_PRESIDENTE),
    ("governador_rj", ARQUIVO_GOVERNADOR_RJ),
]


def sincronizar_tse(dry_run: bool = True) -> dict:
    """Baixa o dataset do TSE, sincroniza e casa. Devolve o relatório."""
    zip_bytes = baixar_zip()
    resultado = {}

    conn = get_conn()
    try:
        for cargo, arquivo in _CARGOS:
            registros = parsear_csv(extrair_csv(zip_bytes, arquivo), cargo=cargo)
            resultado[cargo] = sincronizar(conn, registros)

        casamento = {}
        for cargo, _ in _CARGOS:
            casamento[cargo] = casar(conn, cargo=cargo, dry_run=dry_run)
        resultado["casamento"] = casamento
    finally:
        conn.close()

    return resultado


def main():
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    parser = argparse.ArgumentParser(description="Sincroniza pesquisas registradas no TSE")
    parser.add_argument("--aplicar", action="store_true",
                        help="grava os casamentos (sem esta flag, é dry-run)")
    args = parser.parse_args()

    resultado = sincronizar_tse(dry_run=not args.aplicar)

    for cargo, _ in _CARGOS:
        contagem = resultado[cargo]
        print(f"{cargo}: {contagem['inseridos']} inseridos, "
              f"{contagem['atualizados']} atualizados")

    for cargo, relatorio in resultado["casamento"].items():
        print(f"\n{cargo}: {len(relatorio['casados'])} casamentos, "
              f"{len(relatorio['ambiguos'])} ambíguos, "
              f"{relatorio['sem_par']} sem par")
        for par in relatorio["casados"]:
            print(f"  {par['protocolo']}: pesquisa {par['pesquisa_id']} "
                  f"amostra {par['amostra_atual']} -> {par['amostra_tse']}, "
                  f"data {par['data_atual']} -> {par['data_tse']}")
        for ambiguo in relatorio["ambiguos"]:
            print(f"  AMBÍGUO {ambiguo['protocolo']}: {ambiguo['motivo']} "
                  f"{ambiguo['pesquisa_ids']}")

    if not args.aplicar:
        print("\n(dry-run — nada foi gravado. Use --aplicar para gravar.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
