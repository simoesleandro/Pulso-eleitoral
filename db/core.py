"""Conexão/schema: get_conn, get_db, init_db e utilidades de log do scheduler.

`DB_PATH`/`DATA_DIR`/`BASE_DIR` continuam vivendo em `database.py` (o façade) —
não foram movidos para cá. Testes monkeypatcham `database.DB_PATH` e
`database.DATA_DIR` diretamente (ex.: tests/test_collectors.py,
tests/test_variacoes.py, tests/test_apply_db.py) esperando que isso mude o
que `get_conn`/`init_db` realmente usam. Por isso as funções aqui fazem
`import database` e leem `database.DB_PATH` etc. em tempo de chamada (live
attribute lookup) em vez de um `from database import DB_PATH` (que criaria
uma segunda binding independente e quebraria esse monkeypatch em silêncio).
"""
import os
import json
import logging
import sqlite3
from contextlib import contextmanager

import bcrypt

import database

logger = logging.getLogger(__name__)


def get_conn():
    """Retorna uma conexão aberta com o SQLite, configurando a row_factory."""
    # Garante que a pasta 'data' exista
    if not os.path.exists(database.DATA_DIR):
        os.makedirs(database.DATA_DIR, exist_ok=True)

    conn = sqlite3.connect(database.DB_PATH)
    conn.row_factory = sqlite3.Row
    # Habilita chaves estrangeiras
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def get_db():
    """Context manager para uso com o Flask (with get_db() as conn:)."""
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


def init_db(force_seed=False):
    """Executa o schema.sql para inicializar o banco de dados.
    Se o banco estiver vazio ou force_seed for True, executa também o seed.sql."""
    # Garante que a pasta 'data' exista
    if not os.path.exists(database.DATA_DIR):
        os.makedirs(database.DATA_DIR, exist_ok=True)

    conn = get_conn()

    # 1. Executa o schema.sql
    schema_path = os.path.join(database.BASE_DIR, 'schema.sql')
    if os.path.exists(schema_path):
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
        conn.executescript(schema_sql)
        conn.commit()

    # Popula a tabela candidatos (idempotente — só insere se vazia).
    # Import local (não no topo do módulo) para evitar ciclo de import:
    # db.candidatos importa get_db daqui (db.core) no nível do módulo.
    from db.candidatos import _popular_candidatos
    _popular_candidatos(conn)

    # Migration idempotente: colunas status/data_status em candidatos
    # (mesmo padrão de scripts/migrate_candidatos_status.py — ALTER TABLE
    # puro, sem tocar schema.sql, seguro rodar em toda inicialização)
    from scripts.migrate_candidatos_status import aplicar_migracao
    aplicar_migracao(conn)

    # Migration idempotente: pct_pode_mudar_voto em pesquisas
    from scripts.migrate_pesquisas_volatilidade import aplicar_migracao as _aplicar_migracao_volatilidade
    _aplicar_migracao_volatilidade(conn)

    # Migration idempotente: tabela confrontos_2turno (2º turno real das pesquisas)
    from scripts.migrate_confrontos_2turno import aplicar_migracao as _aplicar_migracao_confrontos
    _aplicar_migracao_confrontos(conn)

    # Verifica se os dados já foram populados
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM institutos")
    count_institutos = cursor.fetchone()[0]

    # 2. Executa o seed.sql se o banco estiver vazio ou forçado
    if count_institutos == 0 or force_seed:
        seed_path = os.path.join(database.BASE_DIR, 'seed.sql')
        if os.path.exists(seed_path):
            with open(seed_path, 'r', encoding='utf-8') as f:
                seed_sql = f.read()
            # Precisamos desabilitar foreign keys temporariamente se formos limpar/refazer inserts
            conn.executescript(seed_sql)
            conn.commit()

    # 3. Inicializa o usuário admin padrão se não houver usuários cadastrados
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    count_usuarios = cursor.fetchone()[0]
    if count_usuarios == 0:
        from dotenv import load_dotenv
        load_dotenv()
        admin_pass = os.getenv('ADMIN_PASS')
        if not admin_pass:
            import secrets
            admin_pass = secrets.token_urlsafe(16)
            logger.warning(
                "ADMIN_PASS não configurada — senha admin aleatória gerada e "
                "descartada. Defina ADMIN_PASS e recrie o usuário admin para ter "
                "uma senha conhecida."
            )
        admin_user = 'admin'
        password_hash = bcrypt.hashpw(admin_pass.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute(
            "INSERT INTO usuarios (username, password_hash, nome, ativo) VALUES (?, ?, ?, 1)",
            (admin_user, password_hash, 'Administrador')
        )
        conn.commit()

    conn.close()


def limpar_cache_analises():
    """Remove todas as análises geradas por IA para forçar regeneração."""
    with get_db() as conn:
        conn.execute("DELETE FROM analises_ia")
        conn.commit()


def salvar_log_scheduler(resultado: list) -> None:
    """Salva o log de execução de coleta no banco de dados SQLite."""
    conn = get_conn()
    try:
        resultado_json = json.dumps(resultado)
        conn.execute(
            "INSERT INTO scheduler_log (job, resultado) VALUES (?, ?)",
            ("coleta_diaria", resultado_json)
        )
        conn.commit()
    except Exception as e:
        raise e
    finally:
        conn.close()


def buscar_ultimo_log() -> dict | None:
    """Busca o log de execução do scheduler mais recente."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT job, executado_em, resultado FROM scheduler_log ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            return {
                "job": row["job"],
                "executado_em": row["executado_em"],
                "resultado": json.loads(row["resultado"]) if row["resultado"] else []
            }
        return None
    except Exception:
        return None
    finally:
        conn.close()
