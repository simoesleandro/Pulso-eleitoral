import os
import datetime
import atexit
import json
from functools import wraps
from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from database import init_db, DB_PATH, get_db

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

app = Flask(__name__)

# Configurações do Flask
app.secret_key = os.getenv('SECRET_KEY', 'default-session-secret-key-9999')
ADMIN_USER = os.getenv('ADMIN_USER', 'admin')
ADMIN_PASS = os.getenv('ADMIN_PASS', 'admin123')

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

# Instancia o scheduler globalmente fora da inicialização do app
scheduler = BackgroundScheduler()

def run_all_collectors():
    """Roda todos os coletores cadastrados sequencialmente e salva log de execução."""
    from collectors.datafolha import DatafolhaCollector
    from database import salvar_log_scheduler
    
    coletores = [
        DatafolhaCollector(db_path=DB_PATH)
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

# Só inicia o scheduler se não estiver em ambiente de testes e não estiver rodando
# (Usamos os.environ['TESTING'] além de app.testing para evitar inicialização em pytest-import-time)
if not app.testing and os.getenv('TESTING') != 'True' and not scheduler.running:
    scheduler.start()

# Registra o shutdown limpo do scheduler no atexit
atexit.register(lambda: scheduler.shutdown() if scheduler.running else None)

@app.before_request
def require_login():
    """Middleware simples que exige login para todas as rotas, 
    exceto /login, /api/status e arquivos estáticos."""
    allowed_endpoints = [
        'login', 'static', 'api_status', 'dashboard', 
        'api_pesquisas_presidente', 'api_pesquisas_historico', 
        'api_pesquisas_governador_rj', 'api_institutos'
    ]
    if request.endpoint in allowed_endpoints:
        return
    
    if request.endpoint is None:
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return
        
    if not session.get('logged_in'):
        return redirect(url_for('login'))

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
        
        if username == ADMIN_USER and password == ADMIN_PASS:
            session['logged_in'] = True
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

@app.route('/dashboard')
def dashboard():
    """Página pública do dashboard."""
    return render_template('dashboard.html')

@app.route('/api/pesquisas/presidente')
def api_pesquisas_presidente():
    """Retorna dados consolidados da pesquisa mais recente para Presidente."""
    from database import get_pesquisas_mais_recentes
    rows = get_pesquisas_mais_recentes('presidente')
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
        "margem_erro": first['margem_erro']
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
        "margem_erro": first['margem_erro']
    })

@app.route('/api/pesquisas/historico')
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

@app.route('/api/institutos')
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
    # Roda o servidor localmente
    app.run(host='0.0.0.0', port=5080, debug=True)
