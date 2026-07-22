import os
os.environ['TESTING'] = 'True'

import sqlite3

# Ver tests/test_cobertura.py: entrar por db.* direto pega db.core
# parcialmente inicializado. A façade é o ponto de entrada.
import database  # noqa: F401
from db.curadoria import ligar_manual
from scripts.migrate_pesquisas_tse import aplicar_migracao


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT, sigla TEXT, agregar INTEGER DEFAULT 1)")
    conn.execute("""CREATE TABLE pesquisas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, instituto_id INTEGER, cargo TEXT,
        data_pesquisa TEXT, data_publicacao TEXT, tamanho_amostra INTEGER,
        margem_erro REAL, registro_tse TEXT UNIQUE, fonte_url TEXT)""")
    aplicar_migracao(conn)
    conn.execute("INSERT INTO institutos (id, nome, cnpj) VALUES (1, 'Quaest', '111')")
    conn.commit()
    return conn


def _reg(conn, protocolo, cargo="presidente", pesquisa_id=None, cnpj="111",
         empresa="QUAEST"):
    conn.execute("""INSERT INTO pesquisas_tse
        (protocolo, cargo, cnpj_empresa, nome_empresa, data_inicio, data_fim,
         data_divulgacao, qt_entrevistado, abrangencia, pesquisa_id)
        VALUES (?, ?, ?, ?, '2026-07-01', '2026-07-03',
                '2026-07-05', 2004, 'nacional', ?)""",
        (protocolo, cargo, cnpj, empresa, pesquisa_id))
    conn.commit()


def _pesquisa(conn, cargo="presidente", registro="GEN-1", amostra=0):
    cur = conn.execute("""INSERT INTO pesquisas
        (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra,
         margem_erro, registro_tse, fonte_url)
        VALUES (1, ?, '2026-07-10', '2026-07-10', ?, 2.0, ?, 'http://x')""",
        (cargo, amostra, registro))
    conn.commit()
    return cur.lastrowid


def test_ligacao_feliz():
    conn = _conn()
    _reg(conn, "BR001")
    pid = _pesquisa(conn)

    resultado = ligar_manual(conn, "BR001", pid)

    assert resultado["ok"] is True
    linha = conn.execute(
        "SELECT tamanho_amostra, data_pesquisa, registro_tse FROM pesquisas WHERE id = ?",
        (pid,)).fetchone()
    assert linha["tamanho_amostra"] == 2004
    assert linha["data_pesquisa"] == "2026-07-03"
    assert linha["registro_tse"] == "BR001"
    conn.close()


def test_recusa_protocolo_ja_ligado():
    conn = _conn()
    outra = _pesquisa(conn, registro="GEN-outra")
    _reg(conn, "BR001", pesquisa_id=outra)
    pid = _pesquisa(conn, registro="GEN-nova")

    resultado = ligar_manual(conn, "BR001", pid)

    assert resultado["ok"] is False
    assert "já está ligado" in resultado["erro"]
    conn.close()


def test_recusa_pesquisa_ja_ligada_a_outro_protocolo():
    conn = _conn()
    pid = _pesquisa(conn)
    _reg(conn, "BR001", pesquisa_id=pid)
    _reg(conn, "BR002")

    resultado = ligar_manual(conn, "BR002", pid)

    assert resultado["ok"] is False
    assert "já está ligada" in resultado["erro"]
    conn.close()


def test_recusa_cargo_divergente():
    """Registro de governador não pode ser ligado a pesquisa de presidente."""
    conn = _conn()
    _reg(conn, "RJ001", cargo="governador_rj")
    pid = _pesquisa(conn, cargo="presidente")

    resultado = ligar_manual(conn, "RJ001", pid)

    assert resultado["ok"] is False
    assert "cargo" in resultado["erro"].lower()
    conn.close()


def test_recusa_protocolo_inexistente():
    conn = _conn()
    pid = _pesquisa(conn)

    resultado = ligar_manual(conn, "NAOEXISTE", pid)

    assert resultado["ok"] is False
    assert "não encontrado" in resultado["erro"]
    conn.close()


def test_recusa_pesquisa_inexistente():
    conn = _conn()
    _reg(conn, "BR001")

    resultado = ligar_manual(conn, "BR001", 9999)

    assert resultado["ok"] is False
    assert "não encontrada" in resultado["erro"]
    conn.close()


def test_recusa_nao_deixa_efeito_parcial():
    conn = _conn()
    _reg(conn, "RJ001", cargo="governador_rj")
    pid = _pesquisa(conn, cargo="presidente")

    ligar_manual(conn, "RJ001", pid)

    ligado = conn.execute(
        "SELECT pesquisa_id FROM pesquisas_tse WHERE protocolo = 'RJ001'").fetchone()[0]
    registro = conn.execute(
        "SELECT registro_tse FROM pesquisas WHERE id = ?", (pid,)).fetchone()[0]
    assert ligado is None
    assert registro == "GEN-1", "recusa não pode ter escrito nada"
    conn.close()


# ─── Curadoria de instituto descoberto ──────────────────────────────────────

def test_aprovar_instituto_cria_linha_agregada():
    from db.curadoria import avaliar_instituto

    conn = _conn()
    _reg(conn, "X1", cnpj="999", empresa="VETOR ARROW LTDA")

    resultado = avaliar_instituto(conn, cnpj="999",
                                  nome_exibicao="Vetor Arrow", aprovar=True)

    assert resultado["ok"] is True
    linha = conn.execute(
        "SELECT nome, agregar FROM institutos WHERE cnpj = '999'").fetchone()
    assert linha["nome"] == "Vetor Arrow", "nome de exibição, não razão social"
    assert linha["agregar"] == 1
    conn.close()


def test_rejeitar_instituto_cria_linha_fora_do_agregado():
    conn = _conn()
    from db.curadoria import avaliar_instituto

    resultado = avaliar_instituto(conn, cnpj="999",
                                  nome_exibicao="Instituto Qualquer", aprovar=False)

    assert resultado["ok"] is True
    agregar = conn.execute(
        "SELECT agregar FROM institutos WHERE cnpj = '999'").fetchone()[0]
    assert agregar == 0
    conn.close()


def test_avaliar_instituto_ja_cadastrado_e_recusado():
    from db.curadoria import avaliar_instituto

    conn = _conn()  # já tem Quaest com cnpj 111
    resultado = avaliar_instituto(conn, cnpj="111",
                                  nome_exibicao="Duplicata", aprovar=True)

    assert resultado["ok"] is False
    assert "já cadastrado" in resultado["erro"]
    total = conn.execute(
        "SELECT COUNT(*) FROM institutos WHERE cnpj = '111'").fetchone()[0]
    assert total == 1
    conn.close()


def test_avaliar_exige_nome_de_exibicao():
    from db.curadoria import avaliar_instituto

    conn = _conn()
    resultado = avaliar_instituto(conn, cnpj="999", nome_exibicao="  ",
                                  aprovar=True)

    assert resultado["ok"] is False
    assert "nome" in resultado["erro"].lower()
    conn.close()
