"""Análises de integridade estatística sobre o banco de pesquisas.

Detecta INDÍCIOS de anomalia (dígito final, subdispersão, z-score vs consenso,
divergência de amostra vs registro TSE) e categoriza institutos e pesquisas.
Nenhum resultado aqui é prova de irregularidade — a linguagem de saída é
sempre de indício estatístico, e a página /integridade repete o disclaimer.

Diferente das consultas de curadoria, este módulo analisa TODOS os institutos
(inclusive agregar = 0): auditoria quer o oposto do filtro de aprovação.
"""
from datetime import date, timedelta
from statistics import mean

from db.core import get_db
from db.estatistica import chi2_sf, teste_digito_final, teste_subdispersao

# Mesmo filtro de candidato de get_house_effects (db/pesquisas.py) — copiado,
# não refatorado: aquela função tem contrato congelado em tests/test_agregacao.py.
_FILTRO_CANDIDATO = """
    AND (i.tipo = 'estimulada' OR i.tipo IS NULL)
    AND (c.status IS NULL OR c.status = 'ativo')
    AND LOWER(i.candidato) NOT LIKE '%outros%'
    AND LOWER(i.candidato) NOT LIKE '%nulos%'
    AND LOWER(i.candidato) NOT LIKE '%brancos%'
    AND LOWER(i.candidato) NOT LIKE '%indecisos%'
    AND LOWER(i.candidato) NOT LIKE '%não sabe%'
    AND LOWER(i.candidato) NOT LIKE '%não respondeu%'
"""

LIMIAR_DIVERGENCIA_TSE = 0.10  # 10% entre amostra realizada e registrada


def analise_digito_final(cargo: str | None = None, dias: int = 365) -> list[dict]:
    """Distribuição do último dígito decimal de TODOS os percentuais publicados
    por instituto (qualquer tipo/candidato — o hábito de arredondar aparece em
    qualquer número divulgado, e o teste precisa de volume)."""
    data_limite = (date.today() - timedelta(days=dias)).isoformat()
    sql = """
        SELECT inst.nome AS instituto, i.percentual
        FROM intencoes i
        JOIN pesquisas p ON i.pesquisa_id = p.id
        JOIN institutos inst ON p.instituto_id = inst.id
        WHERE p.data_pesquisa >= ?
    """
    params: list = [data_limite]
    if cargo:
        sql += " AND p.cargo = ?"
        params.append(cargo)
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    por_instituto: dict[str, list] = {}
    for r in rows:
        por_instituto.setdefault(r['instituto'], []).append(r['percentual'])

    return [
        {"instituto": inst, "n": len(valores), "resultado": teste_digito_final(valores)}
        for inst, valores in sorted(por_instituto.items())
    ]


def analise_subdispersao(cargo: str = 'presidente', dias: int = 365) -> list[dict]:
    """Séries (instituto, candidato) com >= 5 pesquisas: variância baixa demais
    vs. a esperada pela binomial = "bom demais para ser verdade". As estatísticas
    qui-quadrado das séries de um instituto são somadas (χ² é aditiva) num único
    p-valor por instituto."""
    data_limite = (date.today() - timedelta(days=dias)).isoformat()
    with get_db() as conn:
        rows = conn.execute(f"""
            SELECT inst.nome AS instituto, i.candidato, i.percentual, p.tamanho_amostra
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            JOIN institutos inst ON p.instituto_id = inst.id
            LEFT JOIN candidatos c ON c.nome_canonico = i.candidato
            WHERE p.cargo = ? AND p.data_pesquisa >= ?
            {_FILTRO_CANDIDATO}
        """, (cargo, data_limite)).fetchall()

    series: dict[tuple, list] = {}
    for r in rows:
        series.setdefault((r['instituto'], r['candidato']), []).append(
            (r['percentual'], r['tamanho_amostra']))

    acumulado: dict[str, dict] = {}
    for (inst, _cand), pontos in series.items():
        resultado = teste_subdispersao([p for p, _ in pontos], [n for _, n in pontos])
        if resultado is None:
            continue
        acc = acumulado.setdefault(inst, {"estatistica": 0.0, "gl": 0, "series": 0})
        acc["estatistica"] += resultado["estatistica"]
        acc["gl"] += resultado["gl"]
        acc["series"] += 1

    return [
        {
            "instituto": inst,
            "estatistica": round(acc["estatistica"], 3),
            "gl": acc["gl"],
            "series": acc["series"],
            "p_subdispersao": round(1.0 - chi2_sf(acc["estatistica"], acc["gl"]), 4),
        }
        for inst, acc in sorted(acumulado.items())
    ]


def _medias_por_candidato_instituto(cargo: str, dias: int) -> dict:
    """pcts[candidato][instituto] = [(percentual, amostra), ...] na janela."""
    data_limite = (date.today() - timedelta(days=dias)).isoformat()
    with get_db() as conn:
        rows = conn.execute(f"""
            SELECT inst.nome AS instituto, i.candidato, i.percentual, p.tamanho_amostra
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            JOIN institutos inst ON p.instituto_id = inst.id
            LEFT JOIN candidatos c ON c.nome_canonico = i.candidato
            WHERE p.cargo = ? AND p.data_pesquisa >= ?
            {_FILTRO_CANDIDATO}
        """, (cargo, data_limite)).fetchall()
    pcts: dict[str, dict[str, list]] = {}
    for r in rows:
        pcts.setdefault(r['candidato'], {}).setdefault(r['instituto'], []).append(
            (r['percentual'], r['tamanho_amostra']))
    return pcts


def _var_media_binomial(pontos: list) -> float:
    """Variância (em fração²) da MÉDIA de uma lista [(pct, n)] sob a binomial:
    mean(p(1−p)/n) / k."""
    k = len(pontos)
    variancias = [max(p, 0.5) / 100 * (1 - min(p, 99.5) / 100) / max(n, 1) for p, n in pontos]
    return mean(variancias) / k


def analise_zscore_consenso(cargo: str = 'presidente', dias: int = 90) -> list[dict]:
    """House effect normalizado: z = (média_inst − média_demais) / erro-padrão
    combinado (variância binomial das médias). |z| > 3 = outlier, > 2 = atenção.

    Mesmos thresholds de contagem de get_house_effects (>= 3 institutos por
    candidato, >= 2 pesquisas por instituto)."""
    pcts = _medias_por_candidato_instituto(cargo, dias)
    saida = []
    for candidato, por_inst in pcts.items():
        if len(por_inst) < 3:
            continue
        medias = {inst: mean(p for p, _ in pontos) for inst, pontos in por_inst.items()}
        for inst, pontos in por_inst.items():
            if len(pontos) < 2:
                continue
            demais = [i2 for i2 in por_inst if i2 != inst]
            media_demais = mean(medias[i2] for i2 in demais)
            var_inst = _var_media_binomial(pontos)
            # variância da média-das-médias dos demais institutos
            var_demais = sum(_var_media_binomial(por_inst[i2]) for i2 in demais) / len(demais) ** 2
            ep = (var_inst + var_demais) ** 0.5 * 100  # de fração para pontos percentuais
            if ep <= 0:
                continue
            saida.append({
                "instituto": inst,
                "candidato": candidato,
                "media_instituto": round(medias[inst], 1),
                "media_demais": round(media_demais, 1),
                "z": round((medias[inst] - media_demais) / ep, 2),
                "n_pesquisas": len(pontos),
            })
    saida.sort(key=lambda e: -abs(e["z"]))
    return saida


def analise_divergencia_tse() -> list[dict]:
    """Amostra realizada (release) vs. registrada no TSE, para pesquisas ligadas.
    Divergência legítima existe (o TSE guarda a amostra planejada) — por isso o
    limiar de 10% e a listagem completa para transparência."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT p.id AS pesquisa_id, inst.nome AS instituto, p.cargo,
                   p.data_pesquisa, p.tamanho_amostra, t.qt_entrevistado, t.protocolo
            FROM pesquisas p
            JOIN pesquisas_tse t ON t.pesquisa_id = p.id
            JOIN institutos inst ON p.instituto_id = inst.id
            WHERE t.qt_entrevistado IS NOT NULL AND t.qt_entrevistado > 0
        """).fetchall()
    saida = []
    for r in rows:
        divergencia = abs(r['tamanho_amostra'] - r['qt_entrevistado']) / r['qt_entrevistado']
        saida.append({
            "pesquisa_id": r['pesquisa_id'],
            "instituto": r['instituto'],
            "cargo": r['cargo'],
            "data_pesquisa": r['data_pesquisa'],
            "amostra_realizada": r['tamanho_amostra'],
            "amostra_registrada": r['qt_entrevistado'],
            "protocolo": r['protocolo'],
            "divergencia_pct": round(divergencia * 100, 1),
            "divergente": divergencia > LIMIAR_DIVERGENCIA_TSE,
        })
    saida.sort(key=lambda e: -e["divergencia_pct"])
    return saida


def _pontos(p_valor: float | None) -> int:
    """Pontuação de um teste: p<0.01 → 2, p<0.05 → 1, senão 0."""
    if p_valor is None:
        return 0
    if p_valor < 0.01:
        return 2
    if p_valor < 0.05:
        return 1
    return 0


def _pontos_z(z_abs: float | None) -> int:
    if z_abs is None:
        return 0
    if z_abs > 3:
        return 2
    if z_abs > 2:
        return 1
    return 0


def _categoria(score: int) -> dict:
    if score == 0:
        return {"categoria": "sem_indicios", "categoria_label": "sem indícios"}
    if score <= 2:
        return {"categoria": "atencao", "categoria_label": "atenção"}
    return {"categoria": "anomalo", "categoria_label": "anômalo"}


def get_integridade_geral(cargo: str = 'presidente', dias_z: int = 90) -> dict:
    """Orquestra as quatro análises e monta score/categoria por instituto e por
    pesquisa. Dígito final e subdispersão usam janela de 365 dias (precisam de
    volume); z-score usa `dias_z` (consenso é conceito de curto prazo)."""
    digito = analise_digito_final(cargo=None, dias=365)  # todos os cargos: mais N
    subdisp = analise_subdispersao(cargo=cargo, dias=365)
    zscores = analise_zscore_consenso(cargo=cargo, dias=dias_z)
    tse = analise_divergencia_tse()

    digito_por_inst = {d["instituto"]: d for d in digito}
    subdisp_por_inst = {s["instituto"]: s for s in subdisp}
    max_z_por_inst: dict[str, float] = {}
    for e in zscores:
        atual = max_z_por_inst.get(e["instituto"], 0.0)
        max_z_por_inst[e["instituto"]] = max(atual, abs(e["z"]))
    tse_divergentes_por_inst: dict[str, int] = {}
    for t in tse:
        if t["divergente"]:
            tse_divergentes_por_inst[t["instituto"]] = \
                tse_divergentes_por_inst.get(t["instituto"], 0) + 1

    with get_db() as conn:
        inst_rows = conn.execute(
            "SELECT nome, agregar FROM institutos ORDER BY nome").fetchall()
    agregar_por_inst = {r['nome']: r['agregar'] for r in inst_rows}

    nomes = sorted(set(digito_por_inst) | set(subdisp_por_inst)
                   | set(max_z_por_inst) | set(tse_divergentes_por_inst))
    institutos = []
    for nome in nomes:
        d = digito_por_inst.get(nome)
        s = subdisp_por_inst.get(nome)
        max_z = max_z_por_inst.get(nome)
        n_tse = min(tse_divergentes_por_inst.get(nome, 0), 2)  # cap 2

        p_digito = d["resultado"]["p_valor"] if d and d["resultado"] else None
        p_subdisp = s["p_subdispersao"] if s else None
        score = _pontos(p_digito) + _pontos(p_subdisp) + _pontos_z(max_z) + n_tse

        institutos.append({
            "instituto": nome,
            "agregar": agregar_por_inst.get(nome),
            "score": score,
            **_categoria(score),
            "testes": {
                "digito_final": d["resultado"] if d and d["resultado"]
                else {"status": "dados_insuficientes", "n": d["n"] if d else 0},
                "subdispersao": s if s else {"status": "dados_insuficientes"},
                "zscore_consenso": {"max_z": max_z} if max_z is not None
                else {"status": "dados_insuficientes"},
                "divergencia_tse": {"pesquisas_divergentes": n_tse},
            },
        })

    pesquisas = _score_pesquisas(cargo, dias_z, tse)

    return {
        "cargo": cargo,
        "janela_dias_z": dias_z,
        "institutos": institutos,
        "pesquisas": pesquisas,
        "zscores": zscores,
        "divergencias_tse": tse,
        "disclaimer": ("Indícios estatísticos não constituem prova de fraude ou "
                       "irregularidade. Os testes medem improbabilidade sob amostragem "
                       "aleatória simples e podem ser disparados por metodologia "
                       "legítima (cotas, arredondamento editorial, tracking)."),
        "atualizado_em": date.today().strftime("%d/%m/%Y"),
    }


def _score_pesquisas(cargo: str, dias: int, tse: list[dict]) -> list[dict]:
    """Score por pesquisa individual na janela: só os testes que fazem sentido
    com 1 observação por candidato — desvio máximo vs. consenso dos DEMAIS
    institutos (z da pesquisa isolada) + divergência TSE. Dígito final e
    subdispersão não têm N numa pesquisa isolada (ficam no nível instituto)."""
    pcts = _medias_por_candidato_instituto(cargo, dias)
    consenso: dict[str, dict[str, float]] = {}  # consenso[cand][inst_excluido]
    for cand, por_inst in pcts.items():
        if len(por_inst) < 3:
            continue
        medias = {inst: mean(p for p, _ in pontos) for inst, pontos in por_inst.items()}
        consenso[cand] = {
            inst: mean(m for i2, m in medias.items() if i2 != inst)
            for inst in por_inst
        }

    tse_por_pesquisa = {t["pesquisa_id"]: t for t in tse}
    data_limite = (date.today() - timedelta(days=dias)).isoformat()
    with get_db() as conn:
        rows = conn.execute(f"""
            SELECT p.id, inst.nome AS instituto, p.data_pesquisa, p.tamanho_amostra,
                   i.candidato, i.percentual
            FROM pesquisas p
            JOIN institutos inst ON p.instituto_id = inst.id
            JOIN intencoes i ON i.pesquisa_id = p.id
            LEFT JOIN candidatos c ON c.nome_canonico = i.candidato
            WHERE p.cargo = ? AND p.data_pesquisa >= ?
            {_FILTRO_CANDIDATO}
            ORDER BY p.data_pesquisa DESC
        """, (cargo, data_limite)).fetchall()

    por_pesquisa: dict[int, dict] = {}
    for r in rows:
        info = por_pesquisa.setdefault(r['id'], {
            "id": r['id'], "instituto": r['instituto'],
            "data_pesquisa": r['data_pesquisa'], "max_z": None,
        })
        base = consenso.get(r['candidato'], {}).get(r['instituto'])
        if base is None:
            continue
        p = max(min(base, 99.5), 0.5) / 100
        ep = (p * (1 - p) / max(r['tamanho_amostra'], 1)) ** 0.5 * 100
        z = abs(r['percentual'] - base) / ep
        if info["max_z"] is None or z > info["max_z"]:
            info["max_z"] = round(z, 2)

    saida = []
    for info in por_pesquisa.values():
        t = tse_por_pesquisa.get(info["id"])
        divergente_tse = bool(t and t["divergente"])
        score = _pontos_z(info["max_z"]) + (1 if divergente_tse else 0)
        saida.append({
            **info,
            "divergencia_tse": t["divergencia_pct"] if t else None,
            "score": score,
            **_categoria(score),
        })
    saida.sort(key=lambda e: e["data_pesquisa"], reverse=True)
    return saida
