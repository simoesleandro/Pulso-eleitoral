import os
import json
import sqlite3
from contextlib import contextmanager

# Definindo o caminho do banco de dados (data/pulso.db ou data/pulso_test.db em testes)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Em produção (Fly.io): /data/pulso.db
# Em local: data/pulso.db
if os.path.exists('/data'):
    DATA_DIR = '/data'
else:
    DATA_DIR = os.path.join(BASE_DIR, 'data')

DB_NAME = 'pulso_test.db' if os.getenv('TESTING') == 'True' else 'pulso.db'
DB_PATH = os.path.join(DATA_DIR, DB_NAME)

def get_conn():
    """Retorna uma conexão aberta com o SQLite, configurando a row_factory."""
    # Garante que a pasta 'data' exista
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Habilita chaves estrangeiras
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db(force_seed=False):
    """Executa o schema.sql para inicializar o banco de dados. 
    Se o banco estiver vazio ou force_seed for True, executa também o seed.sql."""
    # Garante que a pasta 'data' exista
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
        
    conn = get_conn()
    
    # 1. Executa o schema.sql
    schema_path = os.path.join(BASE_DIR, 'schema.sql')
    if os.path.exists(schema_path):
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
        conn.executescript(schema_sql)
        conn.commit()
    
    # Verifica se os dados já foram populados
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM institutos")
    count_institutos = cursor.fetchone()[0]
    
    # 2. Executa o seed.sql se o banco estiver vazio ou forçado
    if count_institutos == 0 or force_seed:
        seed_path = os.path.join(BASE_DIR, 'seed.sql')
        if os.path.exists(seed_path):
            with open(seed_path, 'r', encoding='utf-8') as f:
                seed_sql = f.read()
            # Precisamos desabilitar foreign keys temporariamente se formos limpar/refazer inserts
            conn.executescript(seed_sql)
            conn.commit()
            
    conn.close()

@contextmanager
def get_db():
    """Context manager para uso com o Flask (with get_db() as conn:)."""
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()

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

def get_pesquisas_mais_recentes(cargo: str) -> list[dict]:
    """Retorna os dados da pesquisa mais recente para o cargo e suas intenções de voto."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        # Encontra a pesquisa mais recente
        cursor.execute("""
            SELECT p.id, p.data_pesquisa, p.margem_erro, p.tamanho_amostra, p.fonte_url, inst.nome AS instituto,
                   int.candidato, int.percentual, int.partido
            FROM pesquisas p
            JOIN institutos inst ON p.instituto_id = inst.id
            JOIN intencoes int ON int.pesquisa_id = p.id
            WHERE p.cargo = ? AND p.id = (
                SELECT id FROM pesquisas 
                WHERE cargo = ? 
                ORDER BY data_pesquisa DESC, id DESC 
                LIMIT 1
            )
            ORDER BY int.percentual DESC
        """, (cargo, cargo))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()

def get_historico_candidato(candidato: str) -> list[dict]:
    """Retorna a evolução temporal (série histórica) das intenções de voto de um candidato."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.data_pesquisa AS data, int.percentual, inst.nome AS instituto
            FROM intencoes int
            JOIN pesquisas p ON int.pesquisa_id = p.id
            JOIN institutos inst ON p.instituto_id = inst.id
            WHERE int.candidato = ?
            ORDER BY p.data_pesquisa ASC, p.id ASC
        """, (candidato,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()

def get_institutos_com_totais() -> list[dict]:
    """Retorna a lista de institutos cadastrados junto com a contagem total de pesquisas e a data da última."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT inst.nome, COUNT(p.id) AS total, MAX(p.data_pesquisa) AS ultima_coleta
            FROM institutos inst
            LEFT JOIN pesquisas p ON p.instituto_id = inst.id
            GROUP BY inst.id, inst.nome
            ORDER BY total DESC, inst.nome ASC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()
