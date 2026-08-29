import os
os.environ['TESTING'] = 'True'

import math
import random

import pytest

# Módulo puro (sem db.core) — importável direto sem o ciclo da façade.
# Import por namespace: nomes `teste_*` no escopo do módulo seriam coletados
# pelo pytest (padrão default `test*`).
from db import estatistica as est


# ---------- chi2_sf: valores críticos tabelados (gl par e ímpar) ----------

@pytest.mark.parametrize("x, gl, esperado", [
    (3.841, 1, 0.05),
    (5.991, 2, 0.05),
    (16.919, 9, 0.05),
    (21.666, 9, 0.01),
    (15.507, 8, 0.05),
])
def test_chi2_sf_valores_tabelados(x, gl, esperado):
    assert est.chi2_sf(x, gl) == pytest.approx(esperado, abs=1e-3)


def test_chi2_sf_bordas():
    assert est.chi2_sf(0, 5) == 1.0
    assert est.chi2_sf(-1, 5) == 1.0
    assert est.chi2_sf(1000, 5) == pytest.approx(0.0, abs=1e-9)


# ---------- qui-quadrado de aderência ----------

def test_qui_quadrado_ajuste_perfeito():
    r = est.teste_qui_quadrado([10, 10, 10], [10.0, 10.0, 10.0])
    assert r["chi2"] == 0.0
    assert r["p_valor"] == 1.0
    assert r["gl"] == 2


def test_qui_quadrado_valida_entrada():
    with pytest.raises(ValueError):
        est.teste_qui_quadrado([1, 2], [1.0])
    with pytest.raises(ValueError):
        est.teste_qui_quadrado([1, 2], [1.0, 0.0])


# ---------- dígito final ----------

def test_digito_final_arredondamento_manual_dispara():
    # 100 valores todos terminados em .0 ou .5 — arredondamento "no olho"
    valores = [float(v) for v in range(10, 60)] + [v + 0.5 for v in range(10, 60)]
    r = est.teste_digito_final(valores)
    assert r is not None
    assert r["p_valor"] < 0.01
    assert r["excesso_0_5"] > 0.5


def test_digito_final_uniforme_nao_dispara():
    valores = [10 + i + d / 10 for i in range(10) for d in range(10)]  # dígitos 0-9 balanceados
    r = est.teste_digito_final(valores)
    assert r is not None
    assert r["chi2"] == 0.0
    assert r["p_valor"] > 0.9


def test_digito_final_n_insuficiente():
    assert est.teste_digito_final([12.3] * 20) is None


def test_digito_final_float_impreciso():
    # 12.3*10 = 122.99999... — a guarda de +1e-9 precisa classificar como dígito 3
    r = est.teste_digito_final([12.3] * 30)
    assert r["contagens"][3] == 30


# ---------- Benford ----------

def test_benford_potencias_de_2_conformes():
    # 1º dígito de 2^k segue Benford (teorema clássico de equidistribuição)
    valores = [float(2 ** k) for k in range(1, 201)]
    r = est.teste_benford(valores)
    assert r is not None
    assert r["p_valor"] > 0.05


def test_benford_uniforme_dispara():
    # uniformes em 1-9999: 1º dígito ~uniforme, viola Benford
    rng = random.Random(42)
    valores = [float(rng.randint(1, 9999)) for _ in range(500)]
    r = est.teste_benford(valores)
    assert r is not None
    assert r["p_valor"] < 0.01


def test_benford_amplitude_insuficiente():
    # percentuais 10-60: menos de 2 ordens de grandeza — teste não se aplica
    assert est.teste_benford([float(v) for v in range(10, 61)] * 2) is None


def test_benford_n_insuficiente():
    assert est.teste_benford([float(2 ** k) for k in range(1, 12)]) is None


# ---------- subdispersão ----------

def test_subdispersao_serie_constante_dispara():
    # 8 pesquisas idênticas com n=2000: variância zero é "bom demais"
    r = est.teste_subdispersao([32.0] * 8, [2000] * 8)
    assert r is not None
    assert r["p_subdispersao"] < 0.01


def test_subdispersao_ruido_binomial_nao_dispara():
    # série com dispersão compatível com a binomial (sd ≈ sqrt(.32*.68/2000) ≈ 1pp)
    rng = random.Random(7)
    percentuais = [32.0 + rng.gauss(0, 1.0) for _ in range(10)]
    r = est.teste_subdispersao(percentuais, [2000] * 10)
    assert r is not None
    assert r["p_subdispersao"] > 0.05


def test_subdispersao_k_insuficiente():
    assert est.teste_subdispersao([32.0] * 4, [2000] * 4) is None


# ---------- KL ----------

def test_kl_identicas_e_disjuntas():
    dist = {"a": 50, "b": 30, "c": 20}
    assert est.divergencia_kl(dist, dict(dist)) == pytest.approx(0.0, abs=1e-12)
    assert est.divergencia_kl({"a": 1}, {"b": 1}) == math.inf


def test_kl_valida_massa():
    with pytest.raises(ValueError):
        est.divergencia_kl({"a": 0}, {"a": 1})
