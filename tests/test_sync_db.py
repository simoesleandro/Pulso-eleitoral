import os
os.environ['TESTING'] = 'True'

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import database
from scripts import sync_db

RAIZ = Path(__file__).resolve().parent.parent


def _banco_local(tmp_path, n_pesquisas: int) -> str:
    """SQLite com o schema do projeto e `n_pesquisas` pesquisas (cada uma
    com uma intenção, que é o que o export de produção conta)."""
    db = str(tmp_path / "local.db")
    conn = sqlite3.connect(db)
    conn.executescript((RAIZ / "schema.sql").read_text(encoding="utf-8"))
    conn.execute("INSERT INTO institutos (id, nome) VALUES (1, 'Datafolha')")
    for i in range(n_pesquisas):
        cur = conn.execute(
            "INSERT INTO pesquisas (instituto_id, cargo, data_pesquisa, data_publicacao, "
            "tamanho_amostra, margem_erro, registro_tse) "
            "VALUES (1, 'presidente', '2026-09-01', '2026-09-02', 2000, 2.0, ?)", (f"R{i}",))
        conn.execute("INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) "
                     "VALUES (?, 'Lula', 40.0, 'estimulada')", (cur.lastrowid,))
    conn.commit()
    conn.close()
    return db


def _csv_producao(n_pesquisas: int) -> str:
    """Export público de produção: uma linha por intenção, várias por pesquisa."""
    linhas = ["pesquisa_id,instituto,registro_tse,cargo,data_pesquisa,data_publicacao,"
              "tamanho_amostra,margem_erro,candidato,percentual,tipo"]
    for pid in range(1, n_pesquisas + 1):
        for cand in ("Lula", "Flávio Bolsonaro"):
            linhas.append(f"{pid},Datafolha,R{pid},presidente,2026-09-01,2026-09-02,2000,2.0,{cand},40.0,estimulada")
    return "\n".join(linhas) + "\n"


@pytest.fixture
def producao_com(monkeypatch):
    """Mocka o GET do export público; devolve o mock para inspeção."""
    def configurar(n_pesquisas=None, status=200, erro=None):
        resp = MagicMock(status_code=status, text=_csv_producao(n_pesquisas or 0))
        resp.raise_for_status.side_effect = (
            None if status == 200 else sync_db.requests.HTTPError(f"{status} Server Error"))
        get = MagicMock(side_effect=erro) if erro else MagicMock(return_value=resp)
        monkeypatch.setattr(sync_db.requests, "get", get)
        return get
    return configurar


@pytest.fixture
def flyctl(monkeypatch):
    """Nenhum teste pode chegar ao flyctl/upload sem querer: registra as
    chamadas em vez de executá-las."""
    run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(sync_db.subprocess, "run", run)
    upload = MagicMock(return_value=True)
    monkeypatch.setattr(sync_db, "upload_e_apply", upload)
    monkeypatch.setattr(sync_db, "wait_machine_ready", MagicMock(return_value=True))
    return {"run": run, "upload": upload}


def test_sync_sem_flag_de_confirmacao_aborta(tmp_path, producao_com, flyctl):
    get = producao_com(n_pesquisas=1)
    db = _banco_local(tmp_path, 5)

    with pytest.raises(sync_db.SyncAbortado, match="--force-sync"):
        sync_db.sync_para_fly(db_local=db)

    get.assert_not_called()
    flyctl["run"].assert_not_called()
    flyctl["upload"].assert_not_called()


def test_sync_com_banco_local_menor_que_producao_aborta(tmp_path, producao_com, flyctl):
    producao_com(n_pesquisas=44)
    db = _banco_local(tmp_path, 1)

    with pytest.raises(sync_db.SyncAbortado) as exc:
        sync_db.sync_para_fly(force_sync=True, db_local=db)

    msg = str(exc.value)
    assert "1 pesquisa" in msg and "44" in msg, msg
    assert "produção" in msg
    flyctl["run"].assert_not_called()
    flyctl["upload"].assert_not_called()


def test_sync_aborta_se_nao_consegue_contar_producao(tmp_path, producao_com, flyctl):
    """Sem a contagem de produção não há como garantir que o local não está
    defasado — aborta em vez de sincronizar às cegas."""
    producao_com(erro=sync_db.requests.ConnectionError("sem rota"))
    db = _banco_local(tmp_path, 50)

    with pytest.raises(sync_db.SyncAbortado, match="contar as pesquisas de produção"):
        sync_db.sync_para_fly(force_sync=True, db_local=db)
    flyctl["upload"].assert_not_called()


def test_sync_aborta_se_export_de_producao_devolve_erro_http(tmp_path, producao_com, flyctl):
    producao_com(status=503)
    db = _banco_local(tmp_path, 50)

    with pytest.raises(sync_db.SyncAbortado, match="contar as pesquisas de produção"):
        sync_db.sync_para_fly(force_sync=True, db_local=db)
    flyctl["upload"].assert_not_called()


def test_sync_confirmado_com_local_em_dia_segue_para_o_upload(tmp_path, producao_com, flyctl):
    """A trava não pode bloquear o caso legítimo: local >= produção."""
    producao_com(n_pesquisas=3)
    db = _banco_local(tmp_path, 3)

    assert sync_db.sync_para_fly(force_sync=True, db_local=db) is True
    flyctl["upload"].assert_called_once_with(db)


def test_cli_sem_force_sync_sai_com_erro(producao_com, flyctl, caplog):
    """`python scripts/sync_db.py` sem a flag não sincroniza nada e sai != 0.
    Chama main() no próprio processo: um subprocesso escaparia do bloqueio
    de rede e do load_dotenv neutralizado do conftest."""
    get = producao_com(n_pesquisas=1)
    with caplog.at_level("ERROR", logger=sync_db.logger.name):
        codigo = sync_db.main([])

    assert codigo != 0
    assert "--force-sync" in caplog.text
    get.assert_not_called()
    flyctl["run"].assert_not_called()
    flyctl["upload"].assert_not_called()


def test_coleta_local_nao_chama_sync(monkeypatch):
    """run_all_collectors fora do Fly, com dado novo, não pode sincronizar:
    produção é a fonte da verdade desde que a coleta migrou para o Fly."""
    import app as app_mod

    if os.path.exists(database.DB_PATH):
        os.remove(database.DB_PATH)
    database.init_db()

    class ColetorQueGravaUmaPesquisa:
        def __init__(self, db_path):
            self.db_path = db_path

        def run(self):
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute(
                "INSERT INTO pesquisas (instituto_id, cargo, data_pesquisa, data_publicacao, "
                "tamanho_amostra, margem_erro, registro_tse) "
                "VALUES (1, 'presidente', '2030-01-01', '2030-01-02', 1000, 2.0, 'SYNC-TESTE')")
            conn.execute("INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) "
                         "VALUES (?, 'Lula', 40.0, 'estimulada')", (cur.lastrowid,))
            conn.commit()
            conn.close()
            return {"status": "ok", "salvas": 1, "falhas": []}

    import collectors
    monkeypatch.setattr(collectors, "ALL_COLLECTORS", [ColetorQueGravaUmaPesquisa])
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    monkeypatch.setattr("notifier.send_telegram", lambda *a, **k: None)
    sync = MagicMock(side_effect=AssertionError("coleta local chamou sync_para_fly"))
    monkeypatch.setattr(sync_db, "sync_para_fly", sync)

    resultados = app_mod.run_all_collectors()

    assert resultados == [{"coletor": "ColetorQueGravaUmaPesquisa", "status": "ok"}]
    sync.assert_not_called()
    if os.path.exists(database.DB_PATH):
        os.remove(database.DB_PATH)


def test_coletar_py_nao_chama_sync():
    """coletar.py configura um FileHandler para logs/coleta.log no import —
    importá-lo no teste sujaria o log real. A garantia aqui é estática."""
    fonte = (RAIZ / "coletar.py").read_text(encoding="utf-8")
    assert "sync_para_fly" not in fonte
