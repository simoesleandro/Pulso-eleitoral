"""
Sincroniza data/pulso.db local para o volume do Fly.io.
Uso: python scripts/sync_db.py
Requer: flyctl instalado e autenticado
"""
import subprocess
import os

DB_LOCAL = os.path.join(os.path.dirname(__file__), '..', 'data', 'pulso.db')

def sync():
    print("Sincronizando banco com Fly.io...")
    result = subprocess.run([
        'flyctl', 'sftp', 'shell', '--app', 'pulso-eleitoral'
    ], input=f'put {DB_LOCAL} /data/pulso.db\nexit\n',
    text=True, capture_output=True)
    print(result.stdout)
    if result.returncode == 0:
        print("Sync concluído!")
    else:
        print(f"Erro: {result.stderr}")

if __name__ == "__main__":
    sync()
