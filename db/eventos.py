"""Eventos da campanha (F4 do PRD: marcadores no gráfico de tendência)."""
from datetime import date

from db.core import get_db

_EVENTO_CARGOS = {'presidente', 'governador_rj', 'geral'}
_EVENTO_IMPACTOS = {'positivo', 'negativo', 'neutro', 'indefinido'}


def listar_eventos(cargo: str | None = None) -> list[dict]:
    """Lista eventos ordenados por data. Se `cargo` for dado, traz os do cargo
    mais os 'geral' (que valem para todos os gráficos)."""
    with get_db() as conn:
        if cargo:
            rows = conn.execute(
                "SELECT id, data, titulo, descricao, cargo, impacto "
                "FROM eventos WHERE cargo IN (?, 'geral') ORDER BY data",
                (cargo,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, data, titulo, descricao, cargo, impacto "
                "FROM eventos ORDER BY data"
            ).fetchall()
    return [dict(r) for r in rows]


def criar_evento(data: str, titulo: str, cargo: str, impacto: str,
                 descricao: str | None = None) -> int:
    """Insere um evento. Valida cargo, impacto e formato de data (YYYY-MM-DD).
    Levanta ValueError se algo for inválido. Retorna o id criado."""
    if not titulo or not titulo.strip():
        raise ValueError("título é obrigatório")
    if cargo not in _EVENTO_CARGOS:
        raise ValueError(f"cargo inválido: {cargo!r}")
    if impacto not in _EVENTO_IMPACTOS:
        raise ValueError(f"impacto inválido: {impacto!r}")
    try:
        date.fromisoformat(data)
    except (ValueError, TypeError):
        raise ValueError(f"data inválida (use YYYY-MM-DD): {data!r}")
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO eventos (data, titulo, descricao, cargo, impacto) VALUES (?, ?, ?, ?, ?)",
            (data, titulo.strip(), (descricao or None), cargo, impacto)
        )
        conn.commit()
        return cur.lastrowid


def remover_evento(evento_id: int) -> bool:
    """Remove um evento pelo id. Retorna True se algo foi removido."""
    with get_db() as conn:
        cur = conn.execute("DELETE FROM eventos WHERE id = ?", (evento_id,))
        conn.commit()
        return cur.rowcount > 0
