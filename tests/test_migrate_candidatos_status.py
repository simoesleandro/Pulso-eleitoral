import os
# Configura o ambiente de testes antes de importar os módulos do projeto
os.environ['TESTING'] = 'True'

import sqlite3
from datetime import date, timedelta

import pytest

import database
from database import (
    get_conn, init_db, DB_PATH,
    get_pesquisas_mais_recentes, get_historico_candidato, get_media_agregada,
)
import scripts.migrate_candidatos_status as migrate_candidatos_status
from scripts.migrate_candidatos_status import aplicar_migracao


def _preparar_banco_sem_migracao():
    """Roda schema.sql + popula candidatos SEM aplicar a migration de status
    (estado "pré-migração"), para simular corrida entre processos que hoje
    passam por init_db() (que já roda a migration automaticamente)."""
    if not os.path.exists(database.DATA_DIR):
        os.makedirs(database.DATA_DIR, exist_ok=True)
    conn = get_conn()
    with open(os.path.join(database.BASE_DIR, 'schema.sql'), 'r', encoding='utf-8') as f:
        conn.executescript(f.read())
    conn.commit()
    database._popular_candidatos(conn)
    return conn


@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Garante que o banco de dados de testes seja limpo antes e depois de cada teste."""
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass

    yield

    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass


def _criar_pesquisa(conn, cargo, data_pesquisa, candidatos_percentuais):
    """Insere instituto + pesquisa + intenções de teste (1 poll, N candidatos) e retorna o id da pesquisa.

    `candidatos_percentuais` é uma lista de tuplas (candidato, percentual).
    """
    cursor = conn.cursor()
    cursor.execute(
        # agregar=1: instituto de teste precisa entrar na média (curadoria).
        "INSERT INTO institutos (nome, sigla, site, agregar) VALUES (?, ?, ?, 1)",
        ("Instituto Teste", "IT", "http://teste.com")
    )
    instituto_id = cursor.lastrowid
    cursor.execute(
        """INSERT INTO pesquisas
           (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (instituto_id, cargo, data_pesquisa, data_pesquisa, 1000, 2.0, "Contratante Teste",
         f"BR-{instituto_id}-{data_pesquisa}", "http://fonte.com")
    )
    pesquisa_id = cursor.lastrowid
    cursor.executemany(
        "INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES (?, ?, ?, ?, ?)",
        [(pesquisa_id, candidato, "Partido Teste", percentual, "estimulada")
         for candidato, percentual in candidatos_percentuais]
    )
    conn.commit()
    return pesquisa_id


def test_migracao_e_idempotente():
    """A migration pode rodar 2x sem erro e sem duplicar colunas."""
    init_db(force_seed=False)
    conn = get_conn()

    aplicar_migracao(conn)
    aplicar_migracao(conn)  # segunda execução não deve levantar exceção

    colunas = [row[1] for row in conn.execute("PRAGMA table_info(candidatos)").fetchall()]
    assert colunas.count("status") == 1
    assert colunas.count("data_status") == 1

    row = conn.execute(
        "SELECT status, data_status FROM candidatos WHERE nome_canonico = ?", ("Cláudio Castro",)
    ).fetchone()
    assert row["status"] == "inelegivel"
    assert row["data_status"] == "2026-03-24"

    conn.close()


def test_candidato_inelegivel_nao_aparece_na_lista_ativa():
    """Candidato com status='inelegivel' não aparece na lista de candidatos ativos (corrida atual)."""
    init_db(force_seed=False)
    conn = get_conn()
    aplicar_migracao(conn)

    # Data posterior a toda pesquisa do seed.sql (última é 2026-06-05), para
    # garantir que esta é a pesquisa "mais recente" considerada pela query.
    # Ambos os candidatos no mesmo poll, como numa pesquisa real.
    _criar_pesquisa(conn, "governador_rj", "2026-06-20", [
        ("Cláudio Castro", 20.0),
        ("Eduardo Paes", 40.0),
    ])
    conn.close()

    rows = get_pesquisas_mais_recentes("governador_rj")
    nomes = [r["candidato"] for r in rows]

    assert "Cláudio Castro" not in nomes
    assert "Eduardo Paes" in nomes


def test_candidato_inelegivel_continua_no_historico():
    """Candidato inelegível continua aparecendo em queries de histórico/trend
    para o período anterior à mudança de status."""
    init_db(force_seed=False)
    conn = get_conn()
    aplicar_migracao(conn)

    # Pesquisa de antes da inelegibilidade (declarada em 2026-03-24)
    _criar_pesquisa(conn, "governador_rj", "2026-02-15", [("Cláudio Castro", 30.0)])
    conn.close()

    historico = get_historico_candidato("Cláudio Castro")

    # seed.sql já popula pesquisas históricas do Castro (fev-abr/2026); a query
    # de histórico não deve filtrar por status, então nosso registro de teste
    # (2026-02-15) precisa estar presente junto com os demais.
    assert any(
        r["data"] == "2026-02-15" and r["percentual"] == 30.0 and r["instituto"] == "Instituto Teste"
        for r in historico
    )
    assert len(historico) > 1


def test_migracao_resiliente_a_race_condition(monkeypatch):
    """Se outro processo/machine já adicionou a coluna entre o PRAGMA
    table_info (checagem) e o ALTER TABLE — cenário possível no Fly.io com
    mais de uma machine chamando init_db() ao mesmo tempo — a migration não
    deve quebrar."""
    conn = _preparar_banco_sem_migracao()

    # Simula que outro processo já ganhou a corrida e adicionou a coluna...
    conn.execute("ALTER TABLE candidatos ADD COLUMN status TEXT NOT NULL DEFAULT 'ativo'")
    conn.commit()

    # ...mas a checagem local (_colunas_existentes) ainda não via isso,
    # forçando o código a tentar o ALTER TABLE de qualquer forma.
    monkeypatch.setattr(migrate_candidatos_status, "_colunas_existentes", lambda conn, tabela: set())

    aplicar_migracao(conn)  # não deve levantar sqlite3.OperationalError

    colunas = [row[1] for row in conn.execute("PRAGMA table_info(candidatos)").fetchall()]
    assert colunas.count("status") == 1  # não duplicou a coluna
    assert colunas.count("data_status") == 1

    conn.close()


def test_migracao_propaga_erro_nao_relacionado_a_duplicidade(monkeypatch):
    """Um OperationalError diferente de 'duplicate column name' (ex.: erro de
    sintaxe real na definição da coluna) não deve ser engolido."""
    conn = _preparar_banco_sem_migracao()

    # Força o caminho do ALTER TABLE (finge que a coluna não existe)...
    monkeypatch.setattr(migrate_candidatos_status, "_colunas_existentes", lambda conn, tabela: set())
    # ...com uma definição de coluna sintaticamente inválida, gerando um
    # OperationalError que NÃO é "duplicate column name".
    monkeypatch.setattr(
        migrate_candidatos_status, "_COLUNAS_NOVAS",
        [("status", "TEXT DEFAULT")]
    )

    with pytest.raises(sqlite3.OperationalError) as exc_info:
        aplicar_migracao(conn)
    assert "duplicate column name" not in str(exc_info.value)

    conn.close()


def test_media_agregada_exclui_candidato_inelegivel_mesmo_dentro_da_janela():
    """get_media_agregada() não deve incluir candidato com status != 'ativo',
    mesmo que a pesquisa esteja dentro dos últimos 30 dias."""
    init_db(force_seed=False)
    conn = get_conn()
    aplicar_migracao(conn)  # Cláudio Castro fica status='inelegivel'

    data_a = (date.today() - timedelta(days=10)).isoformat()
    data_b = (date.today() - timedelta(days=5)).isoformat()
    _criar_pesquisa(conn, "governador_rj", data_a, [("Cláudio Castro", 20.0), ("Eduardo Paes", 40.0)])
    _criar_pesquisa(conn, "governador_rj", data_b, [("Cláudio Castro", 22.0), ("Eduardo Paes", 42.0)])
    conn.close()

    resultado = get_media_agregada("governador_rj", dias=30)
    nomes = [c["candidato"] for c in resultado["candidatos"]]

    assert "Cláudio Castro" not in nomes


def test_media_agregada_inclui_candidato_ativo_normalmente():
    """get_media_agregada() continua incluindo normalmente candidatos com
    status='ativo' dentro da janela de dias."""
    init_db(force_seed=False)
    conn = get_conn()
    aplicar_migracao(conn)

    data_a = (date.today() - timedelta(days=10)).isoformat()
    data_b = (date.today() - timedelta(days=5)).isoformat()
    _criar_pesquisa(conn, "governador_rj", data_a, [("Cláudio Castro", 20.0), ("Eduardo Paes", 40.0)])
    _criar_pesquisa(conn, "governador_rj", data_b, [("Cláudio Castro", 22.0), ("Eduardo Paes", 42.0)])
    conn.close()

    resultado = get_media_agregada("governador_rj", dias=30)
    nomes = [c["candidato"] for c in resultado["candidatos"]]

    assert "Eduardo Paes" in nomes
