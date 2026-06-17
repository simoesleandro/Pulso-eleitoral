"""
Sincroniza data/pulso.db local para o volume do Fly.io.
Uso: python scripts/sync_db.py
Requer: flyctl instalado e autenticado
"""
import subprocess
import os
import logging
import time

logger = logging.getLogger(__name__)

APP_NAME = "pulso-eleitoral"
DB_LOCAL = os.path.join(os.path.dirname(__file__), '..', 'data', 'pulso.db')


def sync_para_fly(force: bool = False) -> bool:
    """
    Sincroniza banco local com Fly.io.
    Retorna True se sincronizou, False se falhou.
    """
    # Verifica se flyctl está disponível
    try:
        result = subprocess.run(
            ['flyctl', 'version'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            logger.warning("flyctl não disponível — sync ignorado")
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.warning("flyctl não encontrado — sync ignorado")
        return False

    logger.info(f"Iniciando sync banco → Fly.io ({APP_NAME})")

    try:
        # 1. Garante que a máquina está rodando
        subprocess.run(
            ['flyctl', 'machines', 'start', '--app', APP_NAME],
            capture_output=True, text=True, timeout=30
        )

        # 2. Aguarda máquina estar pronta
        time.sleep(5)

        # 3. Remove banco remoto
        result = subprocess.run(
            ['flyctl', 'ssh', 'console', '--app', APP_NAME, '-C', 'rm -f /data/pulso.db'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            logger.warning(f"Erro ao remover banco remoto: {result.stderr}")

        # 4. Envia banco local
        result = subprocess.run(
            ['flyctl', 'sftp', 'put', DB_LOCAL, '/data/pulso.db', '--app', APP_NAME],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            logger.error(f"Erro no sftp put: {result.stderr}")
            return False

        logger.info(f"Banco enviado: {result.stdout.strip() or 'ok'}")

        # 5. Reinicia máquina
        subprocess.run(
            ['flyctl', 'machines', 'restart', '--app', APP_NAME],
            capture_output=True, text=True, timeout=30
        )

        logger.info("Sync concluído com sucesso")
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
