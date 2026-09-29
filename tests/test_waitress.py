import os
# Configura o ambiente de testes antes de importar
os.environ['TESTING'] = 'True'

import pytest

import app as app_module


@pytest.fixture
def serve_capturado(monkeypatch):
    """Substitui waitress.serve e o start do scheduler: iniciar_servidor()
    roda até o serve() sem abrir porta nem ligar job agendado."""
    chamadas = []
    import waitress
    monkeypatch.setattr(waitress, "serve", lambda app, **kw: chamadas.append(kw))
    monkeypatch.setattr(app_module.scheduler, "start", lambda *a, **k: None)
    return chamadas


def test_threads_da_variavel_chegam_ao_serve(monkeypatch, serve_capturado):
    monkeypatch.setenv("WAITRESS_THREADS", "24")

    app_module.iniciar_servidor()

    assert len(serve_capturado) == 1
    assert serve_capturado[0]["threads"] == 24


def test_threads_sem_variavel_padrao_16(monkeypatch, serve_capturado):
    monkeypatch.delenv("WAITRESS_THREADS", raising=False)

    app_module.iniciar_servidor()

    assert serve_capturado[0]["threads"] == 16


@pytest.mark.parametrize("valor", ["abc", "0", "-3", ""])
def test_threads_invalido_cai_no_padrao(monkeypatch, serve_capturado, valor):
    """Um erro de digitação no fly.toml não pode derrubar o boot."""
    monkeypatch.setenv("WAITRESS_THREADS", valor)

    app_module.iniciar_servidor()

    assert serve_capturado[0]["threads"] == 16
