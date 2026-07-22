"""KPIs analíticos avançados e visão geral consolidada."""
from datetime import date, timedelta
from statistics import mean

from db.core import get_conn, get_db
from db.pesquisas import get_media_agregada


def _media_intervalo(pontos: list[tuple[str, float]], inicio: str, fim: str = None):
    """Média dos percentuais com data_pesquisa em [inicio, fim) — ou
    [inicio, ...] se fim for None. Retorna None se não houver pontos no
    intervalo (equivalente a um AVG(...) SQL retornando NULL)."""
    if fim:
        vals = [pct for dt, pct in pontos if inicio <= dt < fim]
    else:
        vals = [pct for dt, pct in pontos if dt >= inicio]
    return mean(vals) if vals else None


def get_kpis_avancados(cargo: str) -> dict:
    """Calcula 6 KPIs analíticos avançados com base na média agregada dos últimos 30 dias."""
    from statistics import stdev
    hoje = date.today()
    d15 = (hoje - timedelta(days=15)).isoformat()
    d30 = (hoje - timedelta(days=30)).isoformat()
    d60 = (hoje - timedelta(days=60)).isoformat()

    media_data = get_media_agregada(cargo, dias=30)
    candidatos = media_data.get("candidatos", [])

    # Uma única passada: todas as intenções (estimulada/NULL) da janela de 60
    # dias, agrupadas por candidato, para alimentar tendencia_aceleracao,
    # campo_minado e volatilidade sem uma query por candidato.
    with get_db() as conn:
        rows_janela = conn.execute(
            "SELECT i.candidato, p.data_pesquisa, i.percentual FROM intencoes i "
            "JOIN pesquisas p ON i.pesquisa_id = p.id "
            "WHERE p.cargo=? AND p.data_pesquisa>=? "
            "AND (i.tipo='estimulada' OR i.tipo IS NULL) "
            "ORDER BY i.candidato, p.data_pesquisa",
            (cargo, d60)
        ).fetchall()
    por_candidato: dict[str, list[tuple[str, float]]] = {}
    for r in rows_janela:
        por_candidato.setdefault(r["candidato"], []).append((r["data_pesquisa"], r["percentual"]))

    # --- margem_lideranca ---
    if len(candidatos) >= 2:
        p1, p2 = candidatos[0], candidatos[1]
        margem = round(p1["media"] - p2["media"], 1)
        if margem < 5:
            clf = "empate_tecnico"
        elif margem <= 10:
            clf = "lideranca_moderada"
        else:
            clf = "lideranca_confortavel"
        margem_lideranca = {
            "primeiro": p1["candidato"],
            "segundo": p2["candidato"],
            "percentual_primeiro": p1["media"],
            "percentual_segundo": p2["media"],
            "margem": margem,
            "classificacao": clf,
        }
    else:
        margem_lideranca = {}

    # --- probabilidade_segundo_turno ---
    lider_pct = candidatos[0]["media"] if candidatos else 0.0
    probabilidade_segundo_turno = {
        "provavel": lider_pct < 50,
        "lider_percentual": lider_pct,
        "explicacao": "Nenhum candidato supera 50%" if lider_pct < 50 else f"Líder com {lider_pct}% pode vencer no 1º turno",
    }

    # --- tendencia_aceleracao (top 3) ---
    top3_nomes = [c["candidato"] for c in candidatos[:3]]
    tendencia_aceleracao = []
    for nome in top3_nomes:
        pontos = por_candidato.get(nome, [])
        m_rec15 = _media_intervalo(pontos, d15) or 0.0
        m_ant15 = _media_intervalo(pontos, d30, d15) or 0.0
        m_rec30 = _media_intervalo(pontos, d30) or 0.0
        m_ant30 = _media_intervalo(pontos, d60, d30) or 0.0

        t15 = round(m_rec15 - m_ant15, 1)
        t30 = round(m_rec30 - m_ant30, 1)

        if abs(t15) < 0.5 and abs(t30) < 0.5:
            acel = "estavel"
        elif t15 >= 0 and t30 >= 0:
            acel = "acelerando_alta" if t15 >= t30 else "desacelerando_alta"
        elif t15 < 0 and t30 < 0:
            acel = "acelerando_queda" if t15 <= t30 else "desacelerando_queda"
        elif t15 > 0:
            acel = "acelerando_alta"
        else:
            acel = "acelerando_queda"

        tendencia_aceleracao.append({
            "candidato": nome,
            "tendencia_15d": t15,
            "tendencia_30d": t30,
            "aceleracao": acel,
        })

    # --- campo_minado (candidatos fora do top 2, entre 2% e 15%) ---
    campo_minado = []
    for c in candidatos[2:]:
        if not (2.0 <= c["media"] <= 15.0):
            continue
        pontos = por_candidato.get(c["candidato"], [])
        m_rec = _media_intervalo(pontos, d15)
        m_ant = _media_intervalo(pontos, d30, d15)
        pct_atual = round(m_rec if m_rec is not None else c["media"], 1)
        pct_ant = m_ant
        if pct_ant and pct_ant > 0:
            cresc = round((pct_atual - pct_ant) / pct_ant * 100, 1)
        else:
            cresc = 0.0
        campo_minado.append({
            "candidato": c["candidato"],
            "percentual_atual": pct_atual,
            "percentual_anterior": round(pct_ant, 1) if pct_ant else pct_atual,
            "crescimento_relativo": cresc,
            "em_ascensao": cresc > 20,
        })
    campo_minado.sort(key=lambda x: x["crescimento_relativo"], reverse=True)
    campo_minado = campo_minado[:3]

    # --- concentracao_voto ---
    if len(candidatos) >= 2:
        top2_soma = round(candidatos[0]["media"] + candidatos[1]["media"], 1)
        if top2_soma > 70:
            conc_clf = "bipolar"
        elif top2_soma >= 55:
            conc_clf = "moderado"
        else:
            conc_clf = "fragmentado"
        concentracao_voto = {
            "top2_soma": top2_soma,
            "classificacao": conc_clf,
            "terceira_via_possivel": top2_soma < 65,
        }
    else:
        concentracao_voto = {"top2_soma": 0.0, "classificacao": "fragmentado", "terceira_via_possivel": True}

    # --- volatilidade (top 3) ---
    vol_candidatos = []
    for c in candidatos[:3]:
        pontos = por_candidato.get(c["candidato"], [])
        pcts = [pct for dt, pct in pontos if dt >= d30]
        dp = round(stdev(pcts), 1) if len(pcts) >= 2 else 0.0
        vol_candidatos.append({
            "candidato": c["candidato"],
            "desvio_padrao": dp,
            "classificacao": "baixa" if dp < 2 else ("media" if dp <= 4 else "alta"),
        })

    media_dp = mean([v["desvio_padrao"] for v in vol_candidatos]) if vol_candidatos else 0.0
    cenario_geral = "estavel" if media_dp < 2 else ("moderado" if media_dp <= 4 else "volatil")

    return {
        "margem_lideranca": margem_lideranca,
        "probabilidade_segundo_turno": probabilidade_segundo_turno,
        "tendencia_aceleracao": tendencia_aceleracao,
        "campo_minado": campo_minado,
        "concentracao_voto": concentracao_voto,
        "volatilidade": {"candidatos": vol_candidatos, "cenario_geral": cenario_geral},
    }


def get_visao_geral() -> dict:
    """Retorna dados estatísticos e tendências consolidadas para a visão geral."""
    import datetime
    conn = get_conn()
    try:
        cursor = conn.cursor()

        # 1. Total de pesquisas
        cursor.execute("SELECT COUNT(*) FROM pesquisas")
        total_pesquisas = cursor.fetchone()[0]

        # 2. Institutos ativos (com pesquisas nos últimos 30 dias)
        cursor.execute("""
            SELECT COUNT(DISTINCT instituto_id) FROM pesquisas
            WHERE data_pesquisa >= date('now', 'localtime', '-30 days')
        """)
        institutos_ativos = cursor.fetchone()[0]

        # 3. Última atualização (data da pesquisa mais recente)
        cursor.execute("SELECT MAX(data_pesquisa) FROM pesquisas")
        max_data = cursor.fetchone()[0]

        ultima_atualizacao = None
        dias_desde_ultima = None
        if max_data:
            try:
                dt = datetime.datetime.strptime(max_data, "%Y-%m-%d").date()
                today = datetime.date.today()
                dias_desde_ultima = max(0, (today - dt).days)
                ultima_atualizacao = dt.strftime("%d/%m/%Y")
            except Exception:
                pass

        # 4. Líder Presidente
        cursor.execute("""
            SELECT inst.nome AS instituto, int.candidato, int.percentual, p.data_pesquisa
            FROM pesquisas p
            JOIN institutos inst ON p.instituto_id = inst.id
            JOIN intencoes int ON int.pesquisa_id = p.id
            WHERE p.cargo = 'presidente' AND inst.agregar = 1 AND p.id = (
                SELECT p2.id FROM pesquisas p2
                JOIN institutos inst2 ON p2.instituto_id = inst2.id
                WHERE p2.cargo = 'presidente' AND inst2.agregar = 1
                ORDER BY p2.data_pesquisa DESC, p2.id DESC
                LIMIT 1
            )
            ORDER BY int.percentual DESC
            LIMIT 1
        """)
        row_pres = cursor.fetchone()
        lider_pres = None
        if row_pres:
            try:
                dt_pres = datetime.datetime.strptime(row_pres['data_pesquisa'], "%Y-%m-%d").date()
                dt_pres_str = dt_pres.strftime("%d/%m/%Y")
            except Exception:
                dt_pres_str = row_pres['data_pesquisa']
            lider_pres = {
                "candidato": row_pres['candidato'],
                "percentual": row_pres['percentual'],
                "instituto": row_pres['instituto'],
                "data": dt_pres_str
            }

        # 5. Líder Governador RJ
        cursor.execute("""
            SELECT inst.nome AS instituto, int.candidato, int.percentual, p.data_pesquisa
            FROM pesquisas p
            JOIN institutos inst ON p.instituto_id = inst.id
            JOIN intencoes int ON int.pesquisa_id = p.id
            WHERE p.cargo = 'governador_rj' AND inst.agregar = 1 AND p.id = (
                SELECT p2.id FROM pesquisas p2
                JOIN institutos inst2 ON p2.instituto_id = inst2.id
                WHERE p2.cargo = 'governador_rj' AND inst2.agregar = 1
                ORDER BY p2.data_pesquisa DESC, p2.id DESC
                LIMIT 1
            )
            ORDER BY int.percentual DESC
            LIMIT 1
        """)
        row_gov = cursor.fetchone()
        lider_gov = None
        if row_gov:
            try:
                dt_gov = datetime.datetime.strptime(row_gov['data_pesquisa'], "%Y-%m-%d").date()
                dt_gov_str = dt_gov.strftime("%d/%m/%Y")
            except Exception:
                dt_gov_str = row_gov['data_pesquisa']
            lider_gov = {
                "candidato": row_gov['candidato'],
                "percentual": row_gov['percentual'],
                "instituto": row_gov['instituto'],
                "data": dt_gov_str
            }

        # 6. Tendências
        cursor.execute("""
            SELECT int.candidato
            FROM pesquisas p
            JOIN intencoes int ON int.pesquisa_id = p.id
            WHERE p.cargo = 'presidente' AND p.id = (
                SELECT p2.id FROM pesquisas p2
                JOIN institutos inst2 ON p2.instituto_id = inst2.id
                WHERE p2.cargo = 'presidente' AND inst2.agregar = 1
                ORDER BY p2.data_pesquisa DESC, p2.id DESC
                LIMIT 1
            )
            ORDER BY int.percentual DESC
        """)
        rows_cand = cursor.fetchall()
        top_candidates = []
        for r in rows_cand:
            c_name = r['candidato']
            c_name_lower = c_name.lower()
            if any(x in c_name_lower for x in ['outros', 'nulo', 'branco', 'indeciso', 'não sabe', 'nenhum', '—']):
                continue
            top_candidates.append(c_name)
            if len(top_candidates) == 3:
                break

        tendencias = []
        for cand in top_candidates:
            cursor.execute("""
                SELECT i.percentual, p.data_pesquisa, p.instituto_id
                FROM intencoes i
                JOIN pesquisas p ON i.pesquisa_id = p.id
                WHERE i.candidato = ? AND p.cargo = 'presidente'
                AND p.instituto_id = (
                    SELECT p2.instituto_id FROM intencoes i2
                    JOIN pesquisas p2 ON i2.pesquisa_id = p2.id
                    WHERE i2.candidato = ? AND p2.cargo = 'presidente'
                    ORDER BY p2.data_pesquisa DESC, p2.id DESC LIMIT 1
                )
                ORDER BY p.data_pesquisa DESC, p.id DESC
                LIMIT 2
            """, (cand, cand))
            hist_rows = cursor.fetchall()
            if not hist_rows:
                continue

            percentual_atual = hist_rows[0]['percentual']
            if len(hist_rows) > 1:
                percentual_anterior = hist_rows[1]['percentual']
                variacao = percentual_atual - percentual_anterior
            else:
                percentual_anterior = percentual_atual
                variacao = 0.0

            if variacao > 0:
                direcao = "up"
            elif variacao < 0:
                direcao = "down"
            else:
                direcao = "flat"

            tendencias.append({
                "candidato": cand,
                "cargo": "presidente",
                "percentual_atual": percentual_atual,
                "percentual_anterior": percentual_anterior,
                "variacao": round(variacao, 2),
                "direcao": direcao
            })

        return {
            "kpis": {
                "total_pesquisas": total_pesquisas,
                "institutos_ativos": institutos_ativos,
                "ultima_atualizacao": ultima_atualizacao,
                "dias_desde_ultima": dias_desde_ultima
            },
            "lider_presidente": lider_pres,
            "lider_governador": lider_gov,
            "tendencias": tendencias
        }
    finally:
        conn.close()
