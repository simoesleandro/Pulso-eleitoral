"""
Script standalone para coleta de pesquisas eleitorais.
Executado pelo Task Scheduler como usuário stife.
"""
import os
import sys
import logging
from datetime import datetime

# Garante que o diretório do projeto está no path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Configura logging para arquivo
log_path = os.path.join(BASE_DIR, 'logs', 'coleta.log')
os.makedirs(os.path.join(BASE_DIR, 'logs'), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_path, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def main():
    logger.info("=== Iniciando coleta manual ===")
    
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
    
    import database
    DB_PATH = database.DB_PATH
    
    from collectors.quaest import QuaestCollector
    from collectors.atlas import AtlasCollector
    from collectors.poder360 import Poder360Collector
    from database import salvar_log_scheduler
    
    coletores = [
        QuaestCollector(db_path=DB_PATH),
        AtlasCollector(db_path=DB_PATH),
        Poder360Collector(db_path=DB_PATH),
    ]
    
    resultados = []
    for c in coletores:
        try:
            c.run()
            resultados.append({
                "coletor": c.__class__.__name__,
                "status": "ok"
            })
        except Exception as e:
            logger.error(f"Erro no coletor {c.__class__.__name__}: {e}")
            resultados.append({
                "coletor": c.__class__.__name__,
                "status": "erro",
                "msg": str(e)
            })
    
    salvar_log_scheduler(resultados)
    logger.info(f"=== Coleta finalizada: {len(resultados)} coletores ===")

if __name__ == "__main__":
    main()
