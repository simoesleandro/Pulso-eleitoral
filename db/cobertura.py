"""Leitura da cobertura: o que o TSE registrou e o Pulso ainda não tem.

As funções com prefixo `_` recebem a conexão e existem para o teste poder
usar um banco em memória; as públicas abrem a conexão sozinhas, como o resto
de `db/*`.
"""
from datetime import date

from db.core import get_db

# Registro de pesquisa municipal não pertence a uma série estadual/nacional —
# fica fora da fila mesmo quando o instituto é aprovado.
_NAO_MUNICIPAL = "(t.abrangencia IS NULL OR t.abrangencia != 'municipal')"


def _fila_de_trabalho(conn, cargo: str, limite: int = 50, offset: int = 0) -> list[dict]:
    """Registros encerrados, de instituto aprovado, ainda sem pesquisa."""
    rows = conn.execute(f"""
        SELECT t.protocolo, t.nome_empresa, t.data_inicio, t.data_fim,
               t.qt_entrevistado, t.abrangencia, i.nome AS instituto
        FROM pesquisas_tse t
        JOIN institutos i ON i.cnpj = t.cnpj_empresa
        WHERE t.cargo = ? AND t.pesquisa_id IS NULL
          AND t.data_fim < ? AND i.agregar = 1 AND {_NAO_MUNICIPAL}
        ORDER BY t.data_fim DESC, t.protocolo
        LIMIT ? OFFSET ?
    """, (cargo, date.today().isoformat(), limite, offset)).fetchall()
    return [dict(r) for r in rows]


def _contar_fila(conn, cargo: str) -> int:
    return conn.execute(f"""
        SELECT COUNT(*)
        FROM pesquisas_tse t
        JOIN institutos i ON i.cnpj = t.cnpj_empresa
        WHERE t.cargo = ? AND t.pesquisa_id IS NULL
          AND t.data_fim < ? AND i.agregar = 1 AND {_NAO_MUNICIPAL}
    """, (cargo, date.today().isoformat())).fetchone()[0]


def _institutos_para_descobrir(conn) -> list[dict]:
    """CNPJs do registro sem linha em `institutos` — nunca avaliados.

    Rejeitar cria a linha com agregar=0, então o instituto rejeitado some
    daqui e não reaparece a cada sync diário.
    """
    rows = conn.execute("""
        SELECT t.cnpj_empresa,
               MAX(t.nome_empresa) AS nome_empresa,
               COUNT(*) AS registros,
               CAST(AVG(t.qt_entrevistado) AS INTEGER) AS amostra_media,
               MAX(t.data_fim) AS ultimo_campo
        FROM pesquisas_tse t
        LEFT JOIN institutos i ON i.cnpj = t.cnpj_empresa
        WHERE i.id IS NULL AND t.cnpj_empresa != ''
        GROUP BY t.cnpj_empresa
        ORDER BY registros DESC, amostra_media DESC
    """).fetchall()
    return [dict(r) for r in rows]


def _em_campo_hoje(conn) -> list[dict]:
    hoje = date.today().isoformat()
    rows = conn.execute("""
        SELECT t.protocolo, t.cargo, t.nome_empresa, t.data_inicio, t.data_fim,
               t.qt_entrevistado
        FROM pesquisas_tse t
        WHERE t.data_inicio <= ? AND t.data_fim >= ?
        ORDER BY t.data_fim, t.protocolo
    """, (hoje, hoje)).fetchall()
    return [dict(r) for r in rows]


def _agendadas(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT t.protocolo, t.cargo, t.nome_empresa, t.data_inicio, t.data_fim,
               t.qt_entrevistado
        FROM pesquisas_tse t
        WHERE t.data_inicio > ?
        ORDER BY t.data_inicio, t.protocolo
    """, (date.today().isoformat(),)).fetchall()
    return [dict(r) for r in rows]


def fila_de_trabalho(cargo: str, limite: int = 50, offset: int = 0) -> list[dict]:
    with get_db() as conn:
        return _fila_de_trabalho(conn, cargo, limite, offset)


def contar_fila(cargo: str) -> int:
    with get_db() as conn:
        return _contar_fila(conn, cargo)


def institutos_para_descobrir() -> list[dict]:
    with get_db() as conn:
        return _institutos_para_descobrir(conn)


def em_campo_hoje() -> list[dict]:
    with get_db() as conn:
        return _em_campo_hoje(conn)


def agendadas() -> list[dict]:
    with get_db() as conn:
        return _agendadas(conn)
