import os
import sqlite3
from contextlib import contextmanager

# Definindo o caminho do banco de dados (data/pulso.db ou data/pulso_test.db em testes)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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
