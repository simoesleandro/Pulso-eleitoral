import os
os.environ['TESTING'] = 'True'

import sqlite3

import pytest

import database
from database import _popular_candidatos
from scripts.migrate_candidatos_status import aplicar_migracao as _migrar_status
from scripts.migrate_unificar_apelidos import main, unificar_apelidos


def _conn(com_roster=True):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open(os.path.join(database.BASE_DIR, 'schema.sql'), encoding='utf-8') as f:
        conn.executescript(f.read())
    _migrar_status(conn)
    if com_roster:
        _popular_candidatos(conn)
    conn.execute("INSERT INTO institutos (id, nome) VALUES (1, 'Instituto Teste')")
    conn.commit()
    return conn


def _pesquisa(conn, registro, intencoes, tipo="estimulada", cargo="governador_rj"):
    pid = conn.execute(
        "INSERT INTO pesquisas (instituto_id, cargo, data_pesquisa, data_publicacao, "
        "tamanho_amostra, margem_erro, registro_tse) VALUES (1, ?, '2026-07-01', "
        "'2026-07-02', 1000, 3.0, ?)", (cargo, registro)).lastrowid
    for nome, pct in intencoes.items():
        conn.execute("INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) "
                     "VALUES (?, ?, ?, ?)", (pid, nome, pct, tipo))
    conn.commit()
    return pid


def _candidatos(conn):
    return sorted(r[0] for r in conn.execute("SELECT candidato FROM intencoes"))


def test_duas_grafias_do_mesmo_candidato_viram_uma_serie_so():
    conn = _conn()
    _pesquisa(conn, "RJ-1", {"Garotinho": 11.0, "EDUARDO PAES": 40.0})
    _pesquisa(conn, "RJ-2", {"Anthony Garotinho": 12.0, "Eduardo Paes": 41.0})
    _pesquisa(conn, "RJ-3", {"garotinho": 10.0})

    relatorio = unificar_apelidos(conn, aplicar=True)

    assert _candidatos(conn) == ["Anthony Garotinho"] * 3 + ["Eduardo Paes"] * 2
    assert relatorio["total"] == 3
    assert {(m["de"], m["para"], m["linhas"]) for m in relatorio["mudancas"]} == {
        ("Garotinho", "Anthony Garotinho", 1),
        ("garotinho", "Anthony Garotinho", 1),
        ("EDUARDO PAES", "Eduardo Paes", 1),
    }


def test_rodar_duas_vezes_nao_altera_nada_na_segunda():
    conn = _conn()
    _pesquisa(conn, "RJ-1", {"Garotinho": 11.0})
    _pesquisa(conn, "RJ-2", {"Anthony Garotinho": 12.0})

    unificar_apelidos(conn, aplicar=True)
    depois_da_primeira = [tuple(r) for r in conn.execute("SELECT * FROM intencoes ORDER BY id")]
    segunda = unificar_apelidos(conn, aplicar=True)

    assert segunda["total"] == 0 and segunda["mudancas"] == []
    assert [tuple(r) for r in conn.execute("SELECT * FROM intencoes ORDER BY id")] == depois_da_primeira


def test_nomes_fora_do_mapa_e_candidatos_inativos_nao_sao_tocados():
    conn = _conn()
    _pesquisa(conn, "BR-1", {
        "Clariana Barao": 1.0,       # fora do roster
        "Branco/Nulo": 8.0,          # fora do roster
        "Jair Bolsonaro": 30.0,      # no roster com ativo=0: normalizar_nome daria None
        "jair messias bolsonaro": 2.0,
    }, cargo="presidente")

    relatorio = unificar_apelidos(conn, aplicar=True)

    assert relatorio["total"] == 0
    assert _candidatos(conn) == ["Branco/Nulo", "Clariana Barao", "Jair Bolsonaro",
                                 "jair messias bolsonaro"]


def test_dry_run_reporta_sem_gravar():
    conn = _conn()
    _pesquisa(conn, "RJ-1", {"Garotinho": 11.0})

    relatorio = unificar_apelidos(conn)

    assert relatorio["aplicado"] is False
    assert relatorio["total"] == 1
    assert _candidatos(conn) == ["Garotinho"]


def test_duas_grafias_na_mesma_pesquisa_e_tipo_nao_sao_fundidas():
    """Renomear criaria dois percentuais do mesmo candidato na mesma pesquisa.
    Não há como escolher um sem chute: fica como está e sai no relatório."""
    conn = _conn()
    pid = _pesquisa(conn, "RJ-1", {"Garotinho": 11.0, "Anthony Garotinho": 12.0})
    _pesquisa(conn, "RJ-2", {"Garotinho": 9.0})

    relatorio = unificar_apelidos(conn, aplicar=True)

    assert relatorio["total"] == 1
    assert relatorio["conflitos"] == [{"de": "Garotinho", "para": "Anthony Garotinho",
                                       "pesquisa_id": pid, "tipo": "estimulada"}]
    assert sorted(r[0] for r in conn.execute(
        "SELECT candidato FROM intencoes WHERE pesquisa_id = ?", (pid,))) == [
        "Anthony Garotinho", "Garotinho"]


def test_mesma_grafia_em_tipos_diferentes_da_mesma_pesquisa_e_unificada():
    conn = _conn()
    pid = _pesquisa(conn, "RJ-1", {"Anthony Garotinho": 12.0})
    conn.execute("INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) "
                 "VALUES (?, 'Garotinho', 3.0, 'espontanea')", (pid,))
    conn.commit()

    relatorio = unificar_apelidos(conn, aplicar=True)

    assert relatorio["conflitos"] == []
    assert _candidatos(conn) == ["Anthony Garotinho", "Anthony Garotinho"]


def test_avisa_quando_o_roster_do_banco_esta_atras_do_seed():
    """Rodar antes do deploy do FIX 1 daria um dry-run enganoso: "Garotinho"
    não estaria no mapa e pareceria não haver nada a unificar."""
    conn = _conn(com_roster=False)
    conn.execute("INSERT INTO candidatos (nome_canonico, apelidos) "
                 "VALUES ('Eduardo Paes', '[\"eduardo paes\"]')")
    conn.commit()

    relatorio = unificar_apelidos(conn)

    assert "Anthony Garotinho" in relatorio["faltam_no_roster"]
    assert "Eduardo Paes" not in relatorio["faltam_no_roster"]


def _banco_em_arquivo(tmp_path):
    caminho = str(tmp_path / "copia.db")
    origem = _conn()
    _pesquisa(origem, "RJ-1", {"Garotinho": 11.0})
    destino = sqlite3.connect(caminho)
    origem.backup(destino)
    destino.close()
    origem.close()
    return caminho


def _candidatos_do_arquivo(caminho):
    conn = sqlite3.connect(caminho)
    try:
        return [r[0] for r in conn.execute("SELECT candidato FROM intencoes")]
    finally:
        conn.close()


def test_cli_e_dry_run_por_padrao(tmp_path, capsys):
    caminho = _banco_em_arquivo(tmp_path)

    assert main(["--db", caminho]) == 0

    saida = capsys.readouterr().out
    assert "Garotinho -> Anthony Garotinho: 1" in saida
    assert "dry-run" in saida
    assert _candidatos_do_arquivo(caminho) == ["Garotinho"]


def test_cli_aplicar_grava(tmp_path):
    caminho = _banco_em_arquivo(tmp_path)

    assert main(["--db", caminho, "--aplicar"]) == 0

    assert _candidatos_do_arquivo(caminho) == ["Anthony Garotinho"]


def test_cli_recusa_banco_inexistente(tmp_path):
    """sqlite3.connect criaria um banco vazio no caminho errado e o dry-run
    diria "nada a unificar"."""
    caminho = str(tmp_path / "nao_existe.db")

    with pytest.raises(SystemExit):
        main(["--db", caminho])
    assert not os.path.exists(caminho)
