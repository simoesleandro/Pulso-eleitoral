import os
os.environ['TESTING'] = 'True'

import sqlite3
from datetime import date, timedelta

import database
from database import detectar_variacoes_bruscas

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pesquisa(conn, inst_id, data_pesq, tag):
    cur = conn.execute(
        "INSERT INTO pesquisas (instituto_id, cargo, data_pesquisa, data_publicacao, "
        "tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) "
        "VALUES (?, 'presidente', ?, ?, 2000, 2.0, 'X', ?, ?)",
        (inst_id, data_pesq, data_pesq, f"TSE-{tag}", f"http://x/{tag}"),
    )
    return cur.lastrowid


def _seed(dbpath):
    """Dois institutos, ambos com pesquisa recente na MESMA data máxima e uma
    anterior fora da janela — dois pares (recente, anterior) para 'Lula', com
    |Δ| diferente (Inst A: 4pp; Inst B: 8pp)."""
    conn = sqlite3.connect(dbpath)
    with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    from scripts.migrate_pesquisas_volatilidade import aplicar_migracao as _mig
    _mig(conn)

    conn.execute("INSERT INTO institutos (id, nome, sigla, site, agregar) VALUES (1, 'Inst A', 'A', 'http://a', 1)")
    conn.execute("INSERT INTO institutos (id, nome, sigla, site, agregar) VALUES (2, 'Inst B', 'B', 'http://b', 1)")

    hoje = date.today()
    d_rec = hoje.isoformat()
    d_ant = (hoje - timedelta(days=40)).isoformat()  # fora da janela de 30 dias

    # Inst A: 40 -> 44 (delta 4)
    pa_ant = _pesquisa(conn, 1, d_ant, "a-ant")
    pa_rec = _pesquisa(conn, 1, d_rec, "a-rec")
    conn.execute("INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) VALUES (?, 'Lula', 40.0, 'estimulada')", (pa_ant,))
    conn.execute("INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) VALUES (?, 'Lula', 44.0, 'estimulada')", (pa_rec,))

    # Inst B: 30 -> 38 (delta 8) — este é o maior |Δ| e deve ser o reportado
    pb_ant = _pesquisa(conn, 2, d_ant, "b-ant")
    pb_rec = _pesquisa(conn, 2, d_rec, "b-rec")
    conn.execute("INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) VALUES (?, 'Lula', 30.0, 'estimulada')", (pb_ant,))
    conn.execute("INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) VALUES (?, 'Lula', 38.0, 'estimulada')", (pb_rec,))

    conn.commit()
    conn.close()


def test_reporta_par_de_maior_delta(tmp_path, monkeypatch):
    """Com dois pares qualificados para o mesmo candidato, o alerta reporta o de
    MAIOR |Δ| com pct/instituto/datas coerentes entre si (regressão do GROUP BY
    que escolhia uma linha arbitrária)."""
    db = str(tmp_path / "t.db")
    _seed(db)
    monkeypatch.setattr(database, 'DB_PATH', db)

    alertas = detectar_variacoes_bruscas(cargo='presidente', limiar_pp=3.0, janela_dias=30)

    lula = [a for a in alertas if a['candidato'] == 'Lula']
    assert len(lula) == 1, "deve haver exatamente 1 alerta por candidato"
    a = lula[0]
    # O par de maior |Δ| é o do Inst B (30 -> 38 = 8pp)
    assert a['percentual_atual'] == 38.0
    assert a['percentual_anterior'] == 30.0
    assert a['variacao'] == 8.0
    assert a['direcao'] == 'up'
    assert a['instituto_atual'] == 'Inst B'
    assert a['instituto_anterior'] == 'Inst B'


def test_par_unico_inalterado(tmp_path, monkeypatch):
    """Caso simples (um par por candidato) segue reportando corretamente."""
    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    from scripts.migrate_pesquisas_volatilidade import aplicar_migracao as _mig
    _mig(conn)
    conn.execute("INSERT INTO institutos (id, nome, sigla, site, agregar) VALUES (1, 'Inst A', 'A', 'http://a', 1)")
    hoje = date.today()
    p_ant = _pesquisa(conn, 1, (hoje - timedelta(days=40)).isoformat(), "u-ant")
    p_rec = _pesquisa(conn, 1, hoje.isoformat(), "u-rec")
    conn.execute("INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) VALUES (?, 'Lula', 45.0, 'estimulada')", (p_ant,))
    conn.execute("INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) VALUES (?, 'Lula', 41.0, 'estimulada')", (p_rec,))
    conn.commit()
    conn.close()

    monkeypatch.setattr(database, 'DB_PATH', db)
    alertas = detectar_variacoes_bruscas(cargo='presidente', limiar_pp=3.0, janela_dias=30)
    lula = [a for a in alertas if a['candidato'] == 'Lula']
    assert len(lula) == 1
    assert lula[0]['variacao'] == -4.0
    assert lula[0]['direcao'] == 'down'
