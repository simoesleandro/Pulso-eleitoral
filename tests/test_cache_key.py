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
