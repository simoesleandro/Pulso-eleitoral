import os
os.environ['TESTING'] = 'True'

from datetime import date

import pytest

from collectors.verita import VeritaCollector

DB_PATH = "data/pulso_test.db"


@pytest.fixture
def coletor():
    return VeritaCollector(db_path=DB_PATH)


def test_build_items_gov_com_um_candidato(coletor):
    """Com candidato, _build_items_gov monta o item de governador RJ. Antes
    levantava NameError (date usado sem import) em todo PDF do RJ."""
    resultado = {
        "candidatos": [{"nome": "Eduardo Paes", "percentual": 48.6}],
        "tipo": "estimulada",
    }
    itens = coletor._build_items_gov(resultado, "https://exemplo/pesquisa/rj")

    assert len(itens) == 1
    item = itens[0]
    assert item["cargo"] == "governador_rj"
    assert item["candidato"] == "Eduardo Paes"
    assert item["percentual"] == 48.6
    assert item["instituto_id"] == 9
    # Sem data extraída, cai na data de hoje (é aqui que o import faltava).
    assert item["data_pesquisa"] == date.today().isoformat()
    assert item["data_coleta"] == date.today().isoformat()
