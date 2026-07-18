import os
# Configura o ambiente de testes antes de importar os módulos do projeto
os.environ['TESTING'] = 'True'

import pytest
import sqlite3
from database import get_conn, init_db, DB_PATH
from app import app as flask_app

@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Garante que o banco de dados de testes seja limpo antes e depois de cada teste."""
    # Apaga o banco de testes se ele existir antes de rodar o teste
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass
            
    yield
    
    # Limpa o banco de testes após o término do teste
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass

@pytest.fixture
def client():
    """Retorna um cliente de testes do Flask."""
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret-key'
    with flask_app.test_client() as client:
        yield client

def test_get_conn():
    """Teste 1: Verifica se get_conn retorna uma conexão SQLite válida com row_factory configurado."""
    conn = get_conn()
    assert isinstance(conn, sqlite3.Connection)
    assert conn.row_factory == sqlite3.Row
    
    # Valida se foreign keys estão habilitadas
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys")
    fk_enabled = cursor.fetchone()[0]
    assert fk_enabled == 1
    conn.close()

def test_get_conn_ativa_wal_e_busy_timeout():
    """Regressão: get_conn() deve configurar WAL + busy_timeout para reduzir
    contenção entre o scheduler e requests concorrentes."""
    conn = get_conn()
    try:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
        assert journal_mode.lower() == "wal"
        assert busy_timeout == 10000
    finally:
        conn.close()

def test_schema_creates_tables():
    """Teste 2: Verifica se o schema.sql cria corretamente todas as 6 tabelas requeridas."""
    # Inicializa apenas o esquema (sem forçar o seed)
    init_db(force_seed=False)
    
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row['name'] for row in cursor.fetchall()]
    conn.close()
    
    expected_tables = ['institutos', 'pesquisas', 'intencoes', 'eventos', 'alertas', 'analises_ia']
    for table in expected_tables:
        assert table in tables, f"Tabela '{table}' não foi criada pelo schema.sql"

def test_seed_inserts_institutos():
    """Teste 3: Verifica se o seed.sql insere os 14 institutos corretamente no banco."""
    # Inicializa o banco rodando o schema e forçando a carga do seed.sql
    init_db(force_seed=True)
    
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, sigla FROM institutos ORDER BY id")
    institutos = cursor.fetchall()
    conn.close()
    
    assert len(institutos) == 14
    nomes_esperados = [
        'Datafolha', 'Ibope/IPEC', 'Quaest', 'Genial/Quaest',
        'Atlas', 'Paraná', 'Real Time', 'Nexus/BTG Pactual', 'Verita',
        'Futura Inteligência', 'PoderData', 'Meio/Ideia', 'Vox Populi',
        'Instituto Gerp'
    ]
    for idx, nome in enumerate(nomes_esperados):
        assert institutos[idx]['nome'] == nome

def test_insert_and_read_research():
    """Teste 4: Valida a inserção e leitura de uma pesquisa e suas intenções de voto correspondentes."""
    init_db(force_seed=False)
    
    conn = get_conn()
    cursor = conn.cursor()
    
    # 1. Insere instituto
    cursor.execute(
        "INSERT INTO institutos (nome, sigla, site) VALUES (?, ?, ?)",
        ("Instituto Teste", "IT", "http://teste.com")
    )
    instituto_id = cursor.lastrowid
    
    # 2. Insere pesquisa
    cursor.execute(
        """INSERT INTO pesquisas 
           (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (instituto_id, "presidente", "2026-06-15", "2026-06-16", 1000, 3.0, "Contratante Teste", "BR-99999/2026", "http://fonte.com")
    )
    pesquisa_id = cursor.lastrowid
    
    # 3. Insere intenções de voto
    intencoes_data = [
        (pesquisa_id, "Candidato A", "Partido A", 45.5, "estimulada"),
        (pesquisa_id, "Candidato B", "Partido B", 35.0, "estimulada")
    ]
    cursor.executemany(
        "INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES (?, ?, ?, ?, ?)",
        intencoes_data
    )
    conn.commit()
    
    # 4. Lê dados de volta e verifica correspondência
    cursor.execute("SELECT * FROM pesquisas WHERE id = ?", (pesquisa_id,))
    pesquisa_row = cursor.fetchone()
    assert pesquisa_row['registro_tse'] == "BR-99999/2026"
    assert pesquisa_row['margem_erro'] == 3.0
    
    cursor.execute("SELECT * FROM intencoes WHERE pesquisa_id = ? ORDER BY percentual DESC", (pesquisa_id,))
    intencoes_rows = cursor.fetchall()
    assert len(intencoes_rows) == 2
    assert intencoes_rows[0]['candidato'] == "Candidato A"
    assert intencoes_rows[0]['percentual'] == 45.5
    assert intencoes_rows[1]['candidato'] == "Candidato B"
    assert intencoes_rows[1]['percentual'] == 35.0
    
    conn.close()

def test_auth_blocks_routes_without_login(client, monkeypatch):
    """Teste 5: Verifica se a autenticação bloqueia rotas protegidas e permite acesso a rotas livres."""
    # Define a senha admin explicitamente (não depende de .env / CI)
    monkeypatch.setenv('ADMIN_PASS', 'senha-de-teste-005')
    # Inicializa o banco de testes
    init_db(force_seed=True)
    
    # Acesso a rota livre (/api/status) deve retornar 200 OK sem necessidade de login
    response_status = client.get('/api/status')
    assert response_status.status_code == 200
    assert response_status.json["online"] is True
    assert "ultima_coleta" in response_status.json
    
    # Acesso a rota protegida (/) deve redirecionar (302) para /login
    response_root = client.get('/')
    assert response_root.status_code == 302
    assert response_root.headers['Location'].endswith('/login')
    
    # Login incorreto deve retornar 200 com mensagem de erro na tela
    response_login_fail = client.post('/login', data={'username': 'admin', 'password': 'wrongpass'})
    assert response_login_fail.status_code == 200
    assert b"Usu\xc3\xa1rio ou senha incorretos" in response_login_fail.data
    
    # Login correto deve redirecionar (302) para a raiz (/) e dar acesso
    response_login_success = client.post('/login', data={'username': 'admin', 'password': 'senha-de-teste-005'})
    assert response_login_success.status_code == 302
    assert response_login_success.headers['Location'].endswith('/')
    
    # Agora que está logado (na sessão do cliente de testes), acesso a (/) deve redirecionar (302) para /dashboard
    response_root_after = client.get('/')
    assert response_root_after.status_code == 302
    assert response_root_after.headers['Location'].endswith('/dashboard')


def test_falha_transitoria_no_cache_candidatos_nao_memoiza_vazio(monkeypatch):
    """Uma falha transitória (ex.: banco travado) ao carregar o cache de
    candidatos não deve ser memoizada para sempre — a próxima chamada deve
    tentar recarregar em vez de reutilizar o mapa vazio indefinidamente."""
    import database

    init_db(force_seed=True)
    database._cache_candidatos = None

    original_get_db = database.get_db
    chamadas = {"n": 0}

    def get_db_instavel():
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return original_get_db()

    monkeypatch.setattr(database, "get_db", get_db_instavel)

    resultado1 = database._carregar_candidatos_cache()
    assert resultado1["mapa"] == {}
    # A falha não deve ter sido memoizada no global.
    assert database._cache_candidatos is None

    resultado2 = database._carregar_candidatos_cache()
    assert resultado2["mapa"] != {}


def test_facade_reexporta_todo_o_db_conhecido():
    """Regressão: database.py é uma façade mantida à mão sobre db/*.py
    (plano 029). Se um nome sair da lista de re-exports sem que ninguém
    perceba, ele fica inacessível via `import database` em silêncio — só
    quebra quando algum caller tentar usá-lo em produção. Este teste fixa
    a lista conhecida-boa de hoje; ao adicionar uma função nova e pública
    num submódulo de db/*, adicione o nome aqui também (e no import
    correspondente em database.py)."""
    import database

    esperado = {
        # db/core.py
        "get_conn", "get_db", "init_db", "limpar_cache_analises",
        "salvar_log_scheduler", "buscar_ultimo_log",
        # db/candidatos.py
        "_popular_candidatos", "_invalidar_cache_candidatos",
        "_carregar_candidatos_cache", "get_mapa_apelidos",
        "get_cores_candidatos", "get_candidatos_por_espectro",
        "get_nomes_presidenciais", "get_presidenciais_canonicos",
        "get_candidatos_ignorar",
        # db/eventos.py
        "listar_eventos", "criar_evento", "remover_evento",
        # db/pesquisas.py
        "get_comparativo_candidato", "get_pesquisas_mais_recentes",
        "detectar_variacoes_bruscas", "get_media_agregada",
        "get_house_effects", "get_historico_multi", "get_historico_candidato",
        "get_top_candidatos", "get_institutos_com_totais",
        "get_dados_regionais", "_e_candidato",
        # db/kpis.py
        "get_kpis_avancados", "get_visao_geral", "_media_intervalo",
        # db/monte_carlo.py
        "fator_volatilidade", "_redistribuir_indecisos",
        "prob_vitoria_primeiro_turno", "_margens_por_candidato",
        "_pct_mudar_voto_recente", "_pct_indecisos_medio",
        "_simular_cenario", "simular_monte_carlo_cenarios",
        "_contagem_pesquisas_por_candidato", "_aviso_amostra_limitada",
        "simular_prob_vitoria_1_turno", "simular_monte_carlo_cargo",
        "get_simulacao_monte_carlo", "get_confronto_2turno_real",
        "get_simulacao_segundo_turno",
        # db/usuarios.py
        "criar_usuario", "verificar_usuario", "listar_usuarios",
        "remover_usuario", "toggle_usuario",
    }

    faltando = [nome for nome in esperado if not hasattr(database, nome)]
    assert not faltando, f"database.py não re-exporta: {faltando}"


def test_todos_os_imports_de_database_resolvem():
    """Varre app.py, coletar.py, collectors/*.py, cronos/**/*.py,
    scripts/*.py e tests/*.py por `from database import X, Y` e confirma
    que cada nome importado existe de fato em `database`. Import-time
    já garante isso indiretamente (um ImportError pararia a suíte), mas
    este teste torna a garantia explícita e documenta a superfície real
    da façade.

    Limitação conhecida: análise estática via `ast` não enxerga imports
    dinâmicos (ex.: `importlib.import_module`) — não há nenhum caso desses
    hoje contra `database`, mas se surgir um no futuro este teste não o
    cobrirá."""
    import ast
    import glob
    import database

    arquivos = (
        glob.glob("app.py") + glob.glob("coletar.py") +
        glob.glob("collectors/*.py") + glob.glob("cronos/**/*.py", recursive=True) +
        glob.glob("scripts/*.py") + glob.glob("tests/*.py")
    )

    problemas = []
    for caminho in arquivos:
        with open(caminho, "r", encoding="utf-8") as f:
            arvore = ast.parse(f.read(), filename=caminho)
        for node in ast.walk(arvore):
            if isinstance(node, ast.ImportFrom) and node.module == "database":
                for alias in node.names:
                    if not hasattr(database, alias.name):
                        problemas.append(f"{caminho}: from database import {alias.name}")

    assert not problemas, "Imports de `database` que não resolvem:\n" + "\n".join(problemas)
