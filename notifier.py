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


def montar_mensagem_nova_pesquisa(pesquisa: dict) -> str:
    """
    Monta notificação para uma pesquisa recém-inserida no banco.
    pesquisa: dict com keys instituto, cargo, data_pesquisa, candidatos (list de {candidato, percentual})
    """
    instituto = pesquisa.get("instituto", "—")
    cargo = pesquisa.get("cargo", "—").replace("_", " ").title()
    data = pesquisa.get("data_pesquisa", "—")

    candidatos = sorted(pesquisa.get("candidatos", []), key=lambda c: c["percentual"], reverse=True)
    cands_str = " | ".join(
        f"{c['candidato']} {c['percentual']:.0f}%"
        for c in candidatos
    ) or "—"

    return (
        f"📊 <b>Nova pesquisa coletada</b>\n"
        f"Instituto: {instituto}\n"
        f"Cargo: {cargo}\n"
        f"Data: {data}\n"
        f"Candidatos: {cands_str}\n"
        f"🔗 <a href='https://pulso-eleitoral.fly.dev/dashboard'>Ver Dashboard</a>"
    )


def montar_mensagem_alerta(alertas: list[dict]) -> str:
    if not alertas:
        return ""

    linhas = ["🚨 <b>ALERTA — Variação Brusca Detectada</b>", ""]

    for a in alertas:
        seta = "📈" if a['direcao'] == 'up' else "📉"
        sinal = "+" if a['variacao'] > 0 else ""
        linhas.append(
            f"{seta} <b>{a['candidato']}</b>: "
            f"{a['percentual_anterior']}% → {a['percentual_atual']}% "
            f"(<b>{sinal}{a['variacao']}pp</b>)"
        )
        linhas.append(
            f"   {a['instituto_anterior']} {a['data_anterior']} → "
            f"{a['instituto_atual']} {a['data_atual']}"
        )
        linhas.append("")

    linhas.append(f"🔗 <a href='https://pulso-eleitoral.fly.dev/dashboard'>Ver Dashboard</a>")
    return "\n".join(linhas)
