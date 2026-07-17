"""Motor de Monte Carlo (genérico, qualquer cargo) + 2º turno real/simulado.

Cluster internamente interdependente — os helpers `_`-prefixados alimentam
uns aos outros e os poucos wrappers públicos (get_simulacao_monte_carlo,
get_simulacao_segundo_turno, simular_monte_carlo_cargo). Movido como um
bloco só, sem separar em módulos menores.
"""
import sqlite3
from datetime import date, timedelta

from db.core import get_db
from db.candidatos import get_candidatos_por_espectro
from db.pesquisas import get_media_agregada

_BUCKET_INDECISOS = "Outros/Nulos/Brancos/Indecisos"


def fator_volatilidade(pct_pode_mudar_voto: float | None) -> float:
    """Fator de inflação do sigma de um candidato quando o instituto divulga
    o "% de eleitores que podem mudar de voto" (coluna pesquisas.pct_pode_mudar_voto).

    Heurística linear: cada ponto percentual de volatilidade divulgada soma
    1% ao sigma (ex.: 30% de eleitores voláteis → sigma 1.30x). Quando o dado
    não foi divulgado (None), o fator é neutro (1.0) — nunca inferimos ou
    estimamos essa métrica.
    """
    if pct_pode_mudar_voto is None:
        return 1.0
    return 1.0 + max(0.0, pct_pode_mudar_voto) / 100.0


def _redistribuir_indecisos(simulado: dict, pct_indecisos: float) -> dict:
    """Redistribui proporcionalmente o bucket "Outros/Nulos/Brancos/Indecisos"
    entre os candidatos reais de uma rodada simulada, com base no share
    relativo de cada um. `pct_indecisos` é a média do bucket para o cargo
    (0.0 se não houver esse dado — nesse caso é no-op)."""
    if pct_indecisos <= 0:
        return simulado
    total = sum(simulado.values())
    if total <= 0:
        return simulado
    return {nome: pct + pct_indecisos * (pct / total) for nome, pct in simulado.items()}


def prob_vitoria_primeiro_turno(candidato: str, runs: list[dict]) -> float:
    """% de runs (já com o bucket de indecisos redistribuído) em que o share
    do candidato ultrapassa 50% dos votos válidos do cenário — i.e., vitória
    em 1º turno sem precisar de confronto direto par a par. Calculada em
    cima do array de runs já retido pelo motor, sem rodar nova simulação."""
    if not runs:
        return 0.0
    vitorias = 0
    for run in runs:
        total = sum(run.values())
        if total > 0 and run.get(candidato, 0) / total > 0.5:
            vitorias += 1
    return round(vitorias / len(runs) * 100, 1)


def _margens_por_candidato(cargo: str) -> dict:
    """Margem de erro da pesquisa mais recente de cada candidato do cargo."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT i.candidato, p.margem_erro
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            WHERE p.cargo = ? AND p.margem_erro > 0
            AND (i.tipo = 'estimulada' OR i.tipo IS NULL)
            ORDER BY p.data_pesquisa DESC
        """, (cargo,)).fetchall()
    margens = {}
    for candidato, margem in rows:
        if candidato not in margens:
            margens[candidato] = margem
    return margens


def _pct_mudar_voto_recente(cargo: str) -> float | None:
    """pct_pode_mudar_voto mais recente divulgado pra esse cargo (dado é do
    poll inteiro, não por candidato — quando presente, é aplicado a todos os
    candidatos do cenário). None se nenhuma pesquisa recente tiver esse dado."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT pct_pode_mudar_voto FROM pesquisas
            WHERE cargo = ? AND pct_pode_mudar_voto IS NOT NULL
            ORDER BY data_pesquisa DESC, id DESC
            LIMIT 1
        """, (cargo,)).fetchone()
    return row["pct_pode_mudar_voto"] if row else None


def _pct_indecisos_medio(cargo: str, dias: int = 30) -> float:
    """Média simples do bucket "Outros/Nulos/Brancos/Indecisos" no cargo, nos
    últimos `dias` dias. 0.0 se não houver esse bucket nas pesquisas (caso do
    cargo 'presidente' hoje — nenhum instituto reporta essa linha)."""
    data_limite = (date.today() - timedelta(days=dias)).isoformat()
    with get_db() as conn:
        row = conn.execute("""
            SELECT AVG(i.percentual) AS media
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            WHERE p.cargo = ? AND p.data_pesquisa >= ? AND i.candidato = ?
        """, (cargo, data_limite, _BUCKET_INDECISOS)).fetchone()
    return row["media"] if row and row["media"] is not None else 0.0


def _simular_cenario(
    candidatos: list[dict],
    margens: dict,
    nome_a: str,
    nome_b: str,
    n_simulacoes: int = 10000,
    fator_sigma: float = 2.0,
    sigma_minimo: float = 6.0,
    margem_default: float = 2.0,
    pct_indecisos: float = 0.0,
    pct_mudar_voto: dict | None = None,
    mu_override: dict | None = None,
) -> dict:
    """Motor genérico de Monte Carlo para um par de candidatos (nome_a vs
    nome_b) dentro de um cenário multi-candidato — funciona pra qualquer
    cargo, não só presidencial.

    `candidatos` é a lista de dicts {'candidato': nome, 'media': pct} (ex.:
    retorno de get_media_agregada). `mu_override` mapeia nome de candidato →
    mu preferencial (0.0-1.0) no split de terceiros de direita — usado pelo
    wrapper presidencial pra preservar o comportamento de que eleitores do
    Flávio Bolsonaro têm maior afinidade com outro candidato de direita
    quando ele é um terceiro no cenário.

    Retorna o resultado do par + `runs`: lista com o dict completo de share
    simulado por candidato em cada rodada (já com o bucket de indecisos
    redistribuído), pra permitir métricas derivadas sem rodar nova simulação.
    """
    import random

    DIREITA = get_candidatos_por_espectro({'direita'})
    ESQUERDA_CENTRO = get_candidatos_por_espectro({'esquerda', 'centro'})
    pct_mudar_voto = pct_mudar_voto or {}
    mu_override = mu_override or {}

    medias_dict = {c['candidato']: c['media'] for c in candidatos}
    media_a = medias_dict.get(nome_a, 0)
    media_b = medias_dict.get(nome_b, 0)
    peso_total = (media_a + media_b) if (media_a + media_b) > 0 else 1
    peso_a = media_a / peso_total
    peso_b = media_b / peso_total

    runs = []
    vitorias_a = 0
    for _ in range(n_simulacoes):
        simulado = {}
        for c in candidatos:
            nome = c['candidato']
            sigma_base = max(margens.get(nome, margem_default) * fator_sigma, sigma_minimo)
            sigma = sigma_base * fator_volatilidade(pct_mudar_voto.get(nome))
            simulado[nome] = max(0, random.gauss(c['media'], sigma))

        simulado = _redistribuir_indecisos(simulado, pct_indecisos)
        runs.append(simulado)

        a = simulado.get(nome_a, 0)
        b = simulado.get(nome_b, 0)

        for nome, pct in simulado.items():
            if nome in (nome_a, nome_b):
                continue
            if nome in ESQUERDA_CENTRO:
                split = min(0.90, max(0.50, random.gauss(0.70, 0.08)))
                a += pct * split
                b += pct * (1 - split)
            elif nome in DIREITA:
                mu = mu_override.get(nome, 0.70)
                split = min(0.90, max(0.50, random.gauss(mu, 0.08)))
                b += pct * split
                a += pct * (1 - split)
            else:
                if media_a >= media_b:
                    a += pct * 0.40
                    b += pct * 0.30
                else:
                    b += pct * 0.40
                    a += pct * 0.30
                abstain = pct * 0.30
                a += abstain * peso_a
                b += abstain * peso_b

        total = a + b
        if total > 0 and (a / total) > 0.5:
            vitorias_a += 1

    prob_a = round(vitorias_a / n_simulacoes * 100, 1)
    prob_b = round(100 - prob_a, 1)
    return {
        'candidato_a': {
            'nome': nome_a,
            'media_direto': round(media_a, 1),
            'prob_vitoria': prob_a,
            'favorito': prob_a > prob_b,
            'prob_vitoria_primeiro_turno': prob_vitoria_primeiro_turno(nome_a, runs),
        },
        'candidato_b': {
            'nome': nome_b,
            'media_direto': round(media_b, 1),
            'prob_vitoria': prob_b,
            'favorito': prob_b > prob_a,
            'prob_vitoria_primeiro_turno': prob_vitoria_primeiro_turno(nome_b, runs),
        },
        'runs': runs,
    }


def simular_monte_carlo_cenarios(
    cargo: str,
    cenarios_def: list[tuple],
    n_simulacoes: int = 10000,
    fator_sigma: float = 2.0,
    sigma_minimo: float = 6.0,
    margem_default: float = 2.0,
    dias_media: int = 30,
    mu_override: dict | None = None,
) -> dict:
    """Motor genérico de Monte Carlo pra qualquer cargo.

    `cenarios_def` é uma lista de tuplas (nome_a, nome_b, id_cenario, label) —
    os confrontos a simular são decididos por quem chama, não fixos no motor
    (ex.: o wrapper presidencial get_simulacao_monte_carlo, ou uma futura
    versão pra governador_rj).
    """
    media = get_media_agregada(cargo, dias=dias_media)
    candidatos = media.get('candidatos', [])

    margens = _margens_por_candidato(cargo)
    pct_mudar_voto_valor = _pct_mudar_voto_recente(cargo)
    pct_mudar_voto = (
        {c['candidato']: pct_mudar_voto_valor for c in candidatos}
        if pct_mudar_voto_valor is not None else {}
    )
    pct_indecisos = _pct_indecisos_medio(cargo, dias=dias_media)

    cenarios = []
    for nome_a, nome_b, cid, label in cenarios_def:
        resultado = _simular_cenario(
            candidatos, margens, nome_a, nome_b,
            n_simulacoes=n_simulacoes,
            fator_sigma=fator_sigma,
            sigma_minimo=sigma_minimo,
            margem_default=margem_default,
            pct_indecisos=pct_indecisos,
            pct_mudar_voto=pct_mudar_voto,
            mu_override=mu_override,
        )
        cenarios.append({'id': cid, 'label': label, **resultado})

    return {
        'cargo': cargo,
        'cenarios': cenarios,
        'n_simulacoes': n_simulacoes,
        'fator_sigma_usado': fator_sigma,
        'sigma_minimo_usado': sigma_minimo,
        'margem_default_usada': margem_default,
    }


def _contagem_pesquisas_por_candidato(cargo: str, dias: int = 30) -> dict:
    """Quantas pesquisas (linhas de intencoes) cada candidato tem na janela,
    com os mesmos filtros de get_media_agregada (mesmo tipo, mesmos buckets
    excluídos, mesmo filtro de status ativo/inelegível via LEFT JOIN
    candidatos) — mas sem o corte de `len(entradas) < 2`, pra permitir
    distinguir candidatos com dado insuficiente dos com dado suficiente."""
    data_limite = (date.today() - timedelta(days=dias)).isoformat()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT i.candidato, COUNT(*) AS n
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
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
            GROUP BY i.candidato
        """, (cargo, data_limite)).fetchall()
    return {r['candidato']: r['n'] for r in rows}


def _aviso_amostra_limitada(candidatos_suficientes: list[dict]) -> str:
    """Monta o aviso de amostra limitada citando a maior variação real
    observada entre pesquisas, quando disponível."""
    variacoes = [c['variacao_30d'] for c in candidatos_suficientes if c.get('variacao_30d') is not None]
    if variacoes:
        maior = max(variacoes, key=abs)
        detalhe = f"variação entre pesquisas maior que o usual ({abs(maior):.0f}pp)"
    else:
        detalhe = "poucos dados disponíveis pra estimar variação"
    return (
        f"Baseado em institutos com rosters de candidatos distintos; {detalhe}. "
        "Interpretar com cautela até mais pesquisas confirmarem tendência."
    )


def simular_prob_vitoria_1_turno(
    candidatos: dict,
    n_simulacoes: int = 10000,
    fator_sigma: float = 2.0,
    sigma_minimo: float = 6.0,
) -> dict:
    """
    Simula, de forma independente por candidato — sem pool compartilhado,
    sem redistribuição entre concorrentes, sem depender de um segundo
    candidato existir — a chance de vitória em 1º turno "sozinho" (share
    simulado > 50.0).

    Conceitualmente diferente de _simular_cenario/prob_vitoria (que é
    par-a-par, pensado pra 2º turno: quem ganha entre A e B). Aqui cada
    candidato é uma distribuição gauss(media, sigma) independente das
    demais — não há "total da rodada" compartilhado, então não degenera
    quando só existe 1 candidato com dado suficiente (bug corrigido:
    antes, prob_vitoria_primeiro_turno(candidato, runs) dividia o share do
    candidato pela soma do dict de runs, que com 1 candidato só é sempre
    ele mesmo — share/total = 1.0 sempre, mascarando o sigma real).

    `candidatos` é um dict {nome: {'media': float, 'margem': float,
    'pct_pode_mudar_voto': float | None (opcional, default None)}}.

    Retorna {nome: prob_pct} — % das n_simulacoes rodadas em que o valor
    simulado desse candidato (isoladamente) ultrapassou 50.0.
    """
    import random

    resultado = {}
    for nome, dados in candidatos.items():
        media = dados['media']
        margem = dados['margem']
        sigma = max(margem * fator_sigma, sigma_minimo) * fator_volatilidade(dados.get('pct_pode_mudar_voto'))

        vitorias = 0
        for _ in range(n_simulacoes):
            if random.gauss(media, sigma) > 50.0:
                vitorias += 1
        resultado[nome] = round(vitorias / n_simulacoes * 100, 1)

    return resultado


def simular_monte_carlo_cargo(
    cargo: str,
    dias_media: int = 30,
    n_simulacoes: int = 10000,
    fator_sigma: float = 2.0,
    sigma_minimo: float = 6.0,
    margem_default: float = 2.0,
) -> dict:
    """
    Simula a chance de vitória em 1º turno (share > 50%, isoladamente) de
    cada candidato do cargo com dado suficiente (>= 2 pesquisas na janela)
    — via simular_prob_vitoria_1_turno(), independente por candidato (sem
    pool compartilhado nem depender de um segundo candidato existir).

    Formato de resposta NOVO, sem chaves legadas do endpoint presidencial
    (get_simulacao_monte_carlo) — este endpoint nasce sem dívida de
    compatibilidade.
    """
    media = get_media_agregada(cargo, dias=dias_media)
    candidatos_suficientes = media.get('candidatos', [])
    nomes_suficientes = {c['candidato'] for c in candidatos_suficientes}

    contagens = _contagem_pesquisas_por_candidato(cargo, dias=dias_media)
    candidatos_dados_insuficientes = sorted(
        nome for nome in contagens if nome not in nomes_suficientes
    )

    candidatos_simulados = []
    if candidatos_suficientes:
        margens = _margens_por_candidato(cargo)
        pct_mudar_voto_valor = _pct_mudar_voto_recente(cargo)

        entrada = {
            c['candidato']: {
                'media': c['media'],
                'margem': margens.get(c['candidato'], margem_default),
                'pct_pode_mudar_voto': pct_mudar_voto_valor,
            }
            for c in candidatos_suficientes
        }
        probs = simular_prob_vitoria_1_turno(
            entrada, n_simulacoes=n_simulacoes,
            fator_sigma=fator_sigma, sigma_minimo=sigma_minimo,
        )

        for c in candidatos_suficientes:
            candidatos_simulados.append({
                'nome': c['candidato'],
                'media': c['media'],
                'prob_vitoria_1_turno': probs[c['candidato']],
            })
        candidatos_simulados.sort(key=lambda c: c['media'], reverse=True)

    amostra_limitada = len(candidatos_suficientes) < 2
    aviso = _aviso_amostra_limitada(candidatos_suficientes) if amostra_limitada else None

    return {
        'cargo': cargo,
        'candidatos_simulados': candidatos_simulados,
        'candidatos_dados_insuficientes': candidatos_dados_insuficientes,
        'amostra_limitada': amostra_limitada,
        'aviso': aviso,
    }


def get_simulacao_monte_carlo(n_simulacoes: int = 10000) -> dict:
    """
    Wrapper de compatibilidade: simula os cenários presidenciais de sempre
    (Lula vs Flávio/Caiado/Zema) via simular_monte_carlo_cenarios() e remonta
    o formato de resposta legado — usado pelo endpoint GET /api/monte-carlo
    em produção. Mantém exatamente o mesmo formato e comportamento de antes.
    """
    CENARIOS_PRESIDENCIAL = [
        ('Lula', 'Flávio Bolsonaro', 'lula_flavio',  'Lula vs Flávio Bolsonaro'),
        ('Lula', 'Ronaldo Caiado',   'lula_caiado',  'Lula vs Ronaldo Caiado'),
        ('Lula', 'Romeu Zema',       'lula_zema',    'Lula vs Romeu Zema'),
    ]
    MARGEM_DEFAULT = 2.0

    resultado = simular_monte_carlo_cenarios(
        cargo='presidente',
        cenarios_def=CENARIOS_PRESIDENCIAL,
        n_simulacoes=n_simulacoes,
        margem_default=MARGEM_DEFAULT,
        # Eleitores do Flávio têm maior afinidade com outro cand. de direita
        # num 2º turno hipotético sem ele — split ligeiramente mais alto
        mu_override={'Flávio Bolsonaro': 0.75},
    )

    def _formato_legado(c: dict) -> dict:
        return {
            'nome': c['nome'],
            'media_direto': c['media_direto'],
            'prob_vitoria': c['prob_vitoria'],
            'favorito': c['favorito'],
        }

    cenarios = [
        {
            'id': c['id'],
            'label': c['label'],
            'candidato_a': _formato_legado(c['candidato_a']),
            'candidato_b': _formato_legado(c['candidato_b']),
        }
        for c in resultado['cenarios']
    ]

    primeiro = cenarios[0]
    return {
        'cenarios': cenarios,
        'n_simulacoes': n_simulacoes,
        'margem_default_usada': MARGEM_DEFAULT,
        # chaves flat para compatibilidade com dashboard existente
        'lula':   {**primeiro['candidato_a'], 'prob_vitoria': primeiro['candidato_a']['prob_vitoria']},
        'flavio': {**primeiro['candidato_b'], 'prob_vitoria': primeiro['candidato_b']['prob_vitoria']},
    }


def get_confronto_2turno_real(nome_a: str, nome_b: str, cargo: str = 'presidente',
                              dias: int = 30) -> dict | None:
    """Média das pesquisas REAIS de confronto direto de 2º turno entre A e B,
    dentro da janela. Pondera por amostra × recência (0.9 ^ dias) e usa uma
    pesquisa por instituto (a mais recente) — mesmo espírito do poll-of-polls.

    O par é casado independente da ordem em que o instituto listou A e B, e o
    resultado é orientado para (a=nome_a, b=nome_b). Retorna None se não houver
    nenhuma pesquisa de 2º turno na janela (aí o chamador cai na simulação).
    """
    data_limite = (date.today() - timedelta(days=dias)).isoformat()
    try:
        with get_db() as conn:
            rows = conn.execute("""
                SELECT instituto_id, candidato_a, candidato_b, pct_a, pct_b,
                       data_pesquisa, tamanho_amostra
                FROM confrontos_2turno
                WHERE cargo = ? AND data_pesquisa >= ?
                  AND ((candidato_a = ? AND candidato_b = ?)
                    OR (candidato_a = ? AND candidato_b = ?))
                ORDER BY data_pesquisa
            """, (cargo, data_limite, nome_a, nome_b, nome_b, nome_a)).fetchall()
    except sqlite3.OperationalError:
        # Tabela ainda não migrada (ex.: banco antigo antes do deploy) — cai na simulação.
        return None

    if not rows:
        return None

    # Uma pesquisa por instituto: a mais recente (desempate por rowid via ordem).
    recente_por_instituto: dict = {}
    for r in rows:
        inst = r['instituto_id']
        atual = recente_por_instituto.get(inst)
        if atual is None or r['data_pesquisa'] >= atual['data_pesquisa']:
            recente_por_instituto[inst] = r

    hoje = date.today()
    num_a = num_b = den = 0.0
    institutos = 0
    for r in recente_por_instituto.values():
        # Orienta para (nome_a, nome_b)
        if r['candidato_a'] == nome_a:
            pa, pb = r['pct_a'], r['pct_b']
        else:
            pa, pb = r['pct_b'], r['pct_a']
        peso_amostra = r['tamanho_amostra'] if r['tamanho_amostra'] and r['tamanho_amostra'] > 0 else 1000
        try:
            dias_desde = max(0, (hoje - date.fromisoformat(r['data_pesquisa'])).days)
        except (ValueError, TypeError):
            dias_desde = 0
        score = peso_amostra * (0.9 ** dias_desde)
        num_a += pa * score
        num_b += pb * score
        den += score
        institutos += 1

    if den == 0:
        return None
    return {
        "a": round(num_a / den, 1),
        "b": round(num_b / den, 1),
        "n_institutos": institutos,
    }


def get_simulacao_segundo_turno() -> dict:
    """Resultado de 2º turno Lula x Flávio.

    Usa a MÉDIA das pesquisas reais de confronto direto quando existem na janela
    (get_confronto_2turno_real); caso contrário, cai na simulação por
    redistribuição proporcional de votos (comportamento legado). O campo `fonte`
    ('pesquisas' | 'simulacao') indica qual caminho foi usado.
    """
    DIREITA = get_candidatos_por_espectro({'direita'})
    ESQUERDA_CENTRO = get_candidatos_por_espectro({'esquerda', 'centro'})

    media = get_media_agregada('presidente', dias=30)
    candidatos = media.get('candidatos', [])

    lula_direto = next((c['media'] for c in candidatos if c['candidato'] == 'Lula'), 0.0)
    flavio_direto = next((c['media'] for c in candidatos if c['candidato'] == 'Flávio Bolsonaro'), 0.0)

    lula_redist = 0.0
    flavio_redist = 0.0
    indefinido = 0.0

    for c in candidatos:
        nome = c['candidato']
        pct = c['media']
        if nome in ('Lula', 'Flávio Bolsonaro'):
            continue
        if nome in DIREITA:
            flavio_redist += pct * 0.70
            lula_redist += pct * 0.30
        elif nome in ESQUERDA_CENTRO:
            lula_redist += pct * 0.70
            flavio_redist += pct * 0.30
        else:
            indefinido += pct

    lula_total = lula_direto + lula_redist
    flavio_total = flavio_direto + flavio_redist

    # Prefere o confronto direto REAL das pesquisas, se houver na janela.
    real = get_confronto_2turno_real('Lula', 'Flávio Bolsonaro', cargo='presidente', dias=30)
    if real:
        segundo_turno = {
            "lula": {
                "votos_diretos": real['a'],
                "votos_redistribuidos": 0.0,
                "total_estimado": real['a'],
                "vencedor": real['a'] > real['b'],
            },
            "flavio": {
                "votos_diretos": real['b'],
                "votos_redistribuidos": 0.0,
                "total_estimado": real['b'],
                "vencedor": real['b'] > real['a'],
            },
            "indefinido": round(max(0.0, 100.0 - real['a'] - real['b']), 1),
            "fonte": "pesquisas",
            "nota": f"Média de pesquisas de 2º turno ({real['n_institutos']} instituto(s))",
        }
    else:
        segundo_turno = {
            "lula": {
                "votos_diretos": round(lula_direto, 1),
                "votos_redistribuidos": round(lula_redist, 1),
                "total_estimado": round(lula_total, 1),
                "vencedor": lula_total > flavio_total,
            },
            "flavio": {
                "votos_diretos": round(flavio_direto, 1),
                "votos_redistribuidos": round(flavio_redist, 1),
                "total_estimado": round(flavio_total, 1),
                "vencedor": flavio_total > lula_total,
            },
            "indefinido": round(indefinido, 1),
            "fonte": "simulacao",
            "nota": "Simulação baseada em redistribuição histórica de votos",
        }

    return {
        "primeiro_turno": {
            "candidatos": [
                {"candidato": c['candidato'], "media": c['media'], "variacao": c.get('variacao_30d')}
                for c in candidatos[:5]
            ],
            "segundo_turno_provavel": lula_direto < 50,
            "data_atualizacao": date.today().strftime('%d/%m/%Y'),
        },
        "segundo_turno": segundo_turno,
    }
