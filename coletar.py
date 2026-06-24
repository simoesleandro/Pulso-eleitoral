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
    
    from collectors.datafolha import DatafolhaCollector
    from collectors.quaest import QuaestCollector
    from collectors.gazetadopovo import GazetaDoPovoColetor
    from collectors.atlas import AtlasCollector
    from collectors.poder360 import Poder360Collector
    from collectors.verita import VeritaCollector
    from collectors.cnn_brasil import CnnBrasilColetor
    from collectors.quaest_regional import QuaestRegionalColetor
    from database import salvar_log_scheduler
    from notifier import send_telegram, montar_mensagem_coleta

    # Antes da coleta
    with database.get_db() as conn:
        p_antes = conn.execute("SELECT COUNT(*) FROM pesquisas").fetchone()[0]
        i_antes = conn.execute("SELECT COUNT(*) FROM intencoes").fetchone()[0]
        max_id_antes = conn.execute("SELECT COALESCE(MAX(id), 0) FROM pesquisas").fetchone()[0]

    coletores = [
        DatafolhaCollector(db_path=DB_PATH),
        QuaestCollector(db_path=DB_PATH),
        GazetaDoPovoColetor(db_path=DB_PATH),
        AtlasCollector(db_path=DB_PATH),
        Poder360Collector(db_path=DB_PATH),
        VeritaCollector(db_path=DB_PATH),
        CnnBrasilColetor(db_path=DB_PATH),
        QuaestRegionalColetor(db_path=DB_PATH),
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
    
    # Depois da coleta
    with database.get_db() as conn:
        p_depois = conn.execute("SELECT COUNT(*) FROM pesquisas").fetchone()[0]
        i_depois = conn.execute("SELECT COUNT(*) FROM intencoes").fetchone()[0]

    pesquisas_novas = max(0, p_depois - p_antes)
    intencoes_novas = max(0, i_depois - i_antes)

    # Envia notificação de resumo da coleta
    mensagem = montar_mensagem_coleta(resultados, pesquisas_novas, intencoes_novas)
    send_telegram(mensagem)
    logger.info(f"Notificação enviada: {pesquisas_novas} pesquisas novas, {intencoes_novas} intenções novas")

    # Notificação individual por pesquisa nova
    if pesquisas_novas > 0:
        from notifier import montar_mensagem_nova_pesquisa
        with database.get_db() as conn:
            novas = conn.execute("""
                SELECT p.id, inst.nome AS instituto, p.cargo, p.data_pesquisa
                FROM pesquisas p
                JOIN institutos inst ON p.instituto_id = inst.id
                WHERE p.id > ?
                ORDER BY p.id
            """, (max_id_antes,)).fetchall()
            for row in novas:
                pid, instituto, cargo, data_pesquisa = row
                candidatos = conn.execute("""
                    SELECT candidato, percentual FROM intencoes
                    WHERE pesquisa_id = ?
                    ORDER BY percentual DESC
                """, (pid,)).fetchall()
                pesquisa_info = {
                    "instituto": instituto,
                    "cargo": cargo,
                    "data_pesquisa": data_pesquisa,
                    "candidatos": [{"candidato": c, "percentual": p} for c, p in candidatos],
                }
                send_telegram(montar_mensagem_nova_pesquisa(pesquisa_info))
                logger.info(f"Notificação nova pesquisa: {instituto} / {cargo} / {data_pesquisa}")

    # Sincroniza com Fly.io se houve dados novos
    if pesquisas_novas > 0 or intencoes_novas > 0:
        logger.info(f"Dados novos detectados ({pesquisas_novas} pesquisas, {intencoes_novas} intenções) — iniciando sync")
        from scripts.sync_db import sync_para_fly
        sucesso = sync_para_fly()
        if sucesso:
            logger.info("Fly.io atualizado automaticamente")
        else:
            logger.warning("Sync falhou — dashboard do Fly.io pode estar desatualizado")
    else:
        logger.info("Sem dados novos — sync ignorado")

    # Verifica variações bruscas
    from database import detectar_variacoes_bruscas
    from notifier import montar_mensagem_alerta
    alertas = detectar_variacoes_bruscas(cargo='presidente', limiar_pp=3.0)
    if alertas:
        logger.info(f"{len(alertas)} alerta(s) de variação detectado(s)")
        msg_alerta = montar_mensagem_alerta(alertas)
        send_telegram(msg_alerta)
    else:
        logger.info("Nenhuma variação brusca detectada")

    logger.info(f"=== Coleta finalizada: {len(resultados)} coletores ===")

if __name__ == "__main__":
    main()
