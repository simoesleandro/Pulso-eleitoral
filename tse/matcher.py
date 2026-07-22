"""Casamento entre registro oficial do TSE e pesquisa já coletada.

Regra: mesmo instituto (via institutos.cnpj), mesmo cargo, e data_pesquisa da
pesquisa dentro de [data_inicio - 3 dias, data_divulgacao + 3 dias] do registro.

A folga de 3 dias absorve o fato de que hoje `data_pesquisa` é preenchida com a
data de publicação da matéria (bug que este casamento vem justamente corrigir).

**Ambiguidade nunca é resolvida por chute.** Se um registro casa com várias
pesquisas, ou várias pesquisas casam com o mesmo registro, o par é reportado em
`ambiguos` e não gravado: um falso negativo deixa um item a mais na fila de
cobertura, enquanto um falso positivo envenena a série histórica em silêncio.
"""
import logging
import sqlite3
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_FOLGA_DIAS = 3


def _mais(data_iso: str, dias: int) -> str:
    return (date.fromisoformat(data_iso) + timedelta(days=dias)).isoformat()


def aplicar_ligacao(conn: sqlite3.Connection, protocolo: str, pesquisa_id: int,
                    amostra_tse: int, data_fim: str) -> None:
    """Liga um registro do TSE a uma pesquisa e faz o backfill dos metadados.

    Usada tanto pelo casamento automático quanto pela ligação manual da tela
    de cobertura — a regra de backfill é do domínio, não do casador.

    **Não commita**: quem chama decide a transação (o casador aplica vários
    pares de uma vez; a rota manual aplica um só).
    """
    conn.execute(
        "UPDATE pesquisas_tse SET pesquisa_id = ? WHERE protocolo = ?",
        (pesquisa_id, protocolo),
    )
    # A amostra do TSE é a REGISTRADA (planejada); o release publica a
    # REALIZADA, que pode diferir (visto: 2000 registrado vs 2003 realizado).
    # Só preenche quando falta — nunca sobrescreve um valor real por um
    # planejado.
    conn.execute("""
        UPDATE pesquisas
        SET tamanho_amostra = CASE
                WHEN tamanho_amostra IS NULL OR tamanho_amostra = 0
                THEN ? ELSE tamanho_amostra END,
            data_pesquisa = ?,
            registro_tse = ?
        WHERE id = ?
    """, (amostra_tse, data_fim, protocolo, pesquisa_id))


def casar(conn: sqlite3.Connection, cargo: str, dry_run: bool = True) -> dict:
    """Casa registros do TSE com pesquisas coletadas.

    dry_run=True (padrão) apenas calcula e devolve o relatório, sem escrever.
    Devolve {"casados": [...], "ambiguos": [...], "sem_par": int}.
    """
    registros = conn.execute("""
        SELECT protocolo, cnpj_empresa, data_inicio, data_fim, data_divulgacao,
               qt_entrevistado
        FROM pesquisas_tse
        WHERE cargo = ? AND pesquisa_id IS NULL
        ORDER BY data_fim DESC
    """, (cargo,)).fetchall()

    candidatos_por_protocolo: dict[str, list] = {}
    protocolos_por_pesquisa: dict[int, list[str]] = {}

    for registro in registros:
        # Instituto sem CNPJ cadastrado nunca casa: '' não bate com NULL nem
        # com CNPJ real, então o registro fica na fila em vez de casar torto.
        if not registro["cnpj_empresa"]:
            candidatos_por_protocolo[registro["protocolo"]] = []
            continue

        limite_inicio = _mais(registro["data_inicio"], -_FOLGA_DIAS)
        limite_fim = _mais(
            registro["data_divulgacao"] or registro["data_fim"], _FOLGA_DIAS
        )

        pesquisas = conn.execute("""
            SELECT p.id, p.tamanho_amostra, p.data_pesquisa
            FROM pesquisas p
            JOIN institutos i ON i.id = p.instituto_id
            WHERE p.cargo = ? AND i.cnpj = ?
              AND p.data_pesquisa BETWEEN ? AND ?
        """, (cargo, registro["cnpj_empresa"], limite_inicio, limite_fim)).fetchall()

        candidatos_por_protocolo[registro["protocolo"]] = pesquisas
        for pesquisa in pesquisas:
            protocolos_por_pesquisa.setdefault(pesquisa["id"], []).append(
                registro["protocolo"]
            )

    casados = []
    ambiguos = []
    sem_par = 0

    for registro in registros:
        protocolo = registro["protocolo"]
        pesquisas = candidatos_por_protocolo[protocolo]

        if not pesquisas:
            sem_par += 1
            continue

        if len(pesquisas) > 1:
            ambiguos.append({
                "protocolo": protocolo,
                "motivo": "registro casa com mais de uma pesquisa",
                "pesquisa_ids": [p["id"] for p in pesquisas],
            })
            continue

        pesquisa = pesquisas[0]
        if len(protocolos_por_pesquisa[pesquisa["id"]]) > 1:
            ambiguos.append({
                "protocolo": protocolo,
                "motivo": "pesquisa casa com mais de um registro",
                "pesquisa_ids": [pesquisa["id"]],
            })
            continue

        casados.append({
            "protocolo": protocolo,
            "pesquisa_id": pesquisa["id"],
            "amostra_tse": registro["qt_entrevistado"],
            "amostra_atual": pesquisa["tamanho_amostra"],
            "data_tse": registro["data_fim"],
            "data_atual": pesquisa["data_pesquisa"],
        })

    if not dry_run:
        for par in casados:
            aplicar_ligacao(conn, protocolo=par["protocolo"],
                            pesquisa_id=par["pesquisa_id"],
                            amostra_tse=par["amostra_tse"],
                            data_fim=par["data_tse"])
        conn.commit()
        logger.info("Casamento aplicado: %d pares, %d ambíguos, %d sem par.",
                    len(casados), len(ambiguos), sem_par)

    return {"casados": casados, "ambiguos": ambiguos, "sem_par": sem_par}
