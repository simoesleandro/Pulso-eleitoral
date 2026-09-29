# -*- coding: utf-8 -*-
"""
Sincroniza data/pulso.db local para o volume do Fly.io — SUBSTITUI o banco
de produção inteiro.

Uso: python scripts/sync_db.py --force-sync
Requer: flyctl instalado e autenticado

Desde que a coleta migrou para o Fly (906c6de), produção é a fonte da
verdade e o banco local fica defasado. Por isso o sync só roda com
confirmação explícita (--force-sync / force_sync=True) e aborta se o banco
local tiver menos pesquisas que produção (contadas pelo export público).
Nenhum fluxo de coleta chama este sync automaticamente.
"""
import argparse
import csv
import io
import json
import sqlite3
import sys
import shutil
import socket
import subprocess
import os
import logging
import time
from dotenv import load_dotenv
import requests
import urllib3.util.connection as urllib3_cn

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

logger = logging.getLogger(__name__)

# Este notebook tem a rota IPv6 pra api.fly.io/*.fly.dev quebrada no handshake
# TLS (curl sem -4 falha, com -4 funciona) — ao contrário do flyctl/curl, o
# urllib3 (usado por requests em upload_e_apply) não faz fallback confiável
# pra IPv4, então o POST /admin/apply-db falhava com SSLEOFError toda vez.
urllib3_cn.allowed_gai_family = lambda: socket.AF_INET

APP_NAME   = "pulso-eleitoral"
MACHINE_ID = "6837932c65d538"
DB_LOCAL   = os.path.join(os.path.dirname(__file__), '..', 'data', 'pulso.db')
EXPORT_PRODUCAO_URL = "https://pulso-eleitoral.fly.dev/api/v1/export/pesquisas.csv"


class SyncAbortado(RuntimeError):
    """O sync foi recusado antes de tocar em produção (sem confirmação,
    produção não contável ou banco local defasado)."""

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


def contar_pesquisas_producao(timeout: int = 60) -> int:
    """Pesquisas em produção, contadas pelo export público (pesquisas_id
    distintos). Levanta SyncAbortado se não conseguir contar."""
    try:
        resp = requests.get(EXPORT_PRODUCAO_URL, timeout=timeout)
        resp.raise_for_status()
        linhas = csv.DictReader(io.StringIO(resp.text))
        return len({linha["pesquisa_id"] for linha in linhas})
    except (requests.RequestException, KeyError, csv.Error) as e:
        raise SyncAbortado(
            f"Não foi possível contar as pesquisas de produção ({EXPORT_PRODUCAO_URL}): {e}. "
            "Sync abortado — sem essa contagem não há como garantir que o banco "
            "local não está defasado."
        ) from e


def contar_pesquisas_local(db_local: str) -> int:
    """Pesquisas no banco local com a mesma semântica do export de produção
    (pesquisa com instituto e ao menos uma intenção), para comparar igual
    com igual."""
    conn = sqlite3.connect(db_local)
    try:
        return conn.execute(
            "SELECT COUNT(DISTINCT p.id) FROM pesquisas p "
            "JOIN institutos inst ON p.instituto_id = inst.id "
            "JOIN intencoes i ON i.pesquisa_id = p.id"
        ).fetchone()[0]
    finally:
        conn.close()


def verificar_banco_local_nao_defasado(db_local: str) -> None:
    """Aborta (SyncAbortado) se o banco local tiver menos pesquisas que
    produção — sincronizar apagaria o que só existe lá."""
    n_producao = contar_pesquisas_producao()
    n_local = contar_pesquisas_local(db_local)
    if n_local < n_producao:
        raise SyncAbortado(
            f"Banco local tem {n_local} pesquisa(s) e produção tem {n_producao}. "
            "Sync abortado: substituir produção pelo banco local apagaria "
            f"{n_producao - n_local} pesquisa(s) que só existem lá. "
            "A coleta roda no Fly — produção é a fonte da verdade."
        )
    logger.info(f"Checagem pré-sync ok: local {n_local} pesquisa(s) >= produção {n_producao}")


def upload_e_apply(db_local: str) -> bool:
    """Sobe banco com nome temporário único e chama /admin/apply-db para fazer o swap."""
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


def sync_para_fly(force_sync: bool = False, db_local: str = DB_LOCAL) -> bool:
    """Substitui o banco de produção pelo banco local.

    Exige force_sync=True e que o banco local tenha pelo menos tantas
    pesquisas quanto produção; senão levanta SyncAbortado antes de tocar no
    flyctl. Retorna True se sincronizou, False se o flyctl/upload falhou.
    """
    if not force_sync:
        raise SyncAbortado(
            "Sync recusado: ele substitui o banco de produção inteiro e exige "
            "confirmação explícita (python scripts/sync_db.py --force-sync)."
        )
    verificar_banco_local_nao_defasado(db_local)

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
        if not upload_e_apply(db_local):
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Substitui o banco de produção (Fly.io) pelo data/pulso.db local.")
    parser.add_argument(
        "--force-sync", action="store_true",
        help="confirma que é para sobrescrever produção (obrigatório)")
    args = parser.parse_args(argv)
    try:
        return 0 if sync_para_fly(force_sync=args.force_sync) else 1
    except SyncAbortado as e:
        logger.error(str(e))
        return 2


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    sys.exit(main())
