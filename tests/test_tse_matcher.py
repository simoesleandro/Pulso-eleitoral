import os
os.environ['TESTING'] = 'True'

import sqlite3

from scripts.migrate_pesquisas_tse import aplicar_migracao
from tse.matcher import casar


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE institutos (
        id INTEGER PRIMARY KEY, nome TEXT)""")
    conn.execute("""CREATE TABLE pesquisas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, instituto_id INTEGER, cargo TEXT,
        data_pesquisa TEXT, data_publicacao TEXT, tamanho_amostra INTEGER,
        margem_erro REAL, registro_tse TEXT UNIQUE, fonte_url TEXT)""")
    aplicar_migracao(conn)
    conn.execute("INSERT INTO institutos (id, nome, cnpj) VALUES (1, 'Quaest', '11111111000111')")
    conn.commit()
    return conn


def _tse(conn, protocolo, inicio, fim, divulgacao, amostra=1200, cnpj="11111111000111"):
    conn.execute("""INSERT INTO pesquisas_tse
        (protocolo, cargo, cnpj_empresa, nome_empresa, data_inicio, data_fim,
         data_divulgacao, qt_entrevistado, abrangencia)
        VALUES (?, 'presidente', ?, 'QUAEST', ?, ?, ?, ?, 'nacional')""",
        (protocolo, cnpj, inicio, fim, divulgacao, amostra))
    conn.commit()


def _pesquisa(conn, data, amostra=0, registro="GEN-x"):
    cur = conn.execute("""INSERT INTO pesquisas
        (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra,
         margem_erro, registro_tse, fonte_url)
        VALUES (1, 'presidente', ?, ?, ?, 2.0, ?, 'http://x')""",
        (data, data, amostra, registro))
    conn.commit()
    return cur.lastrowid


def test_casa_pesquisa_dentro_da_janela():
    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05")
    pid = _pesquisa(conn, "2026-07-05", amostra=0)

    resultado = casar(conn, cargo="presidente")

    assert len(resultado["casados"]) == 1
    par = resultado["casados"][0]
    assert par["protocolo"] == "BR000012026"
    assert par["pesquisa_id"] == pid
    assert par["amostra_tse"] == 1200
    conn.close()


def test_dry_run_nao_grava():
    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05")
    _pesquisa(conn, "2026-07-05")

    casar(conn, cargo="presidente", dry_run=True)

    ligado = conn.execute(
        "SELECT pesquisa_id FROM pesquisas_tse WHERE protocolo = ?",
        ("BR000012026",)).fetchone()["pesquisa_id"]
    assert ligado is None, "dry_run não pode escrever no banco"
    conn.close()


def test_apply_grava_e_faz_backfill():
    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05", amostra=2004)
    pid = _pesquisa(conn, "2026-07-05", amostra=0)

    casar(conn, cargo="presidente", dry_run=False)

    tse = conn.execute("SELECT pesquisa_id FROM pesquisas_tse WHERE protocolo = ?",
                       ("BR000012026",)).fetchone()
    pesquisa = conn.execute(
        "SELECT tamanho_amostra, data_pesquisa, registro_tse FROM pesquisas WHERE id = ?",
        (pid,)).fetchone()

    assert tse["pesquisa_id"] == pid
    assert pesquisa["tamanho_amostra"] == 2004, "amostra deve vir do TSE"
    assert pesquisa["data_pesquisa"] == "2026-07-03", "data de campo = DT_FIM_PESQUISA"
    assert pesquisa["registro_tse"] == "BR000012026", "protocolo real substitui a chave GEN-"
    conn.close()


def test_ambiguidade_nao_casa():
    """Dois registros do mesmo instituto na mesma janela: não adivinhar."""
    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05")
    _tse(conn, "BR000022026", "2026-07-02", "2026-07-04", "2026-07-05")
    _pesquisa(conn, "2026-07-05")

    resultado = casar(conn, cargo="presidente", dry_run=False)

    assert resultado["casados"] == []
    assert len(resultado["ambiguos"]) >= 1
    restantes = conn.execute(
        "SELECT COUNT(*) FROM pesquisas_tse WHERE pesquisa_id IS NOT NULL").fetchone()[0]
    assert restantes == 0, "par ambíguo nunca pode ser gravado"
    conn.close()


def test_fora_da_janela_nao_casa():
    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05")
    _pesquisa(conn, "2026-06-01")

    resultado = casar(conn, cargo="presidente", dry_run=False)

    assert resultado["casados"] == []
    assert resultado["sem_par"] == 1
    conn.close()


def test_instituto_diferente_nao_casa():
    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05",
         cnpj="99999999000199")
    _pesquisa(conn, "2026-07-05")

    resultado = casar(conn, cargo="presidente", dry_run=False)

    assert resultado["casados"] == []
    conn.close()


def test_instituto_sem_cnpj_nao_casa():
    """Instituto sem CNPJ cadastrado não pode casar por acidente (NULL = NULL)."""
    conn = _conn()
    conn.execute("UPDATE institutos SET cnpj = NULL WHERE id = 1")
    conn.commit()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05", cnpj="")
    _pesquisa(conn, "2026-07-05")

    resultado = casar(conn, cargo="presidente", dry_run=False)

    assert resultado["casados"] == []
    conn.close()


def test_aplicar_ligacao_isolada():
    """A ligação é reusável fora do casamento automático (ligação manual)."""
    from tse.matcher import aplicar_ligacao

    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05", amostra=2004)
    pid = _pesquisa(conn, "2026-07-05", amostra=0)

    aplicar_ligacao(conn, protocolo="BR000012026", pesquisa_id=pid,
                    amostra_tse=2004, data_fim="2026-07-03")
    conn.commit()

    tse = conn.execute("SELECT pesquisa_id FROM pesquisas_tse WHERE protocolo = ?",
                       ("BR000012026",)).fetchone()
    pesquisa = conn.execute(
        "SELECT tamanho_amostra, data_pesquisa, registro_tse FROM pesquisas WHERE id = ?",
        (pid,)).fetchone()

    assert tse["pesquisa_id"] == pid
    assert pesquisa["tamanho_amostra"] == 2004
    assert pesquisa["data_pesquisa"] == "2026-07-03"
    assert pesquisa["registro_tse"] == "BR000012026"
    conn.close()


def test_aplicar_ligacao_preserva_amostra_realizada():
    """Mesma regra do casamento automático, agora na função extraída."""
    from tse.matcher import aplicar_ligacao

    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05", amostra=2000)
    pid = _pesquisa(conn, "2026-07-05", amostra=2003)

    aplicar_ligacao(conn, protocolo="BR000012026", pesquisa_id=pid,
                    amostra_tse=2000, data_fim="2026-07-03")
    conn.commit()

    amostra = conn.execute(
        "SELECT tamanho_amostra FROM pesquisas WHERE id = ?", (pid,)).fetchone()[0]
    assert amostra == 2003
    conn.close()


def test_backfill_nao_sobrescreve_amostra_realizada():
    """O TSE guarda a amostra registrada (planejada); o release publica a
    realizada. Visto em produção: 2000 registrado vs 2003 realizado."""
    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05", amostra=2000)
    pid = _pesquisa(conn, "2026-07-05", amostra=2003)

    casar(conn, cargo="presidente", dry_run=False)

    amostra = conn.execute(
        "SELECT tamanho_amostra FROM pesquisas WHERE id = ?", (pid,)).fetchone()[0]
    assert amostra == 2003, "amostra realizada não pode ser sobrescrita pela registrada"
