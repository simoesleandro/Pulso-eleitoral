import os
from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from dotenv import load_dotenv
from database import init_db

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

app = Flask(__name__)

# Configurações do Flask
app.secret_key = os.getenv('SECRET_KEY', 'default-session-secret-key-9999')
ADMIN_USER = os.getenv('ADMIN_USER', 'admin')
ADMIN_PASS = os.getenv('ADMIN_PASS', 'admin123')

# Inicializa o banco de dados e roda a carga de sementes (seed.sql) se necessário
init_db()

@app.before_request
def require_login():
    """Middleware simples que exige login para todas as rotas, 
    exceto /login, /api/status e arquivos estáticos."""
    allowed_endpoints = ['login', 'static', 'api_status']
    if request.endpoint in allowed_endpoints:
        return
    
    # Se a rota não for reconhecida (404), deixa o Flask lidar com isso se estiver logado,
    # caso contrário redireciona para o login
    if request.endpoint is None:
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return
        
    if not session.get('logged_in'):
        return redirect(url_for('login'))

@app.route('/')
def index():
    """Rota inicial temporária."""
    return "Pulso Eleitoral — OK"

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

@app.route('/api/status')
def api_status():
    """Endpoint de status e integridade do sistema, aberto a consultas externas."""
    # Retorna o status online e a última coleta
    return jsonify({
        "online": True,
        "ultima_coleta": None
    })

if __name__ == '__main__':
    # Roda o servidor localmente
    app.run(host='0.0.0.0', port=5080, debug=True)
