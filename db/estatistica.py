"""Funções estatísticas puras do módulo de integridade (sem acesso a banco).

Tudo em stdlib (math/collections), seguindo o precedente de db/monte_carlo.py.
Cada teste devolve None quando não há N mínimo para o resultado ser
interpretável — o chamador exibe "dados insuficientes", nunca um veredito.
"""
import math
from collections import Counter

# Mínimos estatísticos: qui-quadrado exige esperado >= ~3 por célula
# (10 células no dígito final → n>=30; 9 células desiguais no Benford → n>=50);
# subdispersão precisa de graus de liberdade (k>=5 pesquisas na série).
N_MIN_DIGITO_FINAL = 30
N_MIN_BENFORD = 50
K_MIN_SUBDISPERSAO = 5


def chi2_sf(x: float, gl: int) -> float:
    """P-valor (survival function) da qui-quadrado com `gl` graus de liberdade.

    Gamma incompleta regularizada superior Q(gl/2, x/2) via recorrência
    Q(a+1,t) = Q(a,t) + t^a·e^(−t)/Γ(a+1), com âncoras exatas do stdlib:
    Q(1,t)=exp(−t) para gl par e Q(0.5,t)=erfc(sqrt(t)) para gl ímpar.
    """
    if x <= 0:
        return 1.0
    t = x / 2.0
    if gl % 2 == 0:
        a, q = 1.0, math.exp(-t)
    else:
        a, q = 0.5, math.erfc(math.sqrt(t))
    while a < gl / 2.0 - 1e-9:
        q += math.exp(a * math.log(t) - t - math.lgamma(a + 1.0))
        a += 1.0
    return min(1.0, max(0.0, q))


def teste_qui_quadrado(observados: list, esperados: list) -> dict:
    """Qui-quadrado de aderência entre contagens observadas e esperadas.

    As listas devem ter o mesmo tamanho e esperados > 0 em todas as células.
    """
    if len(observados) != len(esperados):
        raise ValueError("observados e esperados devem ter o mesmo tamanho")
    if any(e <= 0 for e in esperados):
        raise ValueError("todas as contagens esperadas devem ser > 0")
    chi2 = sum((o - e) ** 2 / e for o, e in zip(observados, esperados))
    gl = len(observados) - 1
    return {
        "chi2": round(chi2, 3),
        "gl": gl,
        "p_valor": round(chi2_sf(chi2, gl), 4),
        "n": int(sum(observados)),
    }


def teste_digito_final(valores: list) -> dict | None:
    """Uniformidade do último dígito decimal (0-9) de percentuais.

    Em dados reais o dígito final é ~uniforme; excesso de .0/.5 indica
    arredondamento manual ou estimativa "no olho". None se n < 30.
    """
    n = len(valores)
    if n < N_MIN_DIGITO_FINAL:
        return None
    # 1e-9 blinda contra float impreciso (12.3*10 = 122.99999...)
    digitos = [int(round(abs(v) * 10 + 1e-9)) % 10 for v in valores]
    contagens = [0] * 10
    for d in digitos:
        contagens[d] += 1
    resultado = teste_qui_quadrado(contagens, [n / 10.0] * 10)
    resultado["contagens"] = contagens
    resultado["excesso_0_5"] = round((contagens[0] + contagens[5]) / n - 0.2, 3)
    return resultado


def teste_benford(valores: list) -> dict | None:
    """Aderência do 1º dígito significativo à Lei de Benford.

    Só se aplica a conjuntos que cobrem >= 2 ordens de grandeza (percentuais
    limitados a 0-100 quase nunca qualificam — por isso o teste roda sobre
    microdados/contagens, não sobre a série agregada do banco). None se
    n < 50 ou amplitude insuficiente.
    """
    positivos = [v for v in valores if v > 0]
    n = len(positivos)
    if n < N_MIN_BENFORD:
        return None
    if math.log10(max(positivos)) - math.log10(min(positivos)) < 2:
        return None
    contagens = [0] * 9
    for v in positivos:
        while v < 1:
            v *= 10
        while v >= 10:
            v /= 10
        contagens[int(v) - 1] += 1
    esperados = [n * math.log10(1 + 1 / d) for d in range(1, 10)]
    resultado = teste_qui_quadrado(contagens, esperados)
    resultado["contagens"] = contagens
    resultado["esperados"] = [round(e, 1) for e in esperados]
    return resultado


def teste_subdispersao(percentuais: list, amostras: list) -> dict | None:
    """Detecta variância baixa demais numa série de um mesmo candidato/instituto.

    Sob amostragem aleatória, T = Σ (p_i − p̄)² / (p̄(1−p̄)/n_i) ~ χ²(k−1).
    T muito pequeno (cauda esquerda) = série "boa demais para ser verdade",
    indício clássico de fabricação (caso Research 2000). None se k < 5.

    Ressalva metodológica: pesquisas por cotas têm deff < 1 natural — este
    resultado isolado é indício fraco; só pesa combinado a outros testes.
    """
    k = len(percentuais)
    if k < K_MIN_SUBDISPERSAO or k != len(amostras):
        return None
    ps = [p / 100.0 for p in percentuais]
    pbar = sum(ps) / k
    if pbar <= 0 or pbar >= 1 or any(n <= 0 for n in amostras):
        return None
    t = sum((p - pbar) ** 2 / (pbar * (1 - pbar) / n) for p, n in zip(ps, amostras))
    gl = k - 1
    return {
        "estatistica": round(t, 3),
        "gl": gl,
        "k": k,
        # cauda esquerda: prob. de variância TÃO baixa sob amostragem honesta
        "p_subdispersao": round(1.0 - chi2_sf(t, gl), 4),
    }


def divergencia_kl(observada: dict, referencia: dict) -> float:
    """Divergência de Kullback-Leibler D(observada || referencia), em nats.

    Distribuições como dict categoria → massa (normalizadas internamente).
    Categoria observada sem massa na referência → inf (suporte incompatível).
    """
    total_o = sum(observada.values())
    total_r = sum(referencia.values())
    if total_o <= 0 or total_r <= 0:
        raise ValueError("distribuições devem ter massa total > 0")
    kl = 0.0
    for cat, massa in observada.items():
        if massa <= 0:
            continue
        o = massa / total_o
        r = referencia.get(cat, 0) / total_r
        if r <= 0:
            return math.inf
        kl += o * math.log(o / r)
    return max(0.0, kl)
