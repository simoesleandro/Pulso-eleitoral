import os
import json
import sqlite3
from contextlib import contextmanager
import bcrypt

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

    # 3. Inicializa o usuário admin padrão se não houver usuários cadastrados
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    count_usuarios = cursor.fetchone()[0]
    if count_usuarios == 0:
        from dotenv import load_dotenv
        load_dotenv()
        admin_pass = os.getenv('ADMIN_PASS', 'pulso2026')
        admin_user = 'admin'
        password_hash = bcrypt.hashpw(admin_pass.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute(
            "INSERT INTO usuarios (username, password_hash, nome, ativo) VALUES (?, ?, ?, 1)",
            (admin_user, password_hash, 'Administrador')
        )
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

def get_comparativo_candidato(candidato: str, cargo: str) -> dict:
    """Retorna a pesquisa mais recente de cada instituto para o candidato/cargo."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT inst.nome AS instituto, i.percentual,
                   p.data_pesquisa AS data, p.margem_erro
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            JOIN institutos inst ON p.instituto_id = inst.id
            WHERE i.candidato = ? AND p.cargo = ?
            AND p.id = (
                SELECT p2.id FROM pesquisas p2
                JOIN intencoes i2 ON i2.pesquisa_id = p2.id
                WHERE p2.instituto_id = inst.id AND p2.cargo = ?
                  AND i2.candidato = ?
                ORDER BY p2.data_pesquisa DESC LIMIT 1
            )
            ORDER BY i.percentual DESC
        """, (candidato, cargo, cargo, candidato)).fetchall()

    return {
        "candidato": candidato,
        "cargo": cargo,
        "institutos": [
            {
                "instituto": r["instituto"],
                "percentual": r["percentual"],
                "data": r["data"],
                "margem_erro": r["margem_erro"]
            }
            for r in rows
        ]
    }

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

_CANDIDATE_COLORS = {
    'Lula': '#0A2240',
    'Flávio Bolsonaro': '#C0392B',
    'Ronaldo Caiado': '#5a7184',
    'Romeu Zema': '#B4B2A9',
    'Renan Santos': '#1D9E75',
}
_FALLBACK_COLORS = ['#0A2240', '#C0392B', '#5a7184', '#B4B2A9', '#1D9E75']


_EXCLUIR_CATEGORIAS = ['outros', 'nulos', 'brancos', 'indecisos', 'não sabe', 'nao sabe', 'não respondeu', 'nao respondeu']


def _e_candidato(nome: str) -> bool:
    nome_lower = nome.lower()
    return not any(excluir in nome_lower for excluir in _EXCLUIR_CATEGORIAS)


def get_top_candidatos(cargo: str, n: int = 3) -> list[str]:
    """Retorna os n candidatos com maior percentual médio para o cargo."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT i.candidato, AVG(i.percentual) AS media
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            WHERE p.cargo = ?
            GROUP BY i.candidato
            ORDER BY media DESC
        """, (cargo,)).fetchall()
    candidatos = [r['candidato'] for r in rows if _e_candidato(r['candidato'])]
    return candidatos[:n]


def get_historico_multi(candidatos: list[str], cargo: str) -> list[dict]:
    """Retorna série histórica de múltiplos candidatos para o cargo."""
    candidatos = [c for c in candidatos if _e_candidato(c)]
    series = []
    with get_db() as conn:
        for idx, candidato in enumerate(candidatos):
            rows = conn.execute("""
                SELECT p.data_pesquisa AS data, i.percentual, inst.nome AS instituto
                FROM intencoes i
                JOIN pesquisas p ON i.pesquisa_id = p.id
                JOIN institutos inst ON p.instituto_id = inst.id
                WHERE i.candidato = ? AND p.cargo = ?
                ORDER BY p.data_pesquisa ASC
            """, (candidato, cargo)).fetchall()
            cor = _CANDIDATE_COLORS.get(candidato, _FALLBACK_COLORS[idx % len(_FALLBACK_COLORS)])
            series.append({
                "candidato": candidato,
                "cor": cor,
                "dados": [{"data": r["data"], "percentual": r["percentual"], "instituto": r["instituto"]} for r in rows]
            })
    return series


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

def get_visao_geral() -> dict:
    """Retorna dados estatísticos e tendências consolidadas para a visão geral."""
    import datetime
    conn = get_conn()
    try:
        cursor = conn.cursor()
        
        # 1. Total de pesquisas
        cursor.execute("SELECT COUNT(*) FROM pesquisas")
        total_pesquisas = cursor.fetchone()[0]
        
        # 2. Institutos ativos (com pesquisas nos últimos 30 dias)
        cursor.execute("""
            SELECT COUNT(DISTINCT instituto_id) FROM pesquisas 
            WHERE data_pesquisa >= date('now', 'localtime', '-30 days')
        """)
        institutos_ativos = cursor.fetchone()[0]
        
        # 3. Última atualização (data da pesquisa mais recente)
        cursor.execute("SELECT MAX(data_pesquisa) FROM pesquisas")
        max_data = cursor.fetchone()[0]
        
        ultima_atualizacao = None
        dias_desde_ultima = None
        if max_data:
            try:
                dt = datetime.datetime.strptime(max_data, "%Y-%m-%d").date()
                today = datetime.date.today()
                dias_desde_ultima = max(0, (today - dt).days)
                ultima_atualizacao = dt.strftime("%d/%m/%Y")
            except Exception:
                pass
                
        # 4. Líder Presidente
        cursor.execute("""
            SELECT inst.nome AS instituto, int.candidato, int.percentual, p.data_pesquisa
            FROM pesquisas p
            JOIN institutos inst ON p.instituto_id = inst.id
            JOIN intencoes int ON int.pesquisa_id = p.id
            WHERE p.cargo = 'presidente' AND p.id = (
                SELECT id FROM pesquisas 
                WHERE cargo = 'presidente' 
                ORDER BY data_pesquisa DESC, id DESC 
                LIMIT 1
            )
            ORDER BY int.percentual DESC
            LIMIT 1
        """)
        row_pres = cursor.fetchone()
        lider_pres = None
        if row_pres:
            try:
                dt_pres = datetime.datetime.strptime(row_pres['data_pesquisa'], "%Y-%m-%d").date()
                dt_pres_str = dt_pres.strftime("%d/%m/%Y")
            except Exception:
                dt_pres_str = row_pres['data_pesquisa']
            lider_pres = {
                "candidato": row_pres['candidato'],
                "percentual": row_pres['percentual'],
                "instituto": row_pres['instituto'],
                "data": dt_pres_str
            }
            
        # 5. Líder Governador RJ
        cursor.execute("""
            SELECT inst.nome AS instituto, int.candidato, int.percentual, p.data_pesquisa
            FROM pesquisas p
            JOIN institutos inst ON p.instituto_id = inst.id
            JOIN intencoes int ON int.pesquisa_id = p.id
            WHERE p.cargo = 'governador_rj' AND p.id = (
                SELECT id FROM pesquisas 
                WHERE cargo = 'governador_rj' 
                ORDER BY data_pesquisa DESC, id DESC 
                LIMIT 1
            )
            ORDER BY int.percentual DESC
            LIMIT 1
        """)
        row_gov = cursor.fetchone()
        lider_gov = None
        if row_gov:
            try:
                dt_gov = datetime.datetime.strptime(row_gov['data_pesquisa'], "%Y-%m-%d").date()
                dt_gov_str = dt_gov.strftime("%d/%m/%Y")
            except Exception:
                dt_gov_str = row_gov['data_pesquisa']
            lider_gov = {
                "candidato": row_gov['candidato'],
                "percentual": row_gov['percentual'],
                "instituto": row_gov['instituto'],
                "data": dt_gov_str
            }
            
        # 6. Tendências
        cursor.execute("""
            SELECT int.candidato
            FROM pesquisas p
            JOIN intencoes int ON int.pesquisa_id = p.id
            WHERE p.cargo = 'presidente' AND p.id = (
                SELECT id FROM pesquisas 
                WHERE cargo = 'presidente' 
                ORDER BY data_pesquisa DESC, id DESC 
                LIMIT 1
            )
            ORDER BY int.percentual DESC
        """)
        rows_cand = cursor.fetchall()
        top_candidates = []
        for r in rows_cand:
            c_name = r['candidato']
            c_name_lower = c_name.lower()
            if any(x in c_name_lower for x in ['outros', 'nulo', 'branco', 'indeciso', 'não sabe', 'nenhum', '—']):
                continue
            top_candidates.append(c_name)
            if len(top_candidates) == 3:
                break
                
        tendencias = []
        for cand in top_candidates:
            cursor.execute("""
                SELECT i.percentual, p.data_pesquisa, p.instituto_id
                FROM intencoes i
                JOIN pesquisas p ON i.pesquisa_id = p.id
                WHERE i.candidato = ? AND p.cargo = 'presidente'
                AND p.instituto_id = (
                    SELECT p2.instituto_id FROM intencoes i2
                    JOIN pesquisas p2 ON i2.pesquisa_id = p2.id
                    WHERE i2.candidato = ? AND p2.cargo = 'presidente'
                    ORDER BY p2.data_pesquisa DESC, p2.id DESC LIMIT 1
                )
                ORDER BY p.data_pesquisa DESC, p.id DESC
                LIMIT 2
            """, (cand, cand))
            hist_rows = cursor.fetchall()
            if not hist_rows:
                continue
                
            percentual_atual = hist_rows[0]['percentual']
            if len(hist_rows) > 1:
                percentual_anterior = hist_rows[1]['percentual']
                variacao = percentual_atual - percentual_anterior
            else:
                percentual_anterior = percentual_atual
                variacao = 0.0
                
            if variacao > 0:
                direcao = "up"
            elif variacao < 0:
                direcao = "down"
            else:
                direcao = "flat"
                
            tendencias.append({
                "candidato": cand,
                "cargo": "presidente",
                "percentual_atual": percentual_atual,
                "percentual_anterior": percentual_anterior,
                "variacao": round(variacao, 2),
                "direcao": direcao
            })
            
        return {
            "kpis": {
                "total_pesquisas": total_pesquisas,
                "institutos_ativos": institutos_ativos,
                "ultima_atualizacao": ultima_atualizacao,
                "dias_desde_ultima": dias_desde_ultima
            },
            "lider_presidente": lider_pres,
            "lider_governador": lider_gov,
            "tendencias": tendencias
        }
    finally:
        conn.close()


def criar_usuario(username: str, password: str, nome: str = None) -> bool:
    """Cria novo usuário com senha hasheada. Retorna False se username já existe."""
    username = username.strip().lower()
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO usuarios (username, password_hash, nome, ativo) VALUES (?, ?, ?, 1)",
            (username, password_hash, nome)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception as e:
        raise e
    finally:
        conn.close()

def verificar_usuario(username: str, password: str) -> dict | None:
    """Compara a senha informada com a hash salva via bcrypt.checkpw,
    atualiza ultimo_login se correta, e retorna dados do usuário (dict) se ativo."""
    username = username.strip().lower()
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, password_hash, nome, ativo FROM usuarios WHERE username = ?",
            (username,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        
        # Se o usuário não estiver ativo, não permite login
        if not row['ativo']:
            return None

        # Verifica senha
        hash_bytes = row['password_hash'].encode('utf-8')
        if bcrypt.checkpw(password.encode('utf-8'), hash_bytes):
            # Atualiza último login
            import datetime
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "UPDATE usuarios SET ultimo_login = ? WHERE id = ?",
                (now_str, row['id'])
            )
            conn.commit()
            return {
                "id": row["id"],
                "username": row["username"],
                "nome": row["nome"],
                "ativo": row["ativo"]
            }
        return None
    except Exception as e:
        raise e
    finally:
        conn.close()

def listar_usuarios() -> list[dict]:
    """Retorna todos os usuários cadastrados sem a hash da senha."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, nome, ativo, criado_em, ultimo_login FROM usuarios ORDER BY username ASC"
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()

def remover_usuario(user_id: int) -> bool:
    """Exclui o usuário do banco por ID. Retorna True se excluiu com sucesso."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        return False
    finally:
        conn.close()

def toggle_usuario(user_id: int) -> bool:
    """Inverte o status 'ativo' (0 para 1, ou 1 para 0) do usuário por ID."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ativo FROM usuarios WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if row is None:
            return False
        novo_status = 0 if row['ativo'] == 1 else 1
        cursor.execute("UPDATE usuarios SET ativo = ? WHERE id = ?", (novo_status, user_id))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()

