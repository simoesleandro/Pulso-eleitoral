import os
os.environ['TESTING'] = 'True'

import json

import pytest

from db.microdados import ErroMicrodados, analisar_csv


def _csv(linhas: list[str]) -> bytes:
    return "\n".join(linhas).encode("utf-8")


# ---------- duplicatas ----------

def test_duplicatas_copy_paste_detectadas():
    linhas = ["sexo,idade"] + ["F,34"] * 15 + [f"M,{20+i}" for i in range(35)]
    laudo = analisar_csv(_csv(linhas))
    assert laudo["duplicatas"]["grupos"] == 1
    assert laudo["duplicatas"]["linhas_duplicadas"] == 15
    assert laudo["duplicatas"]["pct"] == pytest.approx(30.0, abs=0.1)


def test_csv_limpo_sem_duplicatas():
    linhas = ["sexo,idade"] + [f"F,{20+i}" for i in range(50)]
    laudo = analisar_csv(_csv(linhas))
    assert laudo["duplicatas"]["grupos"] == 0
    assert laudo["duplicatas"]["linhas_duplicadas"] == 0


# ---------- Benford em coluna numérica ----------

def test_benford_coluna_conforme_vs_fabricada():
    conforme = ["contagem"] + [str(2 ** k) for k in range(1, 201)]
    laudo_ok = analisar_csv(_csv(conforme))
    r_ok = laudo_ok["colunas"][0]["benford"]
    assert r_ok is not None and r_ok["p_valor"] > 0.05

    import random
    rng = random.Random(1)
    # amplitude precisa cobrir >=2 ordens de grandeza para o teste se aplicar
    fabricada = ["contagem"] + [str(rng.randint(1, 999999)) for _ in range(500)]
    laudo_fab = analisar_csv(_csv(fabricada))
    r_fab = laudo_fab["colunas"][0]["benford"]
    assert r_fab is not None and r_fab["p_valor"] < 0.01


# ---------- malformados: sempre 400 (ErroMicrodados), nunca traceback ----------

def test_arquivo_binario_rejeitado():
    with pytest.raises(ErroMicrodados):
        analisar_csv(bytes([0, 1, 2, 0, 255, 0]) * 100)


def test_arquivo_vazio_rejeitado():
    with pytest.raises(ErroMicrodados):
        analisar_csv(b"")


def test_apenas_cabecalho_rejeitado():
    with pytest.raises(ErroMicrodados):
        analisar_csv(_csv(["sexo,idade"]))


def test_muitas_linhas_rejeitado():
    from db import microdados
    linhas = ["a"] + ["1"] * (microdados.LIMITE_LINHAS + 10)
    with pytest.raises(ErroMicrodados):
        analisar_csv(_csv(linhas))


def test_muitas_colunas_rejeitado():
    cabecalho = ",".join(f"c{i}" for i in range(150))
    linha = ",".join("1" for _ in range(150))
    with pytest.raises(ErroMicrodados):
        analisar_csv(_csv([cabecalho, linha]))


def test_linha_malformada_isolada_nao_derruba_arquivo():
    linhas = ["sexo,idade", "F,34", "linha,quebrada,com,colunas,demais", "M,29"]
    laudo = analisar_csv(_csv(linhas))
    assert laudo["resumo"]["linhas"] == 2


# ---------- aderência / KL com proporções de referência ----------

def test_aderencia_e_kl_coluna_categorica():
    linhas = ["sexo"] + ["F"] * 52 + ["M"] * 48
    laudo = analisar_csv(_csv(linhas), {"sexo": {"F": 52, "M": 48}})
    col = laudo["colunas"][0]
    assert col["aderencia"]["p_valor"] > 0.9
    assert col["kl"] == pytest.approx(0.0, abs=1e-3)


def test_proporcao_referencia_coluna_inexistente_vira_aviso():
    linhas = ["sexo"] + ["F"] * 10 + ["M"] * 10
    laudo = analisar_csv(_csv(linhas), {"idade": {"jovem": 50, "velho": 50}})
    assert any("idade" in a for a in laudo["avisos"])


# ---------- rota HTTP ----------

from app import app as flask_app
from database import DB_PATH, init_db


@pytest.fixture(autouse=True)
def cleanup():
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass
    yield
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret-key'
    with flask_app.test_client() as client:
        yield client


def _login(client):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'admin'
        sess['nome'] = 'Administrador'


def test_rota_exige_login(client):
    resp = client.post('/integridade/microdados', data={}, follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_rota_sem_arquivo_400(client):
    init_db(force_seed=True)
    _login(client)
    resp = client.post('/integridade/microdados', data={})
    assert resp.status_code == 400
    assert 'erro' in resp.get_json()


def test_rota_proporcoes_json_invalido_400(client):
    from io import BytesIO
    init_db(force_seed=True)
    _login(client)
    dados = {
        'arquivo': (BytesIO(_csv(["a"] + ["1"] * 40)), 'teste.csv'),
        'proporcoes': 'não é json',
    }
    resp = client.post('/integridade/microdados', data=dados, content_type='multipart/form-data')
    assert resp.status_code == 400


def test_rota_upload_valido_200(client):
    from io import BytesIO
    init_db(force_seed=True)
    _login(client)
    conteudo = _csv(["sexo,idade"] + [f"F,{20+i}" for i in range(40)])
    dados = {'arquivo': (BytesIO(conteudo), 'teste.csv')}
    resp = client.post('/integridade/microdados', data=dados, content_type='multipart/form-data')
    assert resp.status_code == 200
    corpo = resp.get_json()
    assert corpo['resumo']['linhas'] == 40
