import os
# Configura o ambiente de testes antes de importar os módulos do projeto
os.environ['TESTING'] = 'True'

from app import (
    app as flask_app,
    _chave_cache_alertas,
    _chave_cache_historico_multi,
    _chave_cache_media_agregada,
)


def test_chave_cache_alertas_normaliza_parametros_equivalentes():
    """janela=7 e janela=07 são o mesmo pedido — a chave de cache deve
    colapsar as duas variações textuais em uma única entrada."""
    with flask_app.test_request_context('/api/alertas?janela=7'):
        chave1 = _chave_cache_alertas()
    with flask_app.test_request_context('/api/alertas?janela=07'):
        chave2 = _chave_cache_alertas()
    assert chave1 == chave2


def test_chave_cache_historico_multi_ignora_ordem_dos_candidatos():
    """A ordem da lista de candidatos não muda o conjunto de séries pedido
    — 'Lula,Ciro Gomes' e 'Ciro Gomes,Lula' devem colapsar na mesma
    entrada de cache."""
    with flask_app.test_request_context(
        '/api/pesquisas/historico-multi?candidatos=Lula,Ciro Gomes'
    ):
        chave1 = _chave_cache_historico_multi()
    with flask_app.test_request_context(
        '/api/pesquisas/historico-multi?candidatos=Ciro Gomes,Lula'
    ):
        chave2 = _chave_cache_historico_multi()
    assert chave1 == chave2


def test_chave_cache_media_agregada_normaliza_parametros_equivalentes():
    """dias=30 e dias=30.0 devem colapsar na mesma entrada de cache."""
    with flask_app.test_request_context('/api/media-agregada?dias=30'):
        chave1 = _chave_cache_media_agregada()
    with flask_app.test_request_context('/api/media-agregada?dias=30.0'):
        chave2 = _chave_cache_media_agregada()
    assert chave1 == chave2


import sqlite3

import pytest

from app import cache
from database import DB_PATH, init_db


@pytest.fixture
def cache_real():
    """Cache de verdade só neste teste. Sob TESTING o app usa NullCache (o
    SimpleCache é global no processo e vazaria entre testes), então bug de
    chave de cache é invisível no resto da suíte."""
    cache.init_app(flask_app, config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 300})
    cache.clear()
    yield
    cache.clear()
    cache.init_app(flask_app, config={'CACHE_TYPE': 'NullCache'})


@pytest.fixture
def banco_com_estimulada_e_espontanea():
    """Banco de teste com uma pesquisa presidencial de cada tipo, datadas
    depois de qualquer dado de demo para serem as mais recentes."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()
    conn = sqlite3.connect(DB_PATH)
    for registro, tipo, pct in (('TESTE-EST/2030', 'estimulada', 41.0),
                                ('TESTE-ESP/2030', 'espontanea', 22.0)):
        cur = conn.execute(
            "INSERT INTO pesquisas (instituto_id, cargo, data_pesquisa, data_publicacao, "
            "tamanho_amostra, margem_erro, registro_tse) "
            "VALUES (1, 'presidente', '2030-01-01', '2030-01-02', 2000, 2.0, ?)",
            (registro,))
        conn.execute(
            "INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) VALUES (?, 'Lula', ?, ?)",
            (cur.lastrowid, pct, tipo))
    conn.commit()
    conn.close()
    yield
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


def test_api_presidente_cache_respeita_parametro_tipo(cache_real, banco_com_estimulada_e_espontanea):
    """O toggle estimulada/espontânea chama a mesma rota com ?tipo= diferente.
    A chave de cache não pode ignorar o parâmetro — antes, a segunda chamada
    devolvia a resposta cacheada da primeira."""
    with flask_app.test_client() as client:
        est = client.get('/api/pesquisas/presidente?tipo=estimulada').json
        esp = client.get('/api/pesquisas/presidente?tipo=espontanea').json

    assert est['tipo'] == 'estimulada'
    assert est['percentuais'] == [41.0]
    assert esp['tipo'] == 'espontanea'
    assert esp['percentuais'] == [22.0]


def test_chave_cache_presidente_normaliza_tipo():
    """Sem ?tipo e com ?tipo inválido o handler usa 'estimulada' — as três
    variações devem colapsar na mesma entrada; espontânea fica separada."""
    from app import _chave_cache_presidente
    chaves = []
    for qs in ('', '?tipo=estimulada', '?tipo=qualquer-coisa', '?tipo=espontanea'):
        with flask_app.test_request_context('/api/pesquisas/presidente' + qs):
            chaves.append(_chave_cache_presidente())
    assert chaves[0] == chaves[1] == chaves[2]
    assert chaves[3] != chaves[0]
