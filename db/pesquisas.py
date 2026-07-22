"""Leitura/agregação de pesquisas: comparativos, poll-of-polls ponderado,
house effects, séries históricas e listagens diversas.

`get_media_agregada` tem contrato numérico fixado em tests/test_agregacao.py
(ver CLAUDE.md) — não alterar a fórmula aqui, só a localização do código.
"""
from datetime import date, timedelta
from statistics import mean

from db.core import get_conn, get_db
from db.candidatos import get_cores_candidatos

# Cores canônicas vêm da tabela candidatos (get_cores_candidatos);
# esta paleta é só o fallback para candidatos sem cor definida.
_FALLBACK_COLORS = ['#0A2240', '#C0392B', '#5a7184', '#B4B2A9', '#1D9E75']

_EXCLUIR_CATEGORIAS = ['outros', 'nulos', 'brancos', 'indecisos', 'não sabe', 'nao sabe', 'não respondeu', 'nao respondeu']


def _e_candidato(nome: str) -> bool:
    nome_lower = nome.lower()
    return not any(excluir in nome_lower for excluir in _EXCLUIR_CATEGORIAS)


def get_comparativo_candidato(candidato: str, cargo: str) -> dict:
    """Retorna a pesquisa mais recente de cada instituto para o candidato/cargo."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT inst.nome AS instituto, i.percentual,
                   p.data_pesquisa AS data, p.margem_erro
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            JOIN institutos inst ON p.instituto_id = inst.id
            WHERE i.candidato = ? AND p.cargo = ?
            AND p.id = (
                SELECT p2.id FROM pesquisas p2
                JOIN intencoes i2 ON i2.pesquisa_id = p2.id
                WHERE p2.instituto_id = inst.id AND p2.cargo = ?
                  AND i2.candidato = ?
                ORDER BY p2.data_pesquisa DESC LIMIT 1
            )
            ORDER BY i.percentual DESC
        """, (candidato, cargo, cargo, candidato)).fetchall()

    return {
        "candidato": candidato,
        "cargo": cargo,
        "institutos": [
            {
                "instituto": r["instituto"],
                "percentual": r["percentual"],
                "data": r["data"],
                "margem_erro": r["margem_erro"]
            }
            for r in rows
        ]
    }


def get_pesquisas_mais_recentes(cargo: str, tipo: str = 'estimulada') -> list[dict]:
    """Retorna a pesquisa mais recente do cargo (do tipo solicitado) e suas intenções.

    tipo='estimulada' inclui também registros legados sem tipo (NULL);
    tipo='espontanea' casa exatamente. A pesquisa escolhida é a mais recente
    que contenha intenções do tipo pedido.
    """
    if tipo == 'espontanea':
        filtro_int = "int.tipo = 'espontanea'"
        filtro_sub = "i2.tipo = 'espontanea'"
    else:
        filtro_int = "(int.tipo = 'estimulada' OR int.tipo IS NULL)"
        filtro_sub = "(i2.tipo = 'estimulada' OR i2.tipo IS NULL)"
    conn = get_conn()
    try:
        cursor = conn.cursor()
        # Encontra a pesquisa mais recente que tenha intenções do tipo pedido.
        # LEFT JOIN com candidatos: categorias que não são candidatos de verdade
        # (outros/nulos/brancos/indecisos) não têm linha em `candidatos` e
        # continuam aparecendo; candidatos com status != 'ativo' (desistente,
        # inelegível) são excluídos desta lista de "corrida atual".
        cursor.execute(f"""
            SELECT p.id, p.data_pesquisa, p.margem_erro, p.tamanho_amostra, p.fonte_url, inst.nome AS instituto,
                   int.candidato, int.percentual, int.partido, int.tipo
            FROM pesquisas p
            JOIN institutos inst ON p.instituto_id = inst.id
            JOIN intencoes int ON int.pesquisa_id = p.id
            LEFT JOIN candidatos c ON c.nome_canonico = int.candidato
            WHERE p.cargo = ? AND {filtro_int} AND p.id = (
                SELECT p2.id FROM pesquisas p2
                JOIN intencoes i2 ON i2.pesquisa_id = p2.id
                WHERE p2.cargo = ? AND {filtro_sub}
                ORDER BY p2.data_pesquisa DESC, p2.id DESC
                LIMIT 1
            )
            AND (c.status IS NULL OR c.status = 'ativo')
            ORDER BY int.percentual DESC
        """, (cargo, cargo))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()


def detectar_variacoes_bruscas(cargo: str = 'presidente',
                                limiar_pp: float = 3.0,
                                janela_dias: int = 7) -> list[dict]:
    """Detecta candidatos com variação >= limiar_pp nos últimos janela_dias."""
    data_limite = (date.today() - timedelta(days=janela_dias)).isoformat()

    # Um candidato pode ter mais de um par (recente, anterior) qualificado —
    # ex.: dois institutos com pesquisa na mesma data máxima. Um `GROUP BY
    # candidato` com colunas não-agregadas deixava o SQLite escolher pct/
    # instituto/datas de uma linha ARBITRÁRIA (podia não bater com o maior |Δ|
    # do ORDER BY). Aqui, ROW_NUMBER seleciona por candidato o par de MAIOR |Δ|
    # de forma determinística, mantendo pct/instituto/datas coerentes entre si.
    query = """
    WITH pares AS (
        SELECT
            i_recente.candidato AS candidato,
            i_recente.percentual AS pct_atual,
            p_recente.data_pesquisa AS data_atual,
            inst_recente.nome AS instituto_atual,
            i_anterior.percentual AS pct_anterior,
            p_anterior.data_pesquisa AS data_anterior,
            inst_anterior.nome AS instituto_anterior,
            ABS(i_recente.percentual - i_anterior.percentual) AS delta
        FROM intencoes i_recente
        JOIN pesquisas p_recente ON i_recente.pesquisa_id = p_recente.id
        JOIN institutos inst_recente ON p_recente.instituto_id = inst_recente.id
        JOIN intencoes i_anterior ON i_anterior.candidato = i_recente.candidato
        JOIN pesquisas p_anterior ON i_anterior.pesquisa_id = p_anterior.id
        JOIN institutos inst_anterior ON p_anterior.instituto_id = inst_anterior.id
        WHERE p_recente.cargo = ?
        AND p_recente.data_pesquisa = (
            SELECT MAX(p2.data_pesquisa) FROM pesquisas p2
            JOIN intencoes i2 ON i2.pesquisa_id = p2.id
            WHERE i2.candidato = i_recente.candidato AND p2.cargo = ?
        )
        AND p_anterior.data_pesquisa <= ?
        AND p_anterior.data_pesquisa = (
            SELECT MAX(p3.data_pesquisa) FROM pesquisas p3
            JOIN intencoes i3 ON i3.pesquisa_id = p3.id
            WHERE i3.candidato = i_recente.candidato
            AND p3.cargo = ?
            AND p3.data_pesquisa <= ?
        )
        AND p_anterior.instituto_id = p_recente.instituto_id
        AND ABS(i_recente.percentual - i_anterior.percentual) >= ?
        AND LOWER(i_recente.candidato) NOT LIKE '%outros%'
        AND LOWER(i_recente.candidato) NOT LIKE '%nulos%'
        AND LOWER(i_recente.candidato) NOT LIKE '%brancos%'
    ),
    ranked AS (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY candidato
            ORDER BY delta DESC, data_atual DESC, instituto_atual
        ) AS rn
        FROM pares
    )
    SELECT candidato, pct_atual, data_atual, instituto_atual,
           pct_anterior, data_anterior, instituto_anterior
    FROM ranked
    WHERE rn = 1
    ORDER BY delta DESC
    """

    with get_db() as conn:
        rows = conn.execute(query, (
            cargo, cargo, data_limite,
            cargo, data_limite, limiar_pp
        )).fetchall()

    alertas = []
    for row in rows:
        variacao = round(row['pct_atual'] - row['pct_anterior'], 1)
        alertas.append({
            'candidato': row['candidato'],
            'percentual_atual': row['pct_atual'],
            'percentual_anterior': row['pct_anterior'],
            'variacao': variacao,
            'direcao': 'up' if variacao > 0 else 'down',
            'data_atual': row['data_atual'],
            'data_anterior': row['data_anterior'],
            'instituto_atual': row['instituto_atual'],
            'instituto_anterior': row['instituto_anterior'],
        })

    return alertas


_FATOR_TETO_AMOSTRA = 2.0


def _teto_amostra(amostras: list[int]) -> int:
    """Teto de peso: o dobro da mediana das amostras da janela.

    Existe para que um instituto com amostra muito acima das demais não dite a
    média sozinho. Um percentil alto (p90) **não** serve aqui: com o número de
    institutos que existe na prática (5 a 10), o nearest-rank do p90 seleciona
    justamente o maior valor, e o teto nunca morderia — inclusive no caso que
    motivou a regra (uma série de tracking de n=14.000 entre institutos de
    n≈1.200 no Rio de Janeiro).

    A mediana é robusta a outlier por construção, então o teto acompanha o
    tamanho típico das pesquisas do momento em vez de ser um número fixo. O
    fator 2 dá folga para variação legítima de amostra: só morde quando uma
    pesquisa é mais que o dobro da mediana. Estatisticamente isso custa pouco —
    o ganho de margem de erro acima de ~2.000 entrevistas é marginal.
    """
    validas = sorted(a for a in amostras if a and a > 0)
    if not validas:
        return 1000

    meio = len(validas) // 2
    if len(validas) % 2:
        mediana = float(validas[meio])
    else:
        mediana = (validas[meio - 1] + validas[meio]) / 2

    return int(mediana * _FATOR_TETO_AMOSTRA)


def get_media_agregada(cargo: str, dias: int = 30) -> dict:
    """Retorna média agregada (poll-of-polls ponderado) por candidato.

    Em vez de média simples de todas as pesquisas — que deixaria um instituto
    prolífico dominar — o cálculo:
      1. Usa SOMENTE a pesquisa mais recente de cada instituto (1 voto/instituto);
      2. Pondera por tamanho de amostra (peso = amostra, ou 1000 se ausente),
         limitado ao percentil 90 das amostras da janela;
      3. Pondera por recência via decaimento exponencial (0.9 ^ dias);
      4. score = peso_amostra * peso_recencia;
      5. média ponderada = SUM(percentual * score) / SUM(score).

    A variação no período continua sendo medida sobre todas as pesquisas da
    janela (sinal temporal), independente da deduplicação usada na média.
    """
    data_limite = (date.today() - timedelta(days=dias)).isoformat()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT i.candidato, i.percentual, p.id AS pesquisa_id, p.data_pesquisa,
                   p.tamanho_amostra, inst.nome AS instituto
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            JOIN institutos inst ON p.instituto_id = inst.id
            LEFT JOIN candidatos c ON c.nome_canonico = i.candidato
            WHERE p.cargo = ? AND p.data_pesquisa >= ?
            AND (i.tipo = 'estimulada' OR i.tipo IS NULL)
            AND (c.status IS NULL OR c.status = 'ativo')
            AND LOWER(i.candidato) NOT LIKE '%outros%'
            AND LOWER(i.candidato) NOT LIKE '%nulos%'
            AND LOWER(i.candidato) NOT LIKE '%brancos%'
            AND LOWER(i.candidato) NOT LIKE '%indecisos%'
            AND LOWER(i.candidato) NOT LIKE '%não sabe%'
            AND LOWER(i.candidato) NOT LIKE '%não respondeu%'
            ORDER BY i.candidato, p.data_pesquisa
        """, (cargo, data_limite)).fetchall()

    # Lista completa por candidato (para a variação temporal e o filtro de ruído)
    por_candidato: dict[str, list] = {}
    # Estrutura de pesquisas: pesquisa_id -> {instituto, data, amostra, cands: {nome: pct}}
    polls: dict[int, dict] = {}
    for r in rows:
        por_candidato.setdefault(r['candidato'], []).append(r)
        poll = polls.setdefault(r['pesquisa_id'], {
            'instituto': r['instituto'],
            'data': r['data_pesquisa'],
            'amostra': r['tamanho_amostra'] or 0,
            'cands': {},
        })
        poll['cands'][r['candidato']] = r['percentual']

    # 1. Seleciona a pesquisa mais recente de cada instituto (desempate por id)
    recente_por_instituto: dict[str, int] = {}
    for pid, poll in polls.items():
        atual = recente_por_instituto.get(poll['instituto'])
        if atual is None or (poll['data'], pid) > (polls[atual]['data'], atual):
            recente_por_instituto[poll['instituto']] = pid
    pids_selecionados = set(recente_por_instituto.values())

    # 2-4. Score de cada pesquisa selecionada = peso_amostra * peso_recencia
    hoje = date.today()
    teto = _teto_amostra([polls[pid]['amostra'] for pid in pids_selecionados])
    scores: dict[int, float] = {}
    for pid in pids_selecionados:
        poll = polls[pid]
        peso_amostra = poll['amostra'] if poll['amostra'] and poll['amostra'] > 0 else 1000
        # Teto: nenhuma pesquisa pesa mais que o dobro da mediana das amostras
        # da janela — evita que um tracking de amostra atípica dite o agregado.
        peso_amostra = min(peso_amostra, teto)
        try:
            dias_desde = max(0, (hoje - date.fromisoformat(poll['data'])).days)
        except (ValueError, TypeError):
            dias_desde = 0
        peso_recencia = 0.9 ** dias_desde
        scores[pid] = peso_amostra * peso_recencia

    data_meio = (date.today() - timedelta(days=dias // 2)).isoformat()

    candidatos_resultado = []
    institutos_set: set[str] = set()
    total_pesquisas = 0

    for candidato, entradas in por_candidato.items():
        if len(entradas) < 2:
            continue

        # 5. Média ponderada sobre as pesquisas selecionadas (1 por instituto)
        num = 0.0
        den = 0.0
        percentuais_sel = []
        for pid in pids_selecionados:
            poll = polls[pid]
            if candidato not in poll['cands']:
                continue
            pct = poll['cands'][candidato]
            s = scores[pid]
            num += pct * s
            den += s
            percentuais_sel.append(pct)
            institutos_set.add(poll['instituto'])

        if den == 0 or not percentuais_sel:
            continue
        media_ponderada = num / den

        # Variação no período: todas as pesquisas da janela (sinal temporal)
        recentes = [e['percentual'] for e in entradas if e['data_pesquisa'] >= data_meio]
        anteriores = [e['percentual'] for e in entradas if e['data_pesquisa'] < data_meio]
        if recentes and anteriores:
            variacao = round(mean(recentes) - mean(anteriores), 1)
        else:
            variacao = None

        candidatos_resultado.append({
            "candidato": candidato,
            "media": round(media_ponderada, 1),
            "min": round(min(percentuais_sel), 1),
            "max": round(max(percentuais_sel), 1),
            "variacao_30d": variacao,
            "pesquisas_count": len(percentuais_sel),
        })
        total_pesquisas += len(percentuais_sel)

    candidatos_resultado.sort(key=lambda x: x['media'], reverse=True)

    return {
        "cargo": cargo,
        "periodo": f"últimos {dias} dias",
        "total_pesquisas": total_pesquisas,
        "institutos_incluidos": sorted(institutos_set),
        "candidatos": candidatos_resultado,
        "atualizado_em": date.today().strftime("%d/%m/%Y"),
    }


def get_house_effects(cargo: str = 'presidente', dias: int = 90) -> dict:
    """Desvio sistemático (house effect) de cada instituto vs. a média dos DEMAIS
    institutos, por candidato, na janela de `dias`.

    Para cada candidato com pesquisas de >= 3 institutos na janela, e cada
    instituto com >= 2 pesquisas desse candidato:
        efeito = média_do_instituto(cand) - média das médias dos OUTROS institutos(cand)
    Thresholds evitam reportar ruído como viés. Não ajusta a média agregada —
    é só leitura/contexto (documentado em /metodologia).
    """
    data_limite = (date.today() - timedelta(days=dias)).isoformat()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT i.candidato, i.percentual, inst.nome AS instituto
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            JOIN institutos inst ON p.instituto_id = inst.id
            LEFT JOIN candidatos c ON c.nome_canonico = i.candidato
            WHERE p.cargo = ? AND p.data_pesquisa >= ?
            AND (i.tipo = 'estimulada' OR i.tipo IS NULL)
            AND (c.status IS NULL OR c.status = 'ativo')
            AND LOWER(i.candidato) NOT LIKE '%outros%'
            AND LOWER(i.candidato) NOT LIKE '%nulos%'
            AND LOWER(i.candidato) NOT LIKE '%brancos%'
            AND LOWER(i.candidato) NOT LIKE '%indecisos%'
            AND LOWER(i.candidato) NOT LIKE '%não sabe%'
            AND LOWER(i.candidato) NOT LIKE '%não respondeu%'
        """, (cargo, data_limite)).fetchall()

    # pcts[candidato][instituto] = [percentuais]
    pcts: dict[str, dict[str, list]] = {}
    for r in rows:
        pcts.setdefault(r['candidato'], {}).setdefault(r['instituto'], []).append(r['percentual'])

    efeitos_por_instituto: dict[str, list] = {}
    for candidato, por_inst in pcts.items():
        if len(por_inst) < 3:   # precisa de >= 3 institutos para ter "os demais"
            continue
        medias = {inst: mean(lst) for inst, lst in por_inst.items()}
        for inst, lst in por_inst.items():
            if len(lst) < 2:    # instituto com 1 pesquisa é ruído, não viés
                continue
            demais = [m for i2, m in medias.items() if i2 != inst]
            efeito = round(medias[inst] - mean(demais), 1)
            if efeito == 0:
                efeito = 0.0  # normaliza -0.0

            efeitos_por_instituto.setdefault(inst, []).append({
                "candidato": candidato,
                "efeito_pp": efeito,
                "n_pesquisas": len(lst),
            })

    institutos = []
    for inst in sorted(efeitos_por_instituto):
        efeitos = sorted(efeitos_por_instituto[inst], key=lambda e: e['candidato'])
        institutos.append({"instituto": inst, "efeitos": efeitos})

    return {
        "cargo": cargo,
        "janela_dias": dias,
        "institutos": institutos,
        "atualizado_em": date.today().strftime("%d/%m/%Y"),
    }


def get_dados_regionais() -> dict:
    """Retorna percentuais mais recentes por candidato e UF da tabela pesquisas_regionais."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT uf, candidato, percentual, data_pesquisa "
                "FROM pesquisas_regionais ORDER BY uf, candidato, data_pesquisa DESC"
            ).fetchall()
    except Exception:
        return {"candidatos": [], "estados": {}}

    estados: dict = {}
    seen: set = set()
    candidato_totals: dict = {}

    for row in rows:
        key = (row["uf"], row["candidato"])
        if key in seen:
            continue
        seen.add(key)
        uf = row["uf"]
        if uf not in estados:
            estados[uf] = {}
        estados[uf][row["candidato"]] = {
            "percentual": row["percentual"],
            "data": row["data_pesquisa"],
        }
        candidato_totals.setdefault(row["candidato"], []).append(row["percentual"])

    candidatos = sorted(
        candidato_totals,
        key=lambda c: sum(candidato_totals[c]) / len(candidato_totals[c]),
        reverse=True,
    )

    return {"candidatos": candidatos, "estados": estados}


def get_top_candidatos(cargo: str, n: int = 3) -> list[str]:
    """Retorna os n candidatos com maior percentual médio para o cargo."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT i.candidato, AVG(i.percentual) AS media
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            WHERE p.cargo = ?
            GROUP BY i.candidato
            ORDER BY media DESC
        """, (cargo,)).fetchall()
    candidatos = [r['candidato'] for r in rows if _e_candidato(r['candidato'])]
    return candidatos[:n]


def get_historico_multi(candidatos: list[str], cargo: str, tipo: str = 'estimulada') -> list[dict]:
    """Retorna série histórica de múltiplos candidatos para o cargo.

    Cada ponto inclui `margem_erro` para a renderização da banda de incerteza.
    tipo='estimulada' inclui registros legados sem tipo (NULL); 'espontanea' é exato.
    """
    if tipo == 'espontanea':
        filtro_tipo = "i.tipo = 'espontanea'"
    else:
        filtro_tipo = "(i.tipo = 'estimulada' OR i.tipo IS NULL)"
    candidatos = [c for c in candidatos if _e_candidato(c)]
    if not candidatos:
        return []

    placeholders = ",".join("?" * len(candidatos))
    with get_db() as conn:
        rows = conn.execute(f"""
            SELECT i.candidato, p.data_pesquisa AS data, i.percentual, p.margem_erro, inst.nome AS instituto
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            JOIN institutos inst ON p.instituto_id = inst.id
            WHERE i.candidato IN ({placeholders}) AND p.cargo = ?
            AND {filtro_tipo}
            ORDER BY i.candidato, p.data_pesquisa ASC
        """, (*candidatos, cargo)).fetchall()

    por_candidato: dict[str, list] = {c: [] for c in candidatos}
    for r in rows:
        por_candidato[r["candidato"]].append({
            "data": r["data"], "percentual": r["percentual"],
            "margem_erro": r["margem_erro"], "instituto": r["instituto"]
        })

    series = []
    for idx, candidato in enumerate(candidatos):
        cor = get_cores_candidatos().get(candidato, _FALLBACK_COLORS[idx % len(_FALLBACK_COLORS)])
        series.append({
            "candidato": candidato,
            "cor": cor,
            "dados": por_candidato[candidato],
        })
    return series


def get_historico_candidato(candidato: str) -> list[dict]:
    """Retorna a evolução temporal (série histórica) das intenções de voto de um candidato."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.data_pesquisa AS data, int.percentual, inst.nome AS instituto
            FROM intencoes int
            JOIN pesquisas p ON int.pesquisa_id = p.id
            JOIN institutos inst ON p.instituto_id = inst.id
            WHERE int.candidato = ?
            ORDER BY p.data_pesquisa ASC, p.id ASC
        """, (candidato,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_pesquisa_por_id(pesquisa_id: int) -> dict | None:
    """Retorna o detalhe completo de uma pesquisa (metodologia + intenções), ou None se não existir."""
    with get_db() as conn:
        pesquisa_row = conn.execute("""
            SELECT p.id, p.cargo, p.data_pesquisa, p.data_publicacao,
                   p.tamanho_amostra, p.margem_erro, p.contratante,
                   p.registro_tse, p.fonte_url,
                   inst.nome AS instituto
            FROM pesquisas p
            JOIN institutos inst ON p.instituto_id = inst.id
            WHERE p.id = ?
        """, (pesquisa_id,)).fetchone()

        if pesquisa_row is None:
            return None

        intencoes_rows = conn.execute("""
            SELECT candidato, partido, percentual, tipo
            FROM intencoes
            WHERE pesquisa_id = ?
            ORDER BY percentual DESC
        """, (pesquisa_id,)).fetchall()

    pesquisa = dict(pesquisa_row)
    pesquisa["intencoes"] = [dict(row) for row in intencoes_rows]
    return pesquisa


def get_institutos_com_totais() -> list[dict]:
    """Retorna a lista de institutos cadastrados junto com a contagem total de pesquisas e a data da última."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT inst.nome, COUNT(p.id) AS total, MAX(p.data_pesquisa) AS ultima_coleta
            FROM institutos inst
            LEFT JOIN pesquisas p ON p.instituto_id = inst.id
            GROUP BY inst.id, inst.nome
            ORDER BY total DESC, inst.nome ASC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()
