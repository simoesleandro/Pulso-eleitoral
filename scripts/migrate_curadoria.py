"""Promove ao agregado os institutos que vieram do seed (curadoria inicial).

`institutos.agregar` nasceu na migração da Onda 1 com default 0 e ninguém
promoveu os institutos já curados. Enquanto nada lia o flag isso era
inofensivo; a partir do filtro de curadoria, 14 institutos em 0 significam
dashboard vazio.

A lista é **explícita** de propósito. Um `UPDATE institutos SET agregar = 1`
sem cláusula promoveria também os institutos descobertos pelo TSE e
rejeitados à mão — a migração roda a cada `init_db` e desfaria a decisão do
operador em silêncio. Mesmo motivo pelo qual `CNPJ_POR_INSTITUTO` é um mapa
explícito em `scripts/migrate_pesquisas_tse.py`.
"""
import logging
import sqlite3

logger = logging.getLogger(__name__)

# Os 14 institutos do seed.sql, curados à mão antes de a curadoria existir.
# Instituto novo no seed.sql precisa ser adicionado aqui conscientemente —
# tests/test_curadoria.py trava a divergência.
INSTITUTOS_AGREGADOS = (
    "Datafolha",
    "Ibope/IPEC",
    "Quaest",
    "Genial/Quaest",
    "Atlas",
    "Paraná",
    "Real Time",
    "Nexus/BTG Pactual",
    "Verita",
    "Futura Inteligência",
    "PoderData",
    "Meio/Ideia",
    "Vox Populi",
    "Instituto Gerp",
)


def promover_institutos_do_seed(conn: sqlite3.Connection) -> int:
    """Marca `agregar = 1` nos institutos do seed que ainda estiverem em 0.

    Idempotente: a cláusula `agregar = 0` faz a segunda passada não tocar em
    nada. Devolve quantas linhas foram promovidas.
    """
    marcadores = ",".join("?" * len(INSTITUTOS_AGREGADOS))
    cursor = conn.execute(
        f"UPDATE institutos SET agregar = 1 "
        f"WHERE nome IN ({marcadores}) AND agregar = 0",
        INSTITUTOS_AGREGADOS,
    )
    conn.commit()
    if cursor.rowcount:
        logger.info("Curadoria: %d institutos do seed promovidos ao agregado.",
                    cursor.rowcount)
    return cursor.rowcount
