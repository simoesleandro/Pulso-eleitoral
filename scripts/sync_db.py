# -*- coding: utf-8 -*-
"""
Sincroniza data/pulso.db local para o volume do Fly.io.
Uso: python scripts/sync_db.py
Requer: flyctl instalado e autenticado
"""
import json
import shutil
import subprocess
import os
import logging
import time
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

logger = logging.getLogger(__name__)

APP_NAME   = "pulso-eleitoral"
MACHINE_ID = "6837932c65d538"
DB_LOCAL   = os.path.join(os.path.dirname(__file__), '..', 'data', 'pulso.db')

# O serviço Windows PulsoEleitoral roda como LocalSystem, que não enxerga o
# PATH de usuário onde o instalador do flyctl grava o binário — por isso o
# fallback para o caminho absoluto (shutil.which cobre a execução manual,
# onde 'flyctl' já está no PATH do usuário).
FLYCTL_BIN = shutil.which('flyctl') or r'C:\Users\Leand\.fly\bin\flyctl.exe'


def wait_machine_ready(timeout: int = 120, interval: int = 5) -> bool:
    """Aguarda a máquina MACHINE_ID atingir state == 'started'.
    Tenta a cada `interval` segundos por até `timeout` segundos.
    Retorna True se pronta, False se esgotou o tempo.
    """
    deadline = time.time() + timeout
    tentativa = 0
    while time.time() < deadline:
        tentativa += 1
        try:
            result = subprocess.run(
                [FLYCTL_BIN, 'machines', 'list', '--app', APP_NAME, '--json'],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0 and result.stdout.strip():
                machines = json.loads(result.stdout)
                for m in machines:
                    if m.get('id') == MACHINE_ID:
                        state = m.get('state', 'desconhecido')
                        if state == 'started':
                            logger.info(f"Máquina pronta após ~{tentativa * interval}s")
                            return True
                        logger.info(f"State atual: {state} — aguardando 'started'...")
        except (json.JSONDecodeError, subprocess.TimeoutExpired, Exception) as e:
            logger.debug(f"Erro ao verificar estado da máquina: {e}")

        logger.info(f"Aguardando máquina iniciar... tentativa {tentativa} ({tentativa * interval}s/{timeout}s)")
        time.sleep(interval)

    logger.warning(f"Máquina não atingiu 'started' em {timeout}s — tentando sync mesmo assim")
    return False


def upload_e_apply(db_local: str) -> bool:
    """Sobe banco com nome temporário único e chama /admin/apply-db para fazer o swap."""
    import requests
    admin_pass = os.getenv('ADMIN_PASS', '')
    url_apply = 'https://pulso-eleitoral.fly.dev/admin/apply-db'
    timestamp = int(time.time())
    filename = f"pulso_upload_{timestamp}.db"
    remote_path = f"/data/{filename}"

    result = subprocess.run(
        [FLYCTL_BIN, 'sftp', 'put', db_local, remote_path, '--app', APP_NAME],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        logger.error(f"sftp put falhou: {result.stderr.strip()}")
        return False
    logger.info(f"Upload ok: {result.stdout.strip() or f'{filename} enviado'}")

    # Chama rota do Flask para fazer o swap atômico
    resp = requests.post(
        url_apply,
        headers={'X-Admin-Pass': admin_pass, 'Content-Type': 'application/json'},
        json={'filename': filename},
        timeout=15
    )
    if resp.status_code == 200:
        logger.info("Banco aplicado via /admin/apply-db")
        return True
    logger.error(f"apply-db falhou: {resp.status_code} {resp.text}")
    return False


def sync_para_fly(force: bool = False) -> bool:
    """Sincroniza banco local com Fly.io.
    Retorna True se sincronizou, False se falhou.
    """
    try:
        result = subprocess.run(
            [FLYCTL_BIN, 'version'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            logger.warning("flyctl não disponível — sync ignorado")
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.warning("flyctl não encontrado — sync ignorado")
        return False

    logger.info(f"Iniciando sync banco -> Fly.io ({APP_NAME})")

    try:
        # 1. Inicia máquina
        subprocess.run(
            [FLYCTL_BIN, 'machines', 'start', MACHINE_ID, '--app', APP_NAME],
            capture_output=True, text=True, timeout=30
        )

        # 2. Aguarda máquina estar pronta
        wait_machine_ready(timeout=120, interval=5)

        # 3. Sobe e aplica banco
        if not upload_e_apply(DB_LOCAL):
            return False

        # 5. Reinicia máquina
        subprocess.run(
            [FLYCTL_BIN, 'machines', 'restart', '--app', APP_NAME],
            capture_output=True, text=True, timeout=30
        )

        logger.info("Sync concluido com sucesso")
        return True

    except subprocess.TimeoutExpired as e:
        logger.error(f"Timeout no sync: {e}")
        return False
    except Exception as e:
        logger.error(f"Erro no sync: {e}")
        return False


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    sync_para_fly(force=True)
