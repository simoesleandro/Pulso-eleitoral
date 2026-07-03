import os
import json
import logging
import sqlite3
from contextlib import contextmanager
import bcrypt

logger = logging.getLogger(__name__)

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

# ─── Candidatos: fonte única de verdade ────────────────────────────────────
# Roster canônico que popula a tabela `candidatos`. Cada item:
# (nome_canonico, [apelidos...], espectro, cor_hex, is_presidencial, ativo)
# ativo=0 → menções devem ser descartadas (hipotéticos / inelegíveis / não declarados).
_CANDIDATOS_SEED = [
    # Presidenciais ativos
    ("Lula", ["luiz inácio lula da silva", "luiz inacio lula da silva", "lula", "lula da silva"], "esquerda", "#0A2240", 1, 1),
    ("Flávio Bolsonaro", ["flávio bolsonaro", "flavio bolsonaro", "bolsonaro", "flavio", "flávio"], "direita", "#C0392B", 1, 1),
    ("Ronaldo Caiado", ["ronaldo caiado", "caiado"], "direita", "#5a7184", 1, 1),
    ("Romeu Zema", ["romeu zema", "zema"], "direita", "#B4B2A9", 1, 1),
    ("Renan Santos", ["renan santos", "renan santos (missão)"], "direita", "#1D9E75", 1, 1),
    ("Tarcísio de Freitas", ["tarcísio de freitas", "tarcisio de freitas", "tarcísio", "tarcisio"], "direita", None, 1, 1),
    ("Pablo Marçal", ["pablo marçal", "pablo marcal"], "direita", None, 1, 1),
    ("Ciro Gomes", ["ciro gomes", "ciro"], "centro", None, 1, 1),
    ("Simone Tebet", ["simone tebet", "simone"], "centro", None, 1, 1),
    ("Augusto Cury", ["augusto cury"], "centro", None, 1, 1),
    ("Rui Costa Pimenta", ["rui costa pimenta"], "esquerda", None, 1, 1),
    ("Samara Martins", ["samara martins"], "esquerda", None, 1, 1),
    ("Cabo Daciolo", ["cabo daciolo"], "direita", None, 1, 1),
    ("Edmilson Costa", ["edmilson costa"], "esquerda", None, 1, 1),
    ("Hertz Dias", ["hertz dias"], "esquerda", None, 1, 1),
    # Governador RJ (não presidenciais)
    ("Eduardo Paes", ["eduardo paes"], "centro", None, 0, 1),
    ("Cláudio Castro", ["cláudio castro", "claudio castro"], "direita", None, 0, 1),
    ("Marcelo Freixo", ["marcelo freixo"], "esquerda", None, 0, 1),
    ("Rodrigo Neves", ["rodrigo neves"], "centro", None, 0, 1),
    # Descartar (hipotéticos / inelegíveis / não declarados)
    ("Jair Bolsonaro", ["jair bolsonaro", "jair messias bolsonaro", "bolsonaro pai"], None, None, 1, 0),
    ("Michelle Bolsonaro", ["michelle bolsonaro", "michele bolsonaro", "michelle"], None, None, 1, 0),
    ("Aécio Neves", ["aécio neves", "aecio neves"], None, None, 1, 0),
    ("Aldo Rebelo", ["aldo rebelo"], None, None, 1, 0),
    ("Eduardo Bolsonaro", ["eduardo bolsonaro"], None, None, 1, 0),
    ("Camilo Santana", ["camilo santana"], None, None, 1, 0),
    ("Fernando Haddad", ["fernando haddad"], None, None, 1, 0),
    ("Elmano de Freitas", ["elmano de freitas"], None, None, 1, 0),
    ("ACM Neto", ["acm neto"], None, None, 1, 0),
    ("Jerônimo Rodrigues", ["jerônimo rodrigues", "jeronimo rodrigues"], None, None, 0, 0),
    ("Ratinho Junior", ["ratinho junior", "ratinho", "carlos massa ratinho junior"], None, None, 0, 0),
    ("Joaquim Barbosa", ["joaquim barbosa"], None, None, 1, 0),
]

# Cache em memória dos dados derivados da tabela candidatos (roster é estático).
_cache_candidatos = None


def _popular_candidatos(conn) -> None:
    """Insere o roster canônico na tabela candidatos se ela estiver vazia (idempotente)."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM candidatos")
    if cur.fetchone()[0] > 0:
        return
    for nome, apelidos, espectro, cor, is_pres, ativo in _CANDIDATOS_SEED:
        cur.execute(
            "INSERT INTO candidatos (nome_canonico, apelidos, espectro, cor_hex, is_presidencial, ativo) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (nome, json.dumps(apelidos, ensure_ascii=False), espectro, cor, is_pres, ativo)
        )
    conn.commit()
    _invalidar_cache_candidatos()


def _invalidar_cache_candidatos() -> None:
    global _cache_candidatos
    _cache_candidatos = None


def _carregar_candidatos_cache() -> dict:
    """Carrega (e memoiza) os mapas derivados da tabela candidatos.

    Retorna dict com:
      - mapa: {alias/canonico_lower -> nome_canonico | None}  (None = descartar)
      - espectro: {nome_canonico -> 'esquerda'|'centro'|'direita'}  (só ativos)
      - cores: {nome_canonico -> cor_hex}
      - presidenciais: set de chaves minúsculas (apelidos+canonico) de presidenciais ativos
      - presidenciais_canonicos: [nome_canonico, ...] presidenciais ativos
      - ignorar: [nome_canonico, ...] com ativo=0
    """
    global _cache_candidatos
    if _cache_candidatos is not None:
        return _cache_candidatos

    mapa, espectro, cores = {}, {}, {}
    presidenciais, presidenciais_canonicos, ignorar = set(), [], []
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT nome_canonico, apelidos, espectro, cor_hex, is_presidencial, ativo FROM candidatos"
            ).fetchall()
        for r in rows:
            nome = r["nome_canonico"]
            ativo = r["ativo"]
            try:
                apelidos = json.loads(r["apelidos"]) if r["apelidos"] else []
            except Exception:
                apelidos = []
            chaves = {a.lower().strip() for a in apelidos}
            chaves.add(nome.lower().strip())
            destino = nome if ativo else None
            for k in chaves:
                mapa[k] = destino
            if ativo:
                if r["espectro"]:
                    espectro[nome] = r["espectro"]
                if r["cor_hex"]:
                    cores[nome] = r["cor_hex"]
                if r["is_presidencial"]:
                    presidenciais.update(chaves)
                    presidenciais_canonicos.append(nome)
            else:
                ignorar.append(nome)
        _cache_candidatos = {
            "mapa": mapa, "espectro": espectro, "cores": cores,
            "presidenciais": presidenciais, "presidenciais_canonicos": presidenciais_canonicos,
            "ignorar": ignorar,
        }
    except Exception:
        # DB ainda sem a tabela/dados: devolve mapas vazios (normalização vira no-op).
        _cache_candidatos = {
            "mapa": {}, "espectro": {}, "cores": {},
            "presidenciais": set(), "presidenciais_canonicos": [], "ignorar": [],
        }
    return _cache_candidatos


def get_mapa_apelidos() -> dict:
    """{alias/nome minúsculo -> nome_canonico ou None}. Fonte para normalizar_nome."""
    return _carregar_candidatos_cache()["mapa"]


def get_cores_candidatos() -> dict:
    """{nome_canonico -> cor_hex} dos candidatos com cor definida."""
    return _carregar_candidatos_cache()["cores"]


def get_candidatos_por_espectro(espectros) -> set:
    """Nomes canônicos cujo espectro está no conjunto pedido (ex.: {'esquerda','centro'})."""
    esp = _carregar_candidatos_cache()["espectro"]
    return {nome for nome, e in esp.items() if e in espectros}


def get_nomes_presidenciais() -> set:
    """Conjunto de chaves minúsculas (apelidos + canônicos) de presidenciais ativos."""
    return _carregar_candidatos_cache()["presidenciais"]


def get_presidenciais_canonicos() -> list:
    """Lista de nomes canônicos presidenciais ativos (para injeção em prompts)."""
    return _carregar_candidatos_cache()["presidenciais_canonicos"]


def get_candidatos_ignorar() -> list:
    """Lista de nomes canônicos a descartar (para injeção em prompts)."""
    return _carregar_candidatos_cache()["ignorar"]


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

    # Popula a tabela candidatos (idempotente — só insere se vazia)
    _popular_candidatos(conn)

    # Migration idempotente: colunas status/data_status em candidatos
    # (mesmo padrão de scripts/migrate_candidatos_status.py — ALTER TABLE
    # puro, sem tocar schema.sql, seguro rodar em toda inicialização)
    from scripts.migrate_candidatos_status import aplicar_migracao
    aplicar_migracao(conn)

    # Migration idempotente: pct_pode_mudar_voto em pesquisas
    from scripts.migrate_pesquisas_volatilidade import aplicar_migracao as _aplicar_migracao_volatilidade
    _aplicar_migracao_volatilidade(conn)

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

def get_pesquisas_mais_recentes(cargo: str, tipo: str = 'estimulada') -> list[dict]:
    """Retorna a pesquisa mais recente do cargo (do tipo solicitado) e suas intenções.

    tipo='estimulada' inclui também registros legados sem tipo (NULL);
    tipo='espontanea' casa exatamente. A pesquisa escolhida é a mais recente
    que contenha intenções do tipo pedido.
    """
    if tipo == 'espontanea':
        filtro_int = "int.tipo = 'espontanea'"
        filtro_sub = "i2.tipo = 'espontanea'"
    else:
        filtro_int = "(int.tipo = 'estimulada' OR int.tipo IS NULL)"
        filtro_sub = "(i2.tipo = 'estimulada' OR i2.tipo IS NULL)"
    conn = get_conn()
    try:
        cursor = conn.cursor()
        # Encontra a pesquisa mais recente que tenha intenções do tipo pedido.
        # LEFT JOIN com candidatos: categorias que não são candidatos de verdade
        # (outros/nulos/brancos/indecisos) não têm linha em `candidatos` e
        # continuam aparecendo; candidatos com status != 'ativo' (desistente,
        # inelegível) são excluídos desta lista de "corrida atual".
        cursor.execute(f"""
            SELECT p.id, p.data_pesquisa, p.margem_erro, p.tamanho_amostra, p.fonte_url, inst.nome AS instituto,
                   int.candidato, int.percentual, int.partido, int.tipo
            FROM pesquisas p
            JOIN institutos inst ON p.instituto_id = inst.id
            JOIN intencoes int ON int.pesquisa_id = p.id
            LEFT JOIN candidatos c ON c.nome_canonico = int.candidato
            WHERE p.cargo = ? AND {filtro_int} AND p.id = (
                SELECT p2.id FROM pesquisas p2
                JOIN intencoes i2 ON i2.pesquisa_id = p2.id
                WHERE p2.cargo = ? AND {filtro_sub}
                ORDER BY p2.data_pesquisa DESC, p2.id DESC
                LIMIT 1
            )
            AND (c.status IS NULL OR c.status = 'ativo')
            ORDER BY int.percentual DESC
        """, (cargo, cargo))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()

# Cores canônicas vêm da tabela candidatos (get_cores_candidatos);
# esta paleta é só o fallback para candidatos sem cor definida.
_FALLBACK_COLORS = ['#0A2240', '#C0392B', '#5a7184', '#B4B2A9', '#1D9E75']


_EXCLUIR_CATEGORIAS = ['outros', 'nulos', 'brancos', 'indecisos', 'não sabe', 'nao sabe', 'não respondeu', 'nao respondeu']

from datetime import date, timedelta
from statistics import mean


def detectar_variacoes_bruscas(cargo: str = 'presidente',
                                limiar_pp: float = 3.0,
                                janela_dias: int = 7) -> list[dict]:
    """Detecta candidatos com variação >= limiar_pp nos últimos janela_dias."""
    data_limite = (date.today() - timedelta(days=janela_dias)).isoformat()

    query = """
    SELECT
        i_recente.candidato,
        i_recente.percentual AS pct_atual,
        p_recente.data_pesquisa AS data_atual,
        inst_recente.nome AS instituto_atual,
        i_anterior.percentual AS pct_anterior,
        p_anterior.data_pesquisa AS data_anterior,
        inst_anterior.nome AS instituto_anterior
    FROM intencoes i_recente
    JOIN pesquisas p_recente ON i_recente.pesquisa_id = p_recente.id
    JOIN institutos inst_recente ON p_recente.instituto_id = inst_recente.id
    JOIN intencoes i_anterior ON i_anterior.candidato = i_recente.candidato
    JOIN pesquisas p_anterior ON i_anterior.pesquisa_id = p_anterior.id
    JOIN institutos inst_anterior ON p_anterior.instituto_id = inst_anterior.id
    WHERE p_recente.cargo = ?
    AND p_recente.data_pesquisa = (
        SELECT MAX(p2.data_pesquisa) FROM pesquisas p2
        JOIN intencoes i2 ON i2.pesquisa_id = p2.id
        WHERE i2.candidato = i_recente.candidato AND p2.cargo = ?
    )
    AND p_anterior.data_pesquisa <= ?
    AND p_anterior.data_pesquisa = (
        SELECT MAX(p3.data_pesquisa) FROM pesquisas p3
        JOIN intencoes i3 ON i3.pesquisa_id = p3.id
        WHERE i3.candidato = i_recente.candidato
        AND p3.cargo = ?
        AND p3.data_pesquisa <= ?
    )
    AND p_anterior.instituto_id = p_recente.instituto_id
    AND ABS(i_recente.percentual - i_anterior.percentual) >= ?
    AND LOWER(i_recente.candidato) NOT LIKE '%outros%'
    AND LOWER(i_recente.candidato) NOT LIKE '%nulos%'
    AND LOWER(i_recente.candidato) NOT LIKE '%brancos%'
    GROUP BY i_recente.candidato
    ORDER BY ABS(i_recente.percentual - i_anterior.percentual) DESC
    """

    with get_db() as conn:
        rows = conn.execute(query, (
            cargo, cargo, data_limite,
            cargo, data_limite, limiar_pp
        )).fetchall()

    alertas = []
    for row in rows:
        variacao = round(row['pct_atual'] - row['pct_anterior'], 1)
        alertas.append({
            'candidato': row['candidato'],
            'percentual_atual': row['pct_atual'],
            'percentual_anterior': row['pct_anterior'],
            'variacao': variacao,
            'direcao': 'up' if variacao > 0 else 'down',
            'data_atual': row['data_atual'],
            'data_anterior': row['data_anterior'],
            'instituto_atual': row['instituto_atual'],
            'instituto_anterior': row['instituto_anterior'],
        })

    return alertas


def get_media_agregada(cargo: str, dias: int = 30) -> dict:
    """Retorna média agregada (poll-of-polls ponderado) por candidato.

    Em vez de média simples de todas as pesquisas — que deixaria um instituto
    prolífico dominar — o cálculo:
      1. Usa SOMENTE a pesquisa mais recente de cada instituto (1 voto/instituto);
      2. Pondera por tamanho de amostra (peso = amostra, ou 1000 se ausente);
      3. Pondera por recência via decaimento exponencial (0.9 ^ dias);
      4. score = peso_amostra * peso_recencia;
      5. média ponderada = SUM(percentual * score) / SUM(score).

    A variação no período continua sendo medida sobre todas as pesquisas da
    janela (sinal temporal), independente da deduplicação usada na média.
    """
    data_limite = (date.today() - timedelta(days=dias)).isoformat()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT i.candidato, i.percentual, p.id AS pesquisa_id, p.data_pesquisa,
                   p.tamanho_amostra, inst.nome AS instituto
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            JOIN institutos inst ON p.instituto_id = inst.id
            LEFT JOIN candidatos c ON c.nome_canonico = i.candidato
            WHERE p.cargo = ? AND p.data_pesquisa >= ?
            AND (i.tipo = 'estimulada' OR i.tipo IS NULL)
            AND (c.status IS NULL OR c.status = 'ativo')
            AND LOWER(i.candidato) NOT LIKE '%outros%'
            AND LOWER(i.candidato) NOT LIKE '%nulos%'
            AND LOWER(i.candidato) NOT LIKE '%brancos%'
            AND LOWER(i.candidato) NOT LIKE '%indecisos%'
            AND LOWER(i.candidato) NOT LIKE '%não sabe%'
            AND LOWER(i.candidato) NOT LIKE '%não respondeu%'
            ORDER BY i.candidato, p.data_pesquisa
        """, (cargo, data_limite)).fetchall()

    # Lista completa por candidato (para a variação temporal e o filtro de ruído)
    por_candidato: dict[str, list] = {}
    # Estrutura de pesquisas: pesquisa_id -> {instituto, data, amostra, cands: {nome: pct}}
    polls: dict[int, dict] = {}
    for r in rows:
        por_candidato.setdefault(r['candidato'], []).append(r)
        poll = polls.setdefault(r['pesquisa_id'], {
            'instituto': r['instituto'],
            'data': r['data_pesquisa'],
            'amostra': r['tamanho_amostra'] or 0,
            'cands': {},
        })
        poll['cands'][r['candidato']] = r['percentual']

    # 1. Seleciona a pesquisa mais recente de cada instituto (desempate por id)
    recente_por_instituto: dict[str, int] = {}
    for pid, poll in polls.items():
        atual = recente_por_instituto.get(poll['instituto'])
        if atual is None or (poll['data'], pid) > (polls[atual]['data'], atual):
            recente_por_instituto[poll['instituto']] = pid
    pids_selecionados = set(recente_por_instituto.values())

    # 2-4. Score de cada pesquisa selecionada = peso_amostra * peso_recencia
    hoje = date.today()
    scores: dict[int, float] = {}
    for pid in pids_selecionados:
        poll = polls[pid]
        peso_amostra = poll['amostra'] if poll['amostra'] and poll['amostra'] > 0 else 1000
        try:
            dias_desde = max(0, (hoje - date.fromisoformat(poll['data'])).days)
        except (ValueError, TypeError):
            dias_desde = 0
        peso_recencia = 0.9 ** dias_desde
        scores[pid] = peso_amostra * peso_recencia

    data_meio = (date.today() - timedelta(days=dias // 2)).isoformat()

    candidatos_resultado = []
    institutos_set: set[str] = set()
    total_pesquisas = 0

    for candidato, entradas in por_candidato.items():
        if len(entradas) < 2:
            continue

        # 5. Média ponderada sobre as pesquisas selecionadas (1 por instituto)
        num = 0.0
        den = 0.0
        percentuais_sel = []
        for pid in pids_selecionados:
            poll = polls[pid]
            if candidato not in poll['cands']:
                continue
            pct = poll['cands'][candidato]
            s = scores[pid]
            num += pct * s
            den += s
            percentuais_sel.append(pct)
            institutos_set.add(poll['instituto'])

        if den == 0 or not percentuais_sel:
            continue
        media_ponderada = num / den

        # Variação no período: todas as pesquisas da janela (sinal temporal)
        recentes = [e['percentual'] for e in entradas if e['data_pesquisa'] >= data_meio]
        anteriores = [e['percentual'] for e in entradas if e['data_pesquisa'] < data_meio]
        if recentes and anteriores:
            variacao = round(mean(recentes) - mean(anteriores), 1)
        else:
            variacao = None

        candidatos_resultado.append({
            "candidato": candidato,
            "media": round(media_ponderada, 1),
            "min": round(min(percentuais_sel), 1),
            "max": round(max(percentuais_sel), 1),
            "variacao_30d": variacao,
            "pesquisas_count": len(percentuais_sel),
        })
        total_pesquisas += len(percentuais_sel)

    candidatos_resultado.sort(key=lambda x: x['media'], reverse=True)

    return {
        "cargo": cargo,
        "periodo": f"últimos {dias} dias",
        "total_pesquisas": total_pesquisas,
        "institutos_incluidos": sorted(institutos_set),
        "candidatos": candidatos_resultado,
        "atualizado_em": date.today().strftime("%d/%m/%Y"),
    }


def get_simulacao_segundo_turno() -> dict:
    """Simula resultado de 2º turno Lula x Flávio com redistribuição proporcional de votos."""
    DIREITA = get_candidatos_por_espectro({'direita'})
    ESQUERDA_CENTRO = get_candidatos_por_espectro({'esquerda', 'centro'})

    media = get_media_agregada('presidente', dias=30)
    candidatos = media.get('candidatos', [])

    lula_direto = next((c['media'] for c in candidatos if c['candidato'] == 'Lula'), 0.0)
    flavio_direto = next((c['media'] for c in candidatos if c['candidato'] == 'Flávio Bolsonaro'), 0.0)

    lula_redist = 0.0
    flavio_redist = 0.0
    indefinido = 0.0

    for c in candidatos:
        nome = c['candidato']
        pct = c['media']
        if nome in ('Lula', 'Flávio Bolsonaro'):
            continue
        if nome in DIREITA:
            flavio_redist += pct * 0.70
            lula_redist += pct * 0.30
        elif nome in ESQUERDA_CENTRO:
            lula_redist += pct * 0.70
            flavio_redist += pct * 0.30
        else:
            indefinido += pct

    lula_total = lula_direto + lula_redist
    flavio_total = flavio_direto + flavio_redist

    return {
        "primeiro_turno": {
            "candidatos": [
                {"candidato": c['candidato'], "media": c['media'], "variacao": c.get('variacao_30d')}
                for c in candidatos[:5]
            ],
            "segundo_turno_provavel": lula_direto < 50,
            "data_atualizacao": date.today().strftime('%d/%m/%Y'),
        },
        "segundo_turno": {
            "lula": {
                "votos_diretos": round(lula_direto, 1),
                "votos_redistribuidos": round(lula_redist, 1),
                "total_estimado": round(lula_total, 1),
                "vencedor": lula_total > flavio_total,
            },
            "flavio": {
                "votos_diretos": round(flavio_direto, 1),
                "votos_redistribuidos": round(flavio_redist, 1),
                "total_estimado": round(flavio_total, 1),
                "vencedor": flavio_total > lula_total,
            },
            "indefinido": round(indefinido, 1),
            "nota": "Simulação baseada em redistribuição histórica de votos",
        },
    }


# ─── Motor de Monte Carlo (genérico, qualquer cargo) ───────────────────────

_BUCKET_INDECISOS = "Outros/Nulos/Brancos/Indecisos"


def fator_volatilidade(pct_pode_mudar_voto: float | None) -> float:
    """Fator de inflação do sigma de um candidato quando o instituto divulga
    o "% de eleitores que podem mudar de voto" (coluna pesquisas.pct_pode_mudar_voto).

    Heurística linear: cada ponto percentual de volatilidade divulgada soma
    1% ao sigma (ex.: 30% de eleitores voláteis → sigma 1.30x). Quando o dado
    não foi divulgado (None), o fator é neutro (1.0) — nunca inferimos ou
    estimamos essa métrica.
    """
    if pct_pode_mudar_voto is None:
        return 1.0
    return 1.0 + max(0.0, pct_pode_mudar_voto) / 100.0


def _redistribuir_indecisos(simulado: dict, pct_indecisos: float) -> dict:
    """Redistribui proporcionalmente o bucket "Outros/Nulos/Brancos/Indecisos"
    entre os candidatos reais de uma rodada simulada, com base no share
    relativo de cada um. `pct_indecisos` é a média do bucket para o cargo
    (0.0 se não houver esse dado — nesse caso é no-op)."""
    if pct_indecisos <= 0:
        return simulado
    total = sum(simulado.values())
    if total <= 0:
        return simulado
    return {nome: pct + pct_indecisos * (pct / total) for nome, pct in simulado.items()}


def prob_vitoria_primeiro_turno(candidato: str, runs: list[dict]) -> float:
    """% de runs (já com o bucket de indecisos redistribuído) em que o share
    do candidato ultrapassa 50% dos votos válidos do cenário — i.e., vitória
    em 1º turno sem precisar de confronto direto par a par. Calculada em
    cima do array de runs já retido pelo motor, sem rodar nova simulação."""
    if not runs:
        return 0.0
    vitorias = 0
    for run in runs:
        total = sum(run.values())
        if total > 0 and run.get(candidato, 0) / total > 0.5:
            vitorias += 1
    return round(vitorias / len(runs) * 100, 1)


def _margens_por_candidato(cargo: str) -> dict:
    """Margem de erro da pesquisa mais recente de cada candidato do cargo."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT i.candidato, p.margem_erro
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            WHERE p.cargo = ? AND p.margem_erro > 0
            AND (i.tipo = 'estimulada' OR i.tipo IS NULL)
            ORDER BY p.data_pesquisa DESC
        """, (cargo,)).fetchall()
    margens = {}
    for candidato, margem in rows:
        if candidato not in margens:
            margens[candidato] = margem
    return margens


def _pct_mudar_voto_recente(cargo: str) -> float | None:
    """pct_pode_mudar_voto mais recente divulgado pra esse cargo (dado é do
    poll inteiro, não por candidato — quando presente, é aplicado a todos os
    candidatos do cenário). None se nenhuma pesquisa recente tiver esse dado."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT pct_pode_mudar_voto FROM pesquisas
            WHERE cargo = ? AND pct_pode_mudar_voto IS NOT NULL
            ORDER BY data_pesquisa DESC, id DESC
            LIMIT 1
        """, (cargo,)).fetchone()
    return row["pct_pode_mudar_voto"] if row else None


def _pct_indecisos_medio(cargo: str, dias: int = 30) -> float:
    """Média simples do bucket "Outros/Nulos/Brancos/Indecisos" no cargo, nos
    últimos `dias` dias. 0.0 se não houver esse bucket nas pesquisas (caso do
    cargo 'presidente' hoje — nenhum instituto reporta essa linha)."""
    data_limite = (date.today() - timedelta(days=dias)).isoformat()
    with get_db() as conn:
        row = conn.execute("""
            SELECT AVG(i.percentual) AS media
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            WHERE p.cargo = ? AND p.data_pesquisa >= ? AND i.candidato = ?
        """, (cargo, data_limite, _BUCKET_INDECISOS)).fetchone()
    return row["media"] if row and row["media"] is not None else 0.0


def _simular_cenario(
    candidatos: list[dict],
    margens: dict,
    nome_a: str,
    nome_b: str,
    n_simulacoes: int = 10000,
    fator_sigma: float = 2.0,
    sigma_minimo: float = 6.0,
    margem_default: float = 2.0,
    pct_indecisos: float = 0.0,
    pct_mudar_voto: dict | None = None,
    mu_override: dict | None = None,
) -> dict:
    """Motor genérico de Monte Carlo para um par de candidatos (nome_a vs
    nome_b) dentro de um cenário multi-candidato — funciona pra qualquer
    cargo, não só presidencial.

    `candidatos` é a lista de dicts {'candidato': nome, 'media': pct} (ex.:
    retorno de get_media_agregada). `mu_override` mapeia nome de candidato →
    mu preferencial (0.0-1.0) no split de terceiros de direita — usado pelo
    wrapper presidencial pra preservar o comportamento de que eleitores do
    Flávio Bolsonaro têm maior afinidade com outro candidato de direita
    quando ele é um terceiro no cenário.

    Retorna o resultado do par + `runs`: lista com o dict completo de share
    simulado por candidato em cada rodada (já com o bucket de indecisos
    redistribuído), pra permitir métricas derivadas sem rodar nova simulação.
    """
    import random

    DIREITA = get_candidatos_por_espectro({'direita'})
    ESQUERDA_CENTRO = get_candidatos_por_espectro({'esquerda', 'centro'})
    pct_mudar_voto = pct_mudar_voto or {}
    mu_override = mu_override or {}

    medias_dict = {c['candidato']: c['media'] for c in candidatos}
    media_a = medias_dict.get(nome_a, 0)
    media_b = medias_dict.get(nome_b, 0)
    peso_total = (media_a + media_b) if (media_a + media_b) > 0 else 1
    peso_a = media_a / peso_total
    peso_b = media_b / peso_total

    runs = []
    vitorias_a = 0
    for _ in range(n_simulacoes):
        simulado = {}
        for c in candidatos:
            nome = c['candidato']
            sigma_base = max(margens.get(nome, margem_default) * fator_sigma, sigma_minimo)
            sigma = sigma_base * fator_volatilidade(pct_mudar_voto.get(nome))
            simulado[nome] = max(0, random.gauss(c['media'], sigma))

        simulado = _redistribuir_indecisos(simulado, pct_indecisos)
        runs.append(simulado)

        a = simulado.get(nome_a, 0)
        b = simulado.get(nome_b, 0)

        for nome, pct in simulado.items():
            if nome in (nome_a, nome_b):
                continue
            if nome in ESQUERDA_CENTRO:
                split = min(0.90, max(0.50, random.gauss(0.70, 0.08)))
                a += pct * split
                b += pct * (1 - split)
            elif nome in DIREITA:
                mu = mu_override.get(nome, 0.70)
                split = min(0.90, max(0.50, random.gauss(mu, 0.08)))
                b += pct * split
                a += pct * (1 - split)
            else:
                if media_a >= media_b:
                    a += pct * 0.40
                    b += pct * 0.30
                else:
                    b += pct * 0.40
                    a += pct * 0.30
                abstain = pct * 0.30
                a += abstain * peso_a
                b += abstain * peso_b

        total = a + b
        if total > 0 and (a / total) > 0.5:
            vitorias_a += 1

    prob_a = round(vitorias_a / n_simulacoes * 100, 1)
    prob_b = round(100 - prob_a, 1)
    return {
        'candidato_a': {
            'nome': nome_a,
            'media_direto': round(media_a, 1),
            'prob_vitoria': prob_a,
            'favorito': prob_a > prob_b,
            'prob_vitoria_primeiro_turno': prob_vitoria_primeiro_turno(nome_a, runs),
        },
        'candidato_b': {
            'nome': nome_b,
            'media_direto': round(media_b, 1),
            'prob_vitoria': prob_b,
            'favorito': prob_b > prob_a,
            'prob_vitoria_primeiro_turno': prob_vitoria_primeiro_turno(nome_b, runs),
        },
        'runs': runs,
    }


def simular_monte_carlo_cenarios(
    cargo: str,
    cenarios_def: list[tuple],
    n_simulacoes: int = 10000,
    fator_sigma: float = 2.0,
    sigma_minimo: float = 6.0,
    margem_default: float = 2.0,
    dias_media: int = 30,
    mu_override: dict | None = None,
) -> dict:
    """Motor genérico de Monte Carlo pra qualquer cargo.

    `cenarios_def` é uma lista de tuplas (nome_a, nome_b, id_cenario, label) —
    os confrontos a simular são decididos por quem chama, não fixos no motor
    (ex.: o wrapper presidencial get_simulacao_monte_carlo, ou uma futura
    versão pra governador_rj).
    """
    media = get_media_agregada(cargo, dias=dias_media)
    candidatos = media.get('candidatos', [])

    margens = _margens_por_candidato(cargo)
    pct_mudar_voto_valor = _pct_mudar_voto_recente(cargo)
    pct_mudar_voto = (
        {c['candidato']: pct_mudar_voto_valor for c in candidatos}
        if pct_mudar_voto_valor is not None else {}
    )
    pct_indecisos = _pct_indecisos_medio(cargo, dias=dias_media)

    cenarios = []
    for nome_a, nome_b, cid, label in cenarios_def:
        resultado = _simular_cenario(
            candidatos, margens, nome_a, nome_b,
            n_simulacoes=n_simulacoes,
            fator_sigma=fator_sigma,
            sigma_minimo=sigma_minimo,
            margem_default=margem_default,
            pct_indecisos=pct_indecisos,
            pct_mudar_voto=pct_mudar_voto,
            mu_override=mu_override,
        )
        cenarios.append({'id': cid, 'label': label, **resultado})

    return {
        'cargo': cargo,
        'cenarios': cenarios,
        'n_simulacoes': n_simulacoes,
        'fator_sigma_usado': fator_sigma,
        'sigma_minimo_usado': sigma_minimo,
        'margem_default_usada': margem_default,
    }


def _contagem_pesquisas_por_candidato(cargo: str, dias: int = 30) -> dict:
    """Quantas pesquisas (linhas de intencoes) cada candidato tem na janela,
    com os mesmos filtros de get_media_agregada (mesmo tipo, mesmos buckets
    excluídos, mesmo filtro de status ativo/inelegível via LEFT JOIN
    candidatos) — mas sem o corte de `len(entradas) < 2`, pra permitir
    distinguir candidatos com dado insuficiente dos com dado suficiente."""
    data_limite = (date.today() - timedelta(days=dias)).isoformat()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT i.candidato, COUNT(*) AS n
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            LEFT JOIN candidatos c ON c.nome_canonico = i.candidato
            WHERE p.cargo = ? AND p.data_pesquisa >= ?
            AND (i.tipo = 'estimulada' OR i.tipo IS NULL)
            AND (c.status IS NULL OR c.status = 'ativo')
            AND LOWER(i.candidato) NOT LIKE '%outros%'
            AND LOWER(i.candidato) NOT LIKE '%nulos%'
            AND LOWER(i.candidato) NOT LIKE '%brancos%'
            AND LOWER(i.candidato) NOT LIKE '%indecisos%'
            AND LOWER(i.candidato) NOT LIKE '%não sabe%'
            AND LOWER(i.candidato) NOT LIKE '%não respondeu%'
            GROUP BY i.candidato
        """, (cargo, data_limite)).fetchall()
    return {r['candidato']: r['n'] for r in rows}


def _aviso_amostra_limitada(candidatos_suficientes: list[dict]) -> str:
    """Monta o aviso de amostra limitada citando a maior variação real
    observada entre pesquisas, quando disponível."""
    variacoes = [c['variacao_30d'] for c in candidatos_suficientes if c.get('variacao_30d') is not None]
    if variacoes:
        maior = max(variacoes, key=abs)
        detalhe = f"variação entre pesquisas maior que o usual ({abs(maior):.0f}pp)"
    else:
        detalhe = "poucos dados disponíveis pra estimar variação"
    return (
        f"Baseado em institutos com rosters de candidatos distintos; {detalhe}. "
        "Interpretar com cautela até mais pesquisas confirmarem tendência."
    )


def simular_prob_vitoria_1_turno(
    candidatos: dict,
    n_simulacoes: int = 10000,
    fator_sigma: float = 2.0,
    sigma_minimo: float = 6.0,
) -> dict:
    """
    Simula, de forma independente por candidato — sem pool compartilhado,
    sem redistribuição entre concorrentes, sem depender de um segundo
    candidato existir — a chance de vitória em 1º turno "sozinho" (share
    simulado > 50.0).

    Conceitualmente diferente de _simular_cenario/prob_vitoria (que é
    par-a-par, pensado pra 2º turno: quem ganha entre A e B). Aqui cada
    candidato é uma distribuição gauss(media, sigma) independente das
    demais — não há "total da rodada" compartilhado, então não degenera
    quando só existe 1 candidato com dado suficiente (bug corrigido:
    antes, prob_vitoria_primeiro_turno(candidato, runs) dividia o share do
    candidato pela soma do dict de runs, que com 1 candidato só é sempre
    ele mesmo — share/total = 1.0 sempre, mascarando o sigma real).

    `candidatos` é um dict {nome: {'media': float, 'margem': float,
    'pct_pode_mudar_voto': float | None (opcional, default None)}}.

    Retorna {nome: prob_pct} — % das n_simulacoes rodadas em que o valor
    simulado desse candidato (isoladamente) ultrapassou 50.0.
    """
    import random

    resultado = {}
    for nome, dados in candidatos.items():
        media = dados['media']
        margem = dados['margem']
        sigma = max(margem * fator_sigma, sigma_minimo) * fator_volatilidade(dados.get('pct_pode_mudar_voto'))

        vitorias = 0
        for _ in range(n_simulacoes):
            if random.gauss(media, sigma) > 50.0:
                vitorias += 1
        resultado[nome] = round(vitorias / n_simulacoes * 100, 1)

    return resultado


def simular_monte_carlo_cargo(
    cargo: str,
    dias_media: int = 30,
    n_simulacoes: int = 10000,
    fator_sigma: float = 2.0,
    sigma_minimo: float = 6.0,
    margem_default: float = 2.0,
) -> dict:
    """
    Simula a chance de vitória em 1º turno (share > 50%, isoladamente) de
    cada candidato do cargo com dado suficiente (>= 2 pesquisas na janela)
    — via simular_prob_vitoria_1_turno(), independente por candidato (sem
    pool compartilhado nem depender de um segundo candidato existir).

    Formato de resposta NOVO, sem chaves legadas do endpoint presidencial
    (get_simulacao_monte_carlo) — este endpoint nasce sem dívida de
    compatibilidade.
    """
    media = get_media_agregada(cargo, dias=dias_media)
    candidatos_suficientes = media.get('candidatos', [])
    nomes_suficientes = {c['candidato'] for c in candidatos_suficientes}

    contagens = _contagem_pesquisas_por_candidato(cargo, dias=dias_media)
    candidatos_dados_insuficientes = sorted(
        nome for nome in contagens if nome not in nomes_suficientes
    )

    candidatos_simulados = []
    if candidatos_suficientes:
        margens = _margens_por_candidato(cargo)
        pct_mudar_voto_valor = _pct_mudar_voto_recente(cargo)

        entrada = {
            c['candidato']: {
                'media': c['media'],
                'margem': margens.get(c['candidato'], margem_default),
                'pct_pode_mudar_voto': pct_mudar_voto_valor,
            }
            for c in candidatos_suficientes
        }
        probs = simular_prob_vitoria_1_turno(
            entrada, n_simulacoes=n_simulacoes,
            fator_sigma=fator_sigma, sigma_minimo=sigma_minimo,
        )

        for c in candidatos_suficientes:
            candidatos_simulados.append({
                'nome': c['candidato'],
                'media': c['media'],
                'prob_vitoria_1_turno': probs[c['candidato']],
            })
        candidatos_simulados.sort(key=lambda c: c['media'], reverse=True)

    amostra_limitada = len(candidatos_suficientes) < 2
    aviso = _aviso_amostra_limitada(candidatos_suficientes) if amostra_limitada else None

    return {
        'cargo': cargo,
        'candidatos_simulados': candidatos_simulados,
        'candidatos_dados_insuficientes': candidatos_dados_insuficientes,
        'amostra_limitada': amostra_limitada,
        'aviso': aviso,
    }


def get_simulacao_monte_carlo(n_simulacoes: int = 10000) -> dict:
    """
    Wrapper de compatibilidade: simula os cenários presidenciais de sempre
    (Lula vs Flávio/Caiado/Zema) via simular_monte_carlo_cenarios() e remonta
    o formato de resposta legado — usado pelo endpoint GET /api/monte-carlo
    em produção. Mantém exatamente o mesmo formato e comportamento de antes.
    """
    CENARIOS_PRESIDENCIAL = [
        ('Lula', 'Flávio Bolsonaro', 'lula_flavio',  'Lula vs Flávio Bolsonaro'),
        ('Lula', 'Ronaldo Caiado',   'lula_caiado',  'Lula vs Ronaldo Caiado'),
        ('Lula', 'Romeu Zema',       'lula_zema',    'Lula vs Romeu Zema'),
    ]
    MARGEM_DEFAULT = 2.0

    resultado = simular_monte_carlo_cenarios(
        cargo='presidente',
        cenarios_def=CENARIOS_PRESIDENCIAL,
        n_simulacoes=n_simulacoes,
        margem_default=MARGEM_DEFAULT,
        # Eleitores do Flávio têm maior afinidade com outro cand. de direita
        # num 2º turno hipotético sem ele — split ligeiramente mais alto
        mu_override={'Flávio Bolsonaro': 0.75},
    )

    def _formato_legado(c: dict) -> dict:
        return {
            'nome': c['nome'],
            'media_direto': c['media_direto'],
            'prob_vitoria': c['prob_vitoria'],
            'favorito': c['favorito'],
        }

    cenarios = [
        {
            'id': c['id'],
            'label': c['label'],
            'candidato_a': _formato_legado(c['candidato_a']),
            'candidato_b': _formato_legado(c['candidato_b']),
        }
        for c in resultado['cenarios']
    ]

    primeiro = cenarios[0]
    return {
        'cenarios': cenarios,
        'n_simulacoes': n_simulacoes,
        'margem_default_usada': MARGEM_DEFAULT,
        # chaves flat para compatibilidade com dashboard existente
        'lula':   {**primeiro['candidato_a'], 'prob_vitoria': primeiro['candidato_a']['prob_vitoria']},
        'flavio': {**primeiro['candidato_b'], 'prob_vitoria': primeiro['candidato_b']['prob_vitoria']},
    }


def get_dados_regionais() -> dict:
    """Retorna percentuais mais recentes por candidato e UF da tabela pesquisas_regionais."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT uf, candidato, percentual, data_pesquisa "
                "FROM pesquisas_regionais ORDER BY uf, candidato, data_pesquisa DESC"
            ).fetchall()
    except Exception:
        return {"candidatos": [], "estados": {}}

    estados: dict = {}
    seen: set = set()
    candidato_totals: dict = {}

    for row in rows:
        key = (row["uf"], row["candidato"])
        if key in seen:
            continue
        seen.add(key)
        uf = row["uf"]
        if uf not in estados:
            estados[uf] = {}
        estados[uf][row["candidato"]] = {
            "percentual": row["percentual"],
            "data": row["data_pesquisa"],
        }
        candidato_totals.setdefault(row["candidato"], []).append(row["percentual"])

    candidatos = sorted(
        candidato_totals,
        key=lambda c: sum(candidato_totals[c]) / len(candidato_totals[c]),
        reverse=True,
    )

    return {"candidatos": candidatos, "estados": estados}


def get_kpis_avancados(cargo: str) -> dict:
    """Calcula 6 KPIs analíticos avançados com base na média agregada dos últimos 30 dias."""
    from statistics import stdev
    hoje = date.today()
    d15 = (hoje - timedelta(days=15)).isoformat()
    d30 = (hoje - timedelta(days=30)).isoformat()
    d60 = (hoje - timedelta(days=60)).isoformat()

    media_data = get_media_agregada(cargo, dias=30)
    candidatos = media_data.get("candidatos", [])

    # --- margem_lideranca ---
    if len(candidatos) >= 2:
        p1, p2 = candidatos[0], candidatos[1]
        margem = round(p1["media"] - p2["media"], 1)
        if margem < 5:
            clf = "empate_tecnico"
        elif margem <= 10:
            clf = "lideranca_moderada"
        else:
            clf = "lideranca_confortavel"
        margem_lideranca = {
            "primeiro": p1["candidato"],
            "segundo": p2["candidato"],
            "percentual_primeiro": p1["media"],
            "percentual_segundo": p2["media"],
            "margem": margem,
            "classificacao": clf,
        }
    else:
        margem_lideranca = {}

    # --- probabilidade_segundo_turno ---
    lider_pct = candidatos[0]["media"] if candidatos else 0.0
    probabilidade_segundo_turno = {
        "provavel": lider_pct < 50,
        "lider_percentual": lider_pct,
        "explicacao": "Nenhum candidato supera 50%" if lider_pct < 50 else f"Líder com {lider_pct}% pode vencer no 1º turno",
    }

    # --- tendencia_aceleracao (top 3) ---
    top3_nomes = [c["candidato"] for c in candidatos[:3]]
    tendencia_aceleracao = []
    with get_db() as conn:
        for nome in top3_nomes:
            def _avg(cand, c_start, c_end=None):
                if c_end:
                    r = conn.execute(
                        "SELECT AVG(i.percentual) AS m FROM intencoes i JOIN pesquisas p ON i.pesquisa_id = p.id "
                        "WHERE i.candidato=? AND p.cargo=? AND p.data_pesquisa>=? AND p.data_pesquisa<? "
                        "AND (i.tipo='estimulada' OR i.tipo IS NULL)",
                        (cand, cargo, c_start, c_end)
                    ).fetchone()
                else:
                    r = conn.execute(
                        "SELECT AVG(i.percentual) AS m FROM intencoes i JOIN pesquisas p ON i.pesquisa_id = p.id "
                        "WHERE i.candidato=? AND p.cargo=? AND p.data_pesquisa>=? "
                        "AND (i.tipo='estimulada' OR i.tipo IS NULL)",
                        (cand, cargo, c_start)
                    ).fetchone()
                return r["m"] if r and r["m"] is not None else 0.0

            m_rec15 = _avg(nome, d15)
            m_ant15 = _avg(nome, d30, d15)
            m_rec30 = _avg(nome, d30)
            m_ant30 = _avg(nome, d60, d30)

            t15 = round(m_rec15 - m_ant15, 1)
            t30 = round(m_rec30 - m_ant30, 1)

            if abs(t15) < 0.5 and abs(t30) < 0.5:
                acel = "estavel"
            elif t15 >= 0 and t30 >= 0:
                acel = "acelerando_alta" if t15 >= t30 else "desacelerando_alta"
            elif t15 < 0 and t30 < 0:
                acel = "acelerando_queda" if t15 <= t30 else "desacelerando_queda"
            elif t15 > 0:
                acel = "acelerando_alta"
            else:
                acel = "acelerando_queda"

            tendencia_aceleracao.append({
                "candidato": nome,
                "tendencia_15d": t15,
                "tendencia_30d": t30,
                "aceleracao": acel,
            })

    # --- campo_minado (candidatos fora do top 2, entre 2% e 15%) ---
    campo_minado = []
    with get_db() as conn:
        for c in candidatos[2:]:
            if not (2.0 <= c["media"] <= 15.0):
                continue
            r_rec = conn.execute(
                "SELECT AVG(i.percentual) AS m FROM intencoes i JOIN pesquisas p ON i.pesquisa_id = p.id "
                "WHERE i.candidato=? AND p.cargo=? AND p.data_pesquisa>=? "
                "AND (i.tipo='estimulada' OR i.tipo IS NULL)",
                (c["candidato"], cargo, d15)
            ).fetchone()
            r_ant = conn.execute(
                "SELECT AVG(i.percentual) AS m FROM intencoes i JOIN pesquisas p ON i.pesquisa_id = p.id "
                "WHERE i.candidato=? AND p.cargo=? AND p.data_pesquisa>=? AND p.data_pesquisa<? "
                "AND (i.tipo='estimulada' OR i.tipo IS NULL)",
                (c["candidato"], cargo, d30, d15)
            ).fetchone()
            pct_atual = round(r_rec["m"] if r_rec and r_rec["m"] is not None else c["media"], 1)
            pct_ant = r_ant["m"] if r_ant and r_ant["m"] is not None else None
            if pct_ant and pct_ant > 0:
                cresc = round((pct_atual - pct_ant) / pct_ant * 100, 1)
            else:
                cresc = 0.0
            campo_minado.append({
                "candidato": c["candidato"],
                "percentual_atual": pct_atual,
                "percentual_anterior": round(pct_ant, 1) if pct_ant else pct_atual,
                "crescimento_relativo": cresc,
                "em_ascensao": cresc > 20,
            })
    campo_minado.sort(key=lambda x: x["crescimento_relativo"], reverse=True)
    campo_minado = campo_minado[:3]

    # --- concentracao_voto ---
    if len(candidatos) >= 2:
        top2_soma = round(candidatos[0]["media"] + candidatos[1]["media"], 1)
        if top2_soma > 70:
            conc_clf = "bipolar"
        elif top2_soma >= 55:
            conc_clf = "moderado"
        else:
            conc_clf = "fragmentado"
        concentracao_voto = {
            "top2_soma": top2_soma,
            "classificacao": conc_clf,
            "terceira_via_possivel": top2_soma < 65,
        }
    else:
        concentracao_voto = {"top2_soma": 0.0, "classificacao": "fragmentado", "terceira_via_possivel": True}

    # --- volatilidade (top 3) ---
    vol_candidatos = []
    with get_db() as conn:
        for c in candidatos[:3]:
            rows = conn.execute(
                "SELECT i.percentual FROM intencoes i JOIN pesquisas p ON i.pesquisa_id = p.id "
                "WHERE i.candidato=? AND p.cargo=? AND p.data_pesquisa>=? "
                "AND (i.tipo='estimulada' OR i.tipo IS NULL) ORDER BY p.data_pesquisa",
                (c["candidato"], cargo, d30)
            ).fetchall()
            pcts = [r["percentual"] for r in rows]
            dp = round(stdev(pcts), 1) if len(pcts) >= 2 else 0.0
            vol_candidatos.append({
                "candidato": c["candidato"],
                "desvio_padrao": dp,
                "classificacao": "baixa" if dp < 2 else ("media" if dp <= 4 else "alta"),
            })

    media_dp = mean([v["desvio_padrao"] for v in vol_candidatos]) if vol_candidatos else 0.0
    cenario_geral = "estavel" if media_dp < 2 else ("moderado" if media_dp <= 4 else "volatil")

    return {
        "margem_lideranca": margem_lideranca,
        "probabilidade_segundo_turno": probabilidade_segundo_turno,
        "tendencia_aceleracao": tendencia_aceleracao,
        "campo_minado": campo_minado,
        "concentracao_voto": concentracao_voto,
        "volatilidade": {"candidatos": vol_candidatos, "cenario_geral": cenario_geral},
    }


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


def get_historico_multi(candidatos: list[str], cargo: str, tipo: str = 'estimulada') -> list[dict]:
    """Retorna série histórica de múltiplos candidatos para o cargo.

    Cada ponto inclui `margem_erro` para a renderização da banda de incerteza.
    tipo='estimulada' inclui registros legados sem tipo (NULL); 'espontanea' é exato.
    """
    if tipo == 'espontanea':
        filtro_tipo = "i.tipo = 'espontanea'"
    else:
        filtro_tipo = "(i.tipo = 'estimulada' OR i.tipo IS NULL)"
    candidatos = [c for c in candidatos if _e_candidato(c)]
    series = []
    with get_db() as conn:
        for idx, candidato in enumerate(candidatos):
            rows = conn.execute(f"""
                SELECT p.data_pesquisa AS data, i.percentual, p.margem_erro, inst.nome AS instituto
                FROM intencoes i
                JOIN pesquisas p ON i.pesquisa_id = p.id
                JOIN institutos inst ON p.instituto_id = inst.id
                WHERE i.candidato = ? AND p.cargo = ?
                AND {filtro_tipo}
                ORDER BY p.data_pesquisa ASC
            """, (candidato, cargo)).fetchall()
            cor = get_cores_candidatos().get(candidato, _FALLBACK_COLORS[idx % len(_FALLBACK_COLORS)])
            series.append({
                "candidato": candidato,
                "cor": cor,
                "dados": [{"data": r["data"], "percentual": r["percentual"],
                           "margem_erro": r["margem_erro"], "instituto": r["instituto"]} for r in rows]
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

