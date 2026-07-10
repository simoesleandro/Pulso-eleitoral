import os
os.environ['TESTING'] = 'True'

from datetime import date
from database import (
    init_db, get_conn, get_confronto_2turno_real, get_simulacao_segundo_turno,
)


def _limpa():
    conn = get_conn()
    conn.execute("DELETE FROM confrontos_2turno")
    conn.commit()
    conn.close()


def _insere(conn, inst, a, b, pa, pb, data, amostra=2000, cargo='presidente'):
    conn.execute(
        "INSERT OR REPLACE INTO confrontos_2turno "
        "(instituto_id, cargo, candidato_a, candidato_b, pct_a, pct_b, data_pesquisa, tamanho_amostra) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (inst, cargo, a, b, pa, pb, data, amostra),
    )


def test_migracao_cria_tabela_confrontos():
    """init_db cria a tabela confrontos_2turno com as colunas esperadas."""
    init_db()
    conn = get_conn()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(confrontos_2turno)")}
    conn.close()
    assert {'candidato_a', 'candidato_b', 'pct_a', 'pct_b', 'cargo'} <= cols


def test_confronto_real_orienta_par_independente_da_ordem():
    """O par é casado nas duas ordens e orientado para (a=nome_a, b=nome_b)."""
    init_db()
    _limpa()
    hoje = date.today().isoformat()
    conn = get_conn()
    _insere(conn, 1, 'Lula', 'Flávio Bolsonaro', 48.0, 46.0, hoje)   # ordem A=Lula
    _insere(conn, 2, 'Flávio Bolsonaro', 'Lula', 44.0, 50.0, hoje)   # ordem trocada
    conn.commit()
    conn.close()

    r = get_confronto_2turno_real('Lula', 'Flávio Bolsonaro')
    _limpa()
    assert r is not None
    assert r['n_institutos'] == 2
    # amostras e datas iguais → média simples: Lula (48+50)/2, Flávio (46+44)/2
    assert r['a'] == 49.0
    assert r['b'] == 45.0


def test_confronto_real_vazio_retorna_none():
    """Sem linhas na janela, retorna None (chamador cai na simulação)."""
    init_db()
    _limpa()
    assert get_confronto_2turno_real('Lula', 'Flávio Bolsonaro') is None


def test_simulacao_usa_dado_real_quando_existe():
    """Havendo confronto real na janela, get_simulacao_segundo_turno usa ele
    (fonte='pesquisas') em vez da redistribuição simulada."""
    init_db()
    _limpa()
    conn = get_conn()
    _insere(conn, 1, 'Lula', 'Flávio Bolsonaro', 47.0, 45.0, date.today().isoformat())
    conn.commit()
    conn.close()

    sim = get_simulacao_segundo_turno()
    _limpa()
    st = sim['segundo_turno']
    assert st['fonte'] == 'pesquisas'
    assert st['lula']['total_estimado'] == 47.0
    assert st['flavio']['total_estimado'] == 45.0
    assert st['lula']['vencedor'] is True


def test_simulacao_cai_na_simulacao_sem_dado_real():
    """Sem confronto real, mantém o comportamento legado (fonte='simulacao')."""
    init_db()
    _limpa()
    sim = get_simulacao_segundo_turno()
    st = sim['segundo_turno']
    assert st['fonte'] == 'simulacao'
    assert 'nota' in st
    assert 'total_estimado' in st['lula'] and 'total_estimado' in st['flavio']


def test_save_persiste_confrontos_2turno(tmp_path):
    """base.save grava os confrontos_2turno anexados ao primeiro item do grupo,
    num banco temporário isolado (sem tocar o pulso_test.db compartilhado)."""
    import os as _os
    import sqlite3
    from collectors.cnn_brasil import CnnBrasilColetor

    db = str(tmp_path / "t.db")
    base_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    conn = sqlite3.connect(db)
    with open(_os.path.join(base_dir, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    # Colunas que vêm de migration (não estão no schema.sql base)
    from scripts.migrate_pesquisas_volatilidade import aplicar_migracao as _mig_vol
    _mig_vol(conn)
    conn.execute("INSERT INTO institutos (id, nome, sigla, site) VALUES (3, 'Quaest', 'Q', 'http://q')")
    conn.commit()
    conn.close()

    col = CnnBrasilColetor(db_path=db)
    itens = [{
        "instituto_id": 3, "cargo": "presidente", "candidato": "Lula", "percentual": 40.0,
        "tipo": "estimulada", "data_pesquisa": "2026-07-05", "data_coleta": "2026-07-05",
        "fonte_url": "http://x/1", "tamanho_amostra": 2000,
        "confrontos_2turno": [
            {"candidato_a": "Lula", "candidato_b": "Flávio Bolsonaro", "pct_a": 48.0, "pct_b": 46.0},
        ],
    }]
    res = col.save(itens)
    assert res["pesquisas"] == 1

    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT candidato_a, candidato_b, pct_a, pct_b, cargo FROM confrontos_2turno"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "Lula" and rows[0][1] == "Flávio Bolsonaro"
    assert rows[0][2] == 48.0 and rows[0][3] == 46.0
    assert rows[0][4] == "presidente"
