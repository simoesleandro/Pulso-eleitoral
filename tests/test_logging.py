import os
# Configura o ambiente de testes antes de importar
os.environ['TESTING'] = 'True'

import logging
import time
from contextlib import contextmanager

import pytest

import app as app_module
from app import run_all_collectors
from database import DB_PATH, init_db


@pytest.fixture(autouse=True)
def setup_db():
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass
    init_db(force_seed=False)
    yield
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass


@contextmanager
def raiz_isolada():
    """Logger raiz sem handlers, restaurado no fim — como no processo de
    produção, onde nada configurou logging antes do app. Usado no corpo do
    teste, não numa fixture: o pytest põe os handlers de captura da fase de
    execução depois do setup das fixtures."""
    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    raiz.handlers.clear()
    try:
        yield raiz
    finally:
        raiz.handlers[:] = handlers
        raiz.setLevel(nivel)


def test_logger_raiz_em_info_depois_do_init():
    """Sem isso, só WARNING ou acima aparece no flyctl logs."""
    assert logging.getLogger().level == logging.INFO


def test_configurar_logging_formato_com_horario_nivel_e_nome():
    with raiz_isolada() as raiz:
        app_module.configurar_logging()
        nivel, handlers = raiz.level, raiz.handlers[:]

    assert nivel == logging.INFO
    assert len(handlers) == 1
    fmt = handlers[0].formatter._fmt
    for campo in ("%(asctime)s", "%(levelname)s", "%(name)s"):
        assert campo in fmt


def test_configurar_logging_nao_duplica_com_waitress():
    """waitress.serve() chama logging.basicConfig(); reconfigurar ou o
    basicConfig do Waitress não pode acrescentar um segundo handler (cada
    linha sairia duas vezes)."""
    with raiz_isolada() as raiz:
        app_module.configurar_logging()
        app_module.configurar_logging()
        logging.basicConfig()
        n_handlers = len(raiz.handlers)

    assert n_handlers == 1


def _coletor(nome, run):
    return type(nome, (), {"__init__": lambda self, db_path: None, "run": run})


def test_resumo_da_coleta_uma_linha_por_coletor(monkeypatch, caplog):
    ok = _coletor("ColetorOk", lambda self: {"status": "ok", "salvas": 3, "falhas": []})
    parcial = _coletor("ColetorParcial", lambda self: {
        "status": "parcial", "salvas": 1, "falhas": [("u1", "e"), ("u2", "e")]})

    def explode(self):
        raise RuntimeError("quebrou")
    quebrado = _coletor("ColetorQueExplode", explode)

    import collectors
    monkeypatch.setattr(collectors, "ALL_COLLECTORS", [ok, parcial, quebrado])
    monkeypatch.setattr("notifier.send_telegram", lambda *a, **k: None)

    with caplog.at_level(logging.INFO, logger="app"):
        run_all_collectors()

    resumo = [r for r in caplog.records if r.getMessage().startswith("Coletor ")
              and "duração" in r.getMessage()]
    assert len(resumo) == 3

    por_nome = {r.getMessage().split()[1]: r for r in resumo}
    assert set(por_nome) == {"ColetorOk", "ColetorParcial", "ColetorQueExplode"}

    msg_ok = por_nome["ColetorOk"].getMessage()
    assert por_nome["ColetorOk"].levelno == logging.INFO
    assert "gravadas=3" in msg_ok and "falhas=0" in msg_ok and "status=ok" in msg_ok

    msg_parcial = por_nome["ColetorParcial"].getMessage()
    assert "gravadas=1" in msg_parcial and "falhas=2" in msg_parcial

    assert "status=erro" in por_nome["ColetorQueExplode"].getMessage()


def test_timeout_do_coletor_gera_warning_com_o_nome(monkeypatch, caplog):
    lento = _coletor("ColetorLento", lambda self: time.sleep(0.5) or
                     {"status": "ok", "salvas": 0, "falhas": []})

    import collectors
    monkeypatch.setattr(collectors, "ALL_COLLECTORS", [lento])
    monkeypatch.setattr("notifier.send_telegram", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "TIMEOUT_COLETOR_S", 0.05)

    with caplog.at_level(logging.INFO, logger="app"):
        resultados = run_all_collectors()

    assert resultados == [{"coletor": "ColetorLento", "status": "timeout", "msg": "Excedeu 0.05s"}]
    avisos = [r for r in caplog.records
              if r.levelno == logging.WARNING and "ColetorLento" in r.getMessage()
              and "timeout" in r.getMessage()]
    assert len(avisos) == 1
