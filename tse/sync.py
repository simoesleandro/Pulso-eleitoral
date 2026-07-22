"""Upsert dos registros do TSE em `pesquisas_tse`.

O upsert é por `protocolo` (chave real do TSE) e **preserva `pesquisa_id`** —
o casamento feito pelo matcher não pode ser desfeito por uma re-sincronização
diária. Por isso o ON CONFLICT lista as colunas uma a uma em vez de usar
INSERT OR REPLACE (que apagaria a linha inteira e com ela o casamento).
"""
import logging
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

_UPSERT = """
INSERT INTO pesquisas_tse
    (protocolo, cargo, cnpj_empresa, nome_empresa, data_inicio, data_fim,
     data_divulgacao, qt_entrevistado, abrangencia, sincronizado_em)
VALUES (:protocolo, :cargo, :cnpj_empresa, :nome_empresa, :data_inicio, :data_fim,
        :data_divulgacao, :qt_entrevistado, :abrangencia, :sincronizado_em)
ON CONFLICT(protocolo) DO UPDATE SET
    cargo            = excluded.cargo,
    cnpj_empresa     = excluded.cnpj_empresa,
    nome_empresa     = excluded.nome_empresa,
    data_inicio      = excluded.data_inicio,
    data_fim         = excluded.data_fim,
    data_divulgacao  = excluded.data_divulgacao,
    qt_entrevistado  = excluded.qt_entrevistado,
    abrangencia      = excluded.abrangencia,
    sincronizado_em  = excluded.sincronizado_em
"""


def sincronizar(conn: sqlite3.Connection, registros: list[dict]) -> dict:
    """Faz upsert dos registros e devolve {"inseridos": int, "atualizados": int}."""
    if not registros:
        return {"inseridos": 0, "atualizados": 0}

    existentes = {
        r[0] for r in conn.execute("SELECT protocolo FROM pesquisas_tse")
    }
    agora = datetime.now().isoformat(timespec="seconds")

    inseridos = 0
    atualizados = 0
    for registro in registros:
        if not registro.get("protocolo"):
            logger.warning("Registro do TSE sem protocolo, ignorado: %s",
                           registro.get("nome_empresa"))
            continue
        conn.execute(_UPSERT, {**registro, "sincronizado_em": agora})
        if registro["protocolo"] in existentes:
            atualizados += 1
        else:
            inseridos += 1

    conn.commit()
    logger.info("Sync TSE: %d inseridos, %d atualizados.", inseridos, atualizados)
    return {"inseridos": inseridos, "atualizados": atualizados}
