import os
os.environ['TESTING'] = 'True'

import pytest

import database
from collectors.gemini_extractor import normalizar_nome


@pytest.fixture(autouse=True)
def roster():
    """Banco de teste com o roster do seed; cache de candidatos recarregado."""
    database.init_db(force_seed=False)
    database._invalidar_cache_candidatos()
    yield
    database._invalidar_cache_candidatos()


@pytest.mark.parametrize("bruto, esperado", [
    # Governador RJ — formato das tabelas do Verita e do Paraná.
    ("Eduardo Paes (PSD)", "Eduardo Paes"),
    ("Douglas Ruas (PL)", "Douglas Ruas"),
    ("Wilson Witzel (Democrata)", "Wilson Witzel"),
    ("Cyro Garcia (PSTU)", "Cyro Garcia"),
    ("EDUARDO PAES - PSD", "Eduardo Paes"),
    # Presidente — hífen, meia-risca e partido de mais de uma palavra.
    ("Lula – PT", "Lula"),
    ("FLAVIO BOLSONARO - PL", "Flávio Bolsonaro"),
    ("Pablo Marçal – União Brasil", "Pablo Marçal"),
    ("Ronaldo Caiado — PSD", "Ronaldo Caiado"),
    ("Romeu Zema (Novo)", "Romeu Zema"),
    ("Augusto Cury - AVANTE", "Augusto Cury"),
])
def test_tira_o_partido_e_normaliza(bruto, esperado):
    assert normalizar_nome(bruto) == esperado


def test_fora_do_roster_devolve_o_nome_sem_partido():
    """Candidato desconhecido não vira série separada por causa do partido."""
    assert normalizar_nome("Rafael Luz (Missão)") == "Rafael Luz"
    assert normalizar_nome("William Siri (PSOL)") == "William Siri"


def test_inativo_com_partido_continua_descartado():
    assert normalizar_nome("Jair Bolsonaro - PL") is None
    assert normalizar_nome("Fernando Haddad (PT)") is None


@pytest.mark.parametrize("nome", [
    "Anthony Garotinho",
    "Fulano de Tal - Filho",          # sufixo que não é partido
    "Beltrano (hipotético)",          # parêntese que não é partido
    "Jean-Pierre Silva",              # hífen dentro do nome
])
def test_sufixo_que_nao_e_partido_fica(nome):
    assert normalizar_nome(nome) == nome


def test_apelido_com_partido_no_roster_tem_precedencia():
    """"renan santos (missão)" já é apelido cadastrado."""
    assert normalizar_nome("Renan Santos (Missão)") == "Renan Santos"
