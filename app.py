import os
import datetime
import atexit
import json
import hmac
import sqlite3
from functools import wraps
from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from flask_caching import Cache
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from database import init_db, DB_PATH, get_db

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

app = Flask(__name__)

# Configurações do Flask
_secret = os.getenv('SECRET_KEY')
if not _secret:
    if os.getenv('FLY_APP_NAME'):
        raise RuntimeError(
            "SECRET_KEY não configurada em produção. "
            "Defina com: flyctl secrets set SECRET_KEY=<string aleatória>"
        )
    import secrets as _secrets
    _secret = _secrets.token_hex(32)
    app.logger.warning(
        "SECRET_KEY não definida — usando chave efêmera (sessões não persistem "
        "entre reinícios). Defina SECRET_KEY no .env para desenvolvimento estável."
    )
app.secret_key = _secret

# NullCache em testes: SimpleCache é global no processo, então respostas
# cacheadas por um teste vazariam para o próximo teste que reusa a mesma rota
# com dados diferentes no banco.
_cache_type = 'NullCache' if os.getenv('TESTING') == 'True' else 'SimpleCache'
cache = Cache(app, config={'CACHE_TYPE': _cache_type, 'CACHE_DEFAULT_TIMEOUT': 300})

# Flags de cookie de sessão (defesa contra XSS/MITM/CSRF).
# Secure só em produção (Fly serve HTTPS); em dev local sobre HTTP ficaria inutilizável.
_em_producao = bool(os.getenv('FLY_APP_NAME'))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=_em_producao,
)

# Proteção CSRF (Flask-WTF). Desativada apenas sob TESTING para manter a suíte verde
# (o test client não tem como obter token); ativa em dev e produção.
app.config['WTF_CSRF_ENABLED'] = os.getenv('TESTING') != 'True'
csrf = CSRFProtect(app)

# Inicializa o banco de dados
init_db()

# Decorator para exigir autenticação nas rotas admin
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def _parse_num(valor, tipo, default):
    """Coage query param para int/float com fallback seguro — evita 500 em
    endpoints públicos quando o cliente manda um valor não-numérico."""
    try:
        return tipo(valor)
    except (TypeError, ValueError):
        return default

# Instancia o scheduler globalmente fora da inicialização do app
scheduler = BackgroundScheduler()

def run_all_collectors():
    """Roda todos os coletores cadastrados sequencialmente e salva log de execução."""
    from collectors.datafolha import DatafolhaCollector
    from collectors.quaest import QuaestCollector
    from collectors.gazetadopovo import GazetaDoPovoColetor
    from collectors.atlas import AtlasCollector
    from collectors.poder360 import Poder360Collector
    from database import salvar_log_scheduler

    coletores = [
        DatafolhaCollector(db_path=DB_PATH),
        QuaestCollector(db_path=DB_PATH),
        GazetaDoPovoColetor(db_path=DB_PATH),
        AtlasCollector(db_path=DB_PATH),
        Poder360Collector(db_path=DB_PATH),
    ]
    
    resultados = []
    for c in coletores:
        try:
            c.run()
            resultados.append({"coletor": c.__class__.__name__, "status": "ok"})
        except Exception as e:
            resultados.append({"coletor": c.__class__.__name__, "status": "erro", "msg": str(e)})
            
    # Salva o log de execução no banco SQLite
    salvar_log_scheduler(resultados)
    return resultados

# Registra o job diário às 08h00 no scheduler
scheduler.add_job(
    run_all_collectors,
    CronTrigger(hour=8, minute=0),
    id='coleta_diaria',
    replace_existing=True
)

if not app.testing and os.getenv('TESTING') != 'True' and not os.getenv('FLY_APP_NAME') and not scheduler.running:
    scheduler.start()

# Registra o shutdown limpo do scheduler no atexit
atexit.register(lambda: scheduler.shutdown() if scheduler.running else None)

@app.before_request
def require_login():
    """Middleware simples que exige login para todas as rotas, 
    exceto /login, /api/status e arquivos estáticos."""
    allowed_endpoints = [
        'login', 'static', 'api_status', 'dashboard', 'metodologia',
        'api_pesquisas_presidente', 'api_pesquisas_historico',
        'api_pesquisas_governador_rj', 'api_institutos',
        'api_visao_geral', 'api_visao_geral_analise', 'api_comparativo',
        'api_pesquisas_historico_multi',
        'api_media_agregada',
        'api_alertas',
        'api_kpis_avancados',
        'api_regional_presidente',
        'api_simulacao_segundo_turno',
        'api_monte_carlo',
        'api_monte_carlo_governador_rj',
        'api_rejeicao',
        'apply_db'
    ]
    if request.endpoint in allowed_endpoints:
        return
    
    if request.endpoint is None:
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return
        
    if not session.get('logged_in'):
        return redirect(url_for('login'))

@app.after_request
def aplicar_security_headers(response):
    """Adiciona cabeçalhos de segurança HTTP a todas as respostas (defesa em profundidade)."""
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    # CSP alinhada ao que os templates realmente carregam: scripts/estilos inline,
    # Chart.js/Tabler via jsDelivr e Google Fonts. connect-src 'self' (todas as APIs são internas).
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response

@app.route('/')
def index():
    """Redireciona para o dashboard se logado, senão o require_login intercepta e manda para /login."""
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Rota de controle de acesso (login)."""
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        from database import verificar_usuario
        user = verificar_usuario(username, password)
        if user:
            session['logged_in'] = True
            session['username'] = user['username']
            session['nome'] = user['nome']
            return redirect(url_for('index'))
        else:
            error = "Usuário ou senha incorretos."
            
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    """Rota para encerramento de sessão."""
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def admin():
    """Painel administrativo do scheduler."""
    from database import buscar_ultimo_log
    
    # 1. Próximo agendamento
    proximo_run = None
    try:
        job = scheduler.get_job('coleta_diaria')
        if job and job.next_run_time:
            proximo_run = job.next_run_time.isoformat()
    except Exception:
        pass
        
    # 2. Último run
    ultimo_log = buscar_ultimo_log()
    ultimo_run = ultimo_log['executado_em'] if ultimo_log else None
    
    # 3. Total de pesquisas no banco
    total_pesquisas = 0
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM pesquisas")
            total_pesquisas = cursor.fetchone()[0]
    except Exception:
        pass
        
    # 4. Últimos 10 logs do scheduler
    logs = []
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, job, executado_em, resultado FROM scheduler_log ORDER BY id DESC LIMIT 10")
            rows = cursor.fetchall()
            for row in rows:
                logs.append({
                    "id": row["id"],
                    "job": row["job"],
                    "executado_em": row["executado_em"],
                    "resultado": json.loads(row["resultado"]) if row["resultado"] else []
                })
    except Exception:
        pass
        
    return render_template(
        'admin.html',
        proximo_run=proximo_run,
        ultimo_run=ultimo_run,
        total_pesquisas=total_pesquisas,
        logs=logs
    )

@app.route('/admin/coletar', methods=['GET', 'POST'])
@login_required
def admin_coletar():
    """Dispara a coleta de pesquisas manualmente (protegida por login)."""
    resultados = run_all_collectors()
    return jsonify({
        "status": "ok",
        "timestamp": datetime.datetime.now().isoformat(),
        "coletores": len(resultados),
        "resultados": resultados
    })

@app.route('/admin/status-coletores')
@login_required
def admin_status_coletores():
    """Retorna o status de integridade e volumetria do coletor Datafolha (protegido por login)."""
    from database import buscar_ultimo_log
    
    ultimo_run = None
    total_registros = 0
    status = "sem_dados"
    
    # Tenta obter do scheduler_log
    ultimo_log = buscar_ultimo_log()
    if ultimo_log:
        ultimo_run = ultimo_log['executado_em']
        for res in ultimo_log['resultado']:
            if res['coletor'] == 'DatafolhaCollector' and res['status'] == 'ok':
                status = "ok"
                break
                
    # Se não achou nos logs de scheduler, tenta buscar da tabela pesquisas
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM pesquisas WHERE instituto_id = 1")
            total_registros = cursor.fetchone()[0]
            
            if not ultimo_run:
                cursor.execute("SELECT max(coletado_em) FROM pesquisas WHERE instituto_id = 1")
                row = cursor.fetchone()
                if row and row[0]:
                    ultimo_run = row[0]
                    status = "ok"
    except Exception as e:
        app.logger.error(f"Erro ao acessar status do coletor Datafolha: {e}")
        status = "erro"
        
    proximo_run = None
    try:
        job = scheduler.get_job('coleta_diaria')
        if job and job.next_run_time:
            proximo_run = job.next_run_time.isoformat()
    except Exception:
        pass
        
    return jsonify({
        "datafolha": {
            "ultimo_run": ultimo_run,
            "total_registros": total_registros,
            "status": status
        },
        "proximo_run": proximo_run
    })

@app.route('/admin/logs')
@login_required
def admin_logs():
    """Retorna os últimos 20 registros do scheduler_log como JSON (protegido por login)."""
    logs = []
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, job, executado_em, resultado FROM scheduler_log ORDER BY id DESC LIMIT 20")
            rows = cursor.fetchall()
            for row in rows:
                logs.append({
                    "id": row["id"],
                    "job": row["job"],
                    "executado_em": row["executado_em"],
                    "resultado": json.loads(row["resultado"]) if row["resultado"] else []
                })
    except Exception as e:
        app.logger.error(f"Erro ao obter logs de execução: {e}")
        
    return jsonify({"logs": logs})

@app.route('/admin/usuarios')
@login_required
def admin_usuarios():
    """Lista todos os usuários e renderiza a tela de gestão."""
    from database import listar_usuarios
    usuarios = listar_usuarios()
    return render_template('admin_usuarios.html', usuarios=usuarios)

@app.route('/admin/usuarios/criar', methods=['POST'])
@login_required
def admin_criar_usuario():
    """Cria um novo usuário."""
    username = request.form.get('username')
    password = request.form.get('password')
    nome = request.form.get('nome')
    
    from flask import flash
    if not username or not password:
        flash("Usuário e senha são obrigatórios.", "danger")
        return redirect(url_for('admin_usuarios'))
        
    from database import criar_usuario
    sucesso = criar_usuario(username, password, nome)
    if sucesso:
        flash("Usuário criado com sucesso!", "success")
    else:
        flash("Nome de usuário já existe.", "danger")
        
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuarios/<int:user_id>/remover', methods=['POST'])
@login_required
def admin_remover_usuario(user_id):
    """Remove um usuário do banco."""
    from database import listar_usuarios
    from flask import flash
    
    usuarios = listar_usuarios()
    target_username = None
    for u in usuarios:
        if u['id'] == user_id:
            target_username = u['username']
            break
            
    if target_username == session.get('username'):
        flash("Você não pode excluir a sua própria conta.", "danger")
        return redirect(url_for('admin_usuarios'))
        
    from database import remover_usuario
    sucesso = remover_usuario(user_id)
    if sucesso:
        flash("Usuário removido com sucesso!", "success")
    else:
        flash("Erro ao remover usuário.", "danger")
        
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuarios/<int:user_id>/toggle', methods=['POST'])
@login_required
def admin_toggle_usuario(user_id):
    """Ativa/desativa um usuário."""
    from database import listar_usuarios
    from flask import flash
    
    usuarios = listar_usuarios()
    target_username = None
    for u in usuarios:
        if u['id'] == user_id:
            target_username = u['username']
            break
            
    if target_username == session.get('username'):
        flash("Você não pode desativar a sua própria conta.", "danger")
        return redirect(url_for('admin_usuarios'))
        
    from database import toggle_usuario
    sucesso = toggle_usuario(user_id)
    if sucesso:
        flash("Status do usuário alterado com sucesso!", "success")
    else:
        flash("Erro ao alterar status do usuário.", "danger")
        
    return redirect(url_for('admin_usuarios'))

@app.route('/api/visao-geral')
@cache.cached(timeout=300)
def api_visao_geral():
    """Retorna dados estatísticos e tendências consolidadas para a visão geral."""
    from database import get_visao_geral
    return jsonify(get_visao_geral())

@app.route('/api/visao-geral/analise')
def api_visao_geral_analise():
    """Retorna análise do cenário político com cache de 6 horas."""
    from database import get_db, get_visao_geral
    import json
    import datetime
    
    cargo = 'visao_geral'
    
    # 1. Verifica cache no SQLite
    cached_analise = None
    cached_data = None
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT texto, criado_em FROM analises_ia
                WHERE cargo = ? AND criado_em >= datetime('now', 'localtime', '-6 hours')
            """, (cargo,))
            row = cursor.fetchone()
            if row:
                cached_analise = row['texto']
                cached_data = row['criado_em']
    except Exception as e:
        app.logger.error(f"Erro ao ler cache de analise: {e}")
        
    if cached_analise:
        try:
            dt = datetime.datetime.strptime(cached_data, "%Y-%m-%d %H:%M:%S")
            gerado_em = dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            gerado_em = cached_data
        return jsonify({
            "analise": cached_analise,
            "gerado_em": gerado_em
        })
        
    # 2. Se não estiver no cache, chama Gemini API
    dados = get_visao_geral()
    
    prompt = f"Você é um analista político brasileiro. Com base nos dados abaixo de pesquisas eleitorais, escreva um parágrafo analítico conciso (máximo 3 frases) sobre o cenário eleitoral atual. Seja objetivo, factual e neutro politicamente.\n\nDados: {json.dumps(dados, ensure_ascii=False)}\n\nResponda apenas com o parágrafo, sem título nem formatação."

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"analise": "Gemini API Key não configurada.", "gerado_em": ""}), 500
        
    try:
        from google import genai
        from collectors.gemini_extractor import gerar_com_cascata
        client = genai.Client(api_key=api_key)

        analise_texto, _ = gerar_com_cascata(
            client, prompt,
            modelos=["gemini-2.5-flash", "gemini-2.5-flash-8b", "gemini-2.5-pro"]
        )

        if not analise_texto:
            return jsonify({"analise": "Erro ao gerar análise de IA.", "gerado_em": ""}), 500
            
        # 3. Salva no banco analises_ia
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with get_db() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO analises_ia (cargo, texto, criado_em)
                    VALUES (?, ?, ?)
                """, (cargo, analise_texto, now_str))
                conn.commit()
        except Exception as e:
            app.logger.error(f"Erro ao salvar analise no banco: {e}")
            
        gerado_em = datetime.datetime.strptime(now_str, "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
        return jsonify({
            "analise": analise_texto,
            "gerado_em": gerado_em
        })
        
    except Exception as e:
        app.logger.error(f"Erro na geração do Gemini: {e}")
        return jsonify({"analise": "Serviço de análise de IA temporariamente indisponível.", "gerado_em": ""}), 500

@app.route('/dashboard')
def dashboard():
    """Página pública do dashboard."""
    return render_template('dashboard.html')

@app.route('/metodologia')
def metodologia():
    """Página de metodologia — como o sistema funciona."""
    return render_template('metodologia.html')

@app.route('/api/pesquisas/presidente')
def api_pesquisas_presidente():
    """Retorna dados consolidados da pesquisa mais recente para Presidente."""
    from database import get_pesquisas_mais_recentes
    tipo = request.args.get('tipo', 'estimulada')
    if tipo not in ('estimulada', 'espontanea'):
        tipo = 'estimulada'
    rows = get_pesquisas_mais_recentes('presidente', tipo)
    if not rows:
        return jsonify({
            "candidatos": [],
            "percentuais": [],
            "data_coleta": None,
            "instituto": None,
            "margem_erro": None
        })
    
    candidatos = [r['candidato'] for r in rows]
    percentuais = [r['percentual'] for r in rows]
    first = rows[0]
    return jsonify({
        "candidatos": candidatos,
        "percentuais": percentuais,
        "data_coleta": first['data_pesquisa'],
        "instituto": first['instituto'],
        "margem_erro": first['margem_erro'],
        "tipo": first['tipo'],
    })

@app.route('/api/pesquisas/governador-rj')
def api_pesquisas_governador_rj():
    """Retorna dados consolidados da pesquisa mais recente para Governador RJ."""
    from database import get_pesquisas_mais_recentes
    rows = get_pesquisas_mais_recentes('governador_rj')
    if not rows:
        return jsonify({
            "candidatos": [],
            "percentuais": [],
            "data_coleta": None,
            "instituto": None,
            "margem_erro": None,
            "tipo": None,
        })

    candidatos = [r['candidato'] for r in rows]
    percentuais = [r['percentual'] for r in rows]
    first = rows[0]
    return jsonify({
        "candidatos": candidatos,
        "percentuais": percentuais,
        "data_coleta": first['data_pesquisa'],
        "instituto": first['instituto'],
        "margem_erro": first['margem_erro'],
        "tipo": first['tipo'],
    })

@app.route('/api/alertas')
@cache.cached(timeout=300, query_string=True)
def api_alertas():
    """Retorna alertas de variações bruscas de percentual."""
    from database import detectar_variacoes_bruscas
    cargo = request.args.get('cargo', 'presidente')
    limiar = _parse_num(request.args.get('limiar'), float, 3.0)
    janela = _parse_num(request.args.get('janela'), int, 7)
    return jsonify({"alertas": detectar_variacoes_bruscas(cargo, limiar, janela)})

@app.route('/api/pesquisas/historico-multi')
@cache.cached(timeout=300, query_string=True)
def api_pesquisas_historico_multi():
    """Retorna séries históricas de múltiplos candidatos para um cargo."""
    from database import get_historico_multi, get_top_candidatos
    cargo = request.args.get('cargo', 'presidente')
    tipo = request.args.get('tipo', 'estimulada')
    if tipo not in ('estimulada', 'espontanea'):
        tipo = 'estimulada'
    candidatos_param = request.args.get('candidatos', '')
    if candidatos_param:
        candidatos = [c.strip() for c in candidatos_param.split(',') if c.strip()]
    else:
        candidatos = get_top_candidatos(cargo, n=3)
    series = get_historico_multi(candidatos, cargo, tipo)
    return jsonify({"cargo": cargo, "series": series})

@app.route('/api/media-agregada')
@cache.cached(timeout=300, query_string=True)
def api_media_agregada():
    """Retorna média agregada dos últimos 30 dias por candidato para um cargo."""
    from database import get_media_agregada
    cargo = request.args.get('cargo', 'presidente')
    dias = _parse_num(request.args.get('dias'), int, 30)
    return jsonify(get_media_agregada(cargo, dias))

@app.route('/api/kpis-avancados')
@cache.cached(timeout=300, query_string=True)
def api_kpis_avancados():
    """Retorna 6 KPIs analíticos avançados para o cargo."""
    from database import get_kpis_avancados
    cargo = request.args.get('cargo', 'presidente')
    return jsonify(get_kpis_avancados(cargo))

@app.route('/api/simulacao-segundo-turno')
@cache.cached(timeout=300)
def api_simulacao_segundo_turno():
    """Retorna simulação de 2º turno com redistribuição proporcional de votos."""
    from database import get_simulacao_segundo_turno
    return jsonify(get_simulacao_segundo_turno())

@app.route('/api/monte-carlo')
@cache.cached(timeout=300)
def api_monte_carlo():
    from database import get_simulacao_monte_carlo
    return jsonify(get_simulacao_monte_carlo())

@app.route('/api/monte-carlo/governador_rj')
@cache.cached(timeout=300)
def api_monte_carlo_governador_rj():
    """Chance de vitória em 1º turno por candidato pra governador RJ.
    Formato novo, sem chaves legadas do endpoint presidencial."""
    from database import simular_monte_carlo_cargo
    return jsonify(simular_monte_carlo_cargo('governador_rj'))

@app.route('/api/regional/presidente')
@cache.cached(timeout=300)
def api_regional_presidente():
    """Retorna dados regionais de intenção de voto por UF para mapa de calor."""
    from database import get_dados_regionais
    return jsonify(get_dados_regionais())

@app.route('/api/pesquisas/historico')
@cache.cached(timeout=300, query_string=True)
def api_pesquisas_historico():
    """Retorna a evolução temporal das intenções de voto de um candidato."""
    candidato = request.args.get('candidato')
    if not candidato:
        return jsonify({"candidato": "", "historico": []})
        
    from database import get_historico_candidato
    rows = get_historico_candidato(candidato)
    
    historico = []
    for r in rows:
        historico.append({
            "data": r['data'],
            "percentual": r['percentual'],
            "instituto": r['instituto']
        })
    return jsonify({
        "candidato": candidato,
        "historico": historico
    })

@app.route('/api/comparativo')
@cache.cached(timeout=300, query_string=True)
def api_comparativo():
    """Retorna a pesquisa mais recente de cada instituto para um candidato/cargo."""
    candidato = request.args.get('candidato', '')
    cargo = request.args.get('cargo', 'presidente')
    if not candidato:
        return jsonify({"candidato": "", "cargo": cargo, "institutos": []})
    from database import get_comparativo_candidato
    return jsonify(get_comparativo_candidato(candidato, cargo))

@app.route('/api/institutos')
@cache.cached(timeout=300)
def api_institutos():
    """Retorna a lista de institutos com contagem de pesquisas coletadas."""
    from database import get_institutos_com_totais
    rows = get_institutos_com_totais()
    institutos = []
    for r in rows:
        institutos.append({
            "nome": r['nome'],
            "total": r['total'],
            "ultima_coleta": r['ultima_coleta']
        })
    return jsonify({"institutos": institutos})

_COLETORES_DISPONIVEIS = {
    'datafolha':      ('collectors.datafolha',        'DatafolhaCollector'),
    'quaest':         ('collectors.quaest',            'QuaestCollector'),
    'gazetadopovo':   ('collectors.gazetadopovo',      'GazetaDoPovoColetor'),
    'cnn_brasil':     ('collectors.cnn_brasil',        'CnnBrasilColetor'),
    'verita':         ('collectors.verita',            'VeritaCollector'),
    'quaest_regional':('collectors.quaest_regional',   'QuaestRegionalColetor'),
}

# Mapeia domínio → coletor. A chave é casada por sufixo no hostname, então
# subdomínios (www., datafolha.folha.uol...) também batem.
_DOMINIO_COLETOR = {
    'gazetadopovo.com.br':          'gazetadopovo',
    'cnnbrasil.com.br':             'cnn_brasil',
    'datafolha.folha.uol.com.br':   'datafolha',
    'quaest.com.br':                'quaest_regional',
    'institutoverita.com.br':       'verita',
}

# Coletor genérico usado quando o domínio não é reconhecido (extrai via Gemini).
_COLETOR_FALLBACK = 'gazetadopovo'


def _detectar_coletor(url: str) -> str:
    """Detecta a chave do coletor a partir do domínio da URL.

    Casa por sufixo de hostname; se nenhum domínio conhecido bater, devolve o
    coletor genérico (_COLETOR_FALLBACK)."""
    try:
        host = (urlparse(url).hostname or '').lower()
    except Exception:
        host = ''
    for dominio, key in _DOMINIO_COLETOR.items():
        if host == dominio or host.endswith('.' + dominio):
            return key
    return _COLETOR_FALLBACK


def _url_segura(url: str) -> bool:
    """Guarda anti-SSRF: aceita só http(s) e bloqueia hosts internos/privados/loopback.

    O coletor faz fetch server-side de uma URL fornecida pelo admin; sem isso, a URL
    poderia apontar para metadados de nuvem, localhost ou a rede interna do Fly.
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return False

    host = parsed.hostname
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False

    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def _coletar_url_especifica(url: str, coletor_key: str) -> dict:
    """Instancia o coletor, faz fetch da URL, salva no banco e retorna delta de registros."""
    import importlib
    from datetime import date as _date

    if coletor_key not in _COLETORES_DISPONIVEIS:
        return {'erro': f'Coletor inválido: {coletor_key}'}

    module_path, class_name = _COLETORES_DISPONIVEIS[coletor_key]

    try:
        with get_db() as conn:
            p_antes = conn.execute("SELECT COUNT(*) FROM pesquisas").fetchone()[0]
            i_antes = conn.execute("SELECT COUNT(*) FROM intencoes").fetchone()[0]
            r_antes = conn.execute("SELECT COUNT(*) FROM pesquisas_regionais").fetchone()[0]

        mod = importlib.import_module(module_path)
        coletor = getattr(mod, class_name)(db_path=DB_PATH)

        html = coletor._get_page(url)
        if not html or len(html) < 200:
            return {'erro': 'Página vazia ou inacessível (HTML < 200 chars).', 'coletor': class_name, 'url': url}

        if coletor_key == 'quaest_regional':
            coletor._parse_page(html, url, data_post=_date.today().isoformat())
        else:
            dados = coletor._parse_release(html, url)
            coletor.save(dados)

        with get_db() as conn:
            p_depois = conn.execute("SELECT COUNT(*) FROM pesquisas").fetchone()[0]
            i_depois = conn.execute("SELECT COUNT(*) FROM intencoes").fetchone()[0]
            r_depois = conn.execute("SELECT COUNT(*) FROM pesquisas_regionais").fetchone()[0]

        return {
            'coletor': class_name,
            'url': url,
            'pesquisas_salvas': p_depois - p_antes,
            'intencoes_salvas': i_depois - i_antes,
            'regionais_salvas': r_depois - r_antes,
        }

    except Exception as e:
        app.logger.error(f"[coletar-url] {class_name} em {url}: {e}")
        return {'erro': str(e), 'coletor': class_name, 'url': url}


@app.route('/admin/coletar-url', methods=['GET', 'POST'])
@login_required
def admin_coletar_url():
    """Coleta uma URL específica detectando o coletor pelo domínio da URL."""
    if request.method == 'GET':
        return render_template('admin_coletar_url.html')

    body = request.get_json(silent=True) or {}
    url = (body.get('url') or '').strip()

    if not url or not url.startswith('http'):
        return jsonify({'erro': 'URL inválida — deve começar com http(s)://'}), 400
    if not _url_segura(url):
        return jsonify({'erro': 'URL recusada: aponta para host interno/privado ou esquema não permitido.'}), 400

    coletor_key = _detectar_coletor(url)
    resultado = _coletar_url_especifica(url, coletor_key)
    status = 200 if 'erro' not in resultado else 422
    return jsonify(resultado), status


@app.route('/admin/apply-db', methods=['POST'])
@csrf.exempt  # Autenticado por header X-Admin-Pass (hmac), chamado headless pelo sync_db.py — sem cookie/sessão, logo sem risco de CSRF.
def apply_db():
    import shutil

    # 1. Auth fail-closed: sem ADMIN_PASS configurada, recusa tudo.
    expected = os.getenv('ADMIN_PASS')
    provided = request.headers.get('X-Admin-Pass')
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        return jsonify({'error': 'unauthorized'}), 401

    # 2. Validação do nome: basename simples, sem separadores de caminho.
    body = request.get_json(silent=True) or {}
    filename = body.get('filename', '')
    if (os.path.basename(filename) != filename
            or not filename.startswith('pulso_upload_')
            or not filename.endswith('.db')):
        return jsonify({'error': 'filename inválido'}), 400

    new_db = f'/data/{filename}'
    current_db = '/data/pulso.db'
    if not os.path.exists(new_db):
        return jsonify({'error': f'{filename} não encontrado'}), 404

    # 3. Validação de integridade: precisa ser um SQLite válido com a tabela 'pesquisas'.
    try:
        conn = sqlite3.connect(new_db)
        try:
            ok = conn.execute("PRAGMA integrity_check").fetchone()
            has_tabela = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='pesquisas'"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        ok, has_tabela = None, None
    if not ok or ok[0] != 'ok' or not has_tabela:
        return jsonify({'error': 'arquivo não é um banco SQLite válido do Pulso'}), 422

    shutil.move(new_db, current_db)

    # Invalida o cache Flask-Caching logo após a troca do arquivo ter
    # terminado sem erro (nunca antes — um clear() prematuro deixaria o
    # cache vazio servindo o banco antigo até o próximo timeout).
    #
    # cache.clear() total é aceitável aqui porque, hoje, TUDO que é
    # cacheado no processo (@cache.cached() nos endpoints) depende do
    # SQLite que acabou de ser substituído — não existe cache de algo
    # independente de banco de dados neste sistema. Se isso mudar no
    # futuro (cache de um cálculo que não lê do SQLite), reavaliar pra
    # invalidação seletiva por chave/prefixo em vez de derrubar tudo.
    cache.clear()

    # O cache de candidatos (normalização/espectro/cores) é um global em memória
    # separado do Flask-Caching e também depende do SQLite que acabou de trocar.
    from database import _invalidar_cache_candidatos
    _invalidar_cache_candidatos()

    from datetime import datetime
    app.logger.info(f"[apply-db] cache invalidado após troca do banco em {datetime.now().isoformat()}")

    return jsonify({'ok': True, 'msg': 'banco aplicado'})

@app.route('/api/rejeicao')
@cache.cached(timeout=300)
def api_rejeicao():
    """Retorna média de rejeição por candidato nos últimos 30 dias."""
    resultado = []
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.candidato, AVG(r.percentual) AS media, COUNT(*) AS n_pesquisas
                FROM rejeicoes r
                JOIN pesquisas p ON p.id = r.pesquisa_id
                WHERE p.data_pesquisa >= date('now', '-30 days')
                  AND p.cargo = 'presidente'
                GROUP BY r.candidato
                ORDER BY media DESC
            """)
            rows = cursor.fetchall()
            resultado = [
                {"candidato": row["candidato"], "media": round(row["media"], 1), "n_pesquisas": row["n_pesquisas"]}
                for row in rows
            ]
    except Exception as e:
        app.logger.error(f"Erro em /api/rejeicao: {e}")
    return jsonify({"rejeicoes": resultado})


@app.route('/api/status')
def api_status():
    """Endpoint de status e integridade do sistema, aberto a consultas externas."""
    # Retorna o status online e a última coleta registrada no banco
    ultima_coleta = None
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT max(coletado_em) FROM pesquisas")
            row = cursor.fetchone()
            if row and row[0]:
                ultima_coleta = row[0]
    except Exception:
        pass

    return jsonify({
        "online": True,
        "ultima_coleta": ultima_coleta
    })

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5080))
    
    # Inicia scheduler só se não for produção
    if not os.getenv("FLY_APP_NAME"):
        if not scheduler.running:
            scheduler.start()
    
    init_db()
    
    from waitress import serve
    print(f"[Pulso Eleitoral] Iniciando na porta {port}")
    serve(app, host="0.0.0.0", port=port)
