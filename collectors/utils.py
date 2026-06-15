import time
import logging
import requests

logger = logging.getLogger("COLLECTOR")

def fetch_with_retry(url: str, headers: dict, max_retries: int = 3, delay: float = 2.0) -> str:
    """Tenta obter o HTML de uma URL com suporte a re-tentativas (retry) e backoff linear.
    Nunca levanta exceções e loga erros caso todas as tentativas falhem."""
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                return response.text
            else:
                logger.warning(
                    "[UTILS] Tentativa %d/%d falhou para %s. Status HTTP: %d", 
                    attempt, max_retries, url, response.status_code
                )
        except Exception as e:
            logger.warning(
                "[UTILS] Tentativa %d/%d falhou para %s devido ao erro: %s", 
                attempt, max_retries, url, str(e)
            )
        
        # Se ainda houver tentativas, aguarda aplicando o backoff linear
        if attempt < max_retries:
            wait_time = delay * attempt
            logger.info("[UTILS] Aguardando %.1f segundos antes de tentar novamente...", wait_time)
            time.sleep(wait_time)
            
    logger.error("[UTILS] Todas as %d tentativas de requisição para %s falharam.", max_retries, url)
    return ""
