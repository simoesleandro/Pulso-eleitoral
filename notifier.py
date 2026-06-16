import os
import requests
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(mensagem: str) -> bool:
    """
    Envia mensagem para o Telegram.
    Retorna True se enviou, False se falhou.
    Nunca crasha.
    """
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("Telegram não configurado — TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID ausente")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": mensagem,
            "parse_mode": "HTML"
        }
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            logger.info("Telegram: mensagem enviada")
            return True
        else:
            logger.warning(f"Telegram erro HTTP {r.status_code}: {r.text}")
            return False
    except Exception as e:
        logger.error(f"Telegram erro: {e}")
        return False

def montar_mensagem_coleta(resultados: list[dict], 
                            pesquisas_novas: int,
                            intencoes_novas: int) -> str:
    """
    Monta mensagem formatada com resultado da coleta.
    """
    ok = [r for r in resultados if r["status"] == "ok"]
    erro = [r for r in resultados if r["status"] == "erro"]
    
    if pesquisas_novas == 0:
        status = "⚪ Sem novidades"
    else:
        status = f"🗳️ <b>{pesquisas_novas} nova(s) pesquisa(s)</b>"
    
    linhas = [
        f"📡 <b>PULSO ELEITORAL — Coleta Diária</b>",
        f"",
        f"{status}",
        f"📊 Intenções salvas: {intencoes_novas}",
        f"",
        f"✅ Coletores OK: {', '.join(r['coletor'].replace('Collector','') for r in ok)}",
    ]
    
    if erro:
        linhas.append(f"❌ Erros: {', '.join(r['coletor'].replace('Collector','') for r in erro)}")
    
    linhas.append(f"")
    linhas.append(f"🔗 <a href='http://localhost:5080/dashboard'>Ver Dashboard</a>")
    
    return "\n".join(linhas)
