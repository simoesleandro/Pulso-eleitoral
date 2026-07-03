import re
import time
import logging
import unicodedata
import requests

logger = logging.getLogger("COLLECTOR")

# UF_MAP unificado (fonte única) — usado por qualquer coletor que precise
# detectar menção de estado numa URL/texto de release. Mais completo que
# os UF_MAP locais que existiam duplicados em cnn_brasil.py e gazetadopovo.py.
UF_MAP = {
    'sao paulo': 'SP', 'sp': 'SP',
    'rio de janeiro': 'RJ', 'rj': 'RJ',
    'minas gerais': 'MG', 'mg': 'MG',
    'bahia': 'BA', 'ba': 'BA',
    'rio grande do sul': 'RS', 'rs': 'RS',
    'parana': 'PR', 'pr': 'PR',
    'goias': 'GO', 'go': 'GO',
    'ceara': 'CE', 'ce': 'CE',
    'pernambuco': 'PE', 'pe': 'PE',
    # 'para' (sem "Pará") é excluída de propósito: é a preposição mais comum
    # do português ("pesquisa para presidente") e gerava falso positivo
    # sistemático com o estado do Pará. A sigla 'pa' isolada continua válida.
    'pa': 'PA',
    'amazonas': 'AM', 'am': 'AM',
    'maranhao': 'MA', 'ma': 'MA',
    'santa catarina': 'SC', 'sc': 'SC',
    'mato grosso do sul': 'MS', 'ms': 'MS',
    'mato grosso': 'MT', 'mt': 'MT',
    'espirito santo': 'ES', 'es': 'ES',
    'distrito federal': 'DF', 'df': 'DF',
    'rondonia': 'RO', 'ro': 'RO',
    'tocantins': 'TO', 'to': 'TO',
    'alagoas': 'AL', 'al': 'AL',
    'sergipe': 'SE', 'se': 'SE',
    'piaui': 'PI', 'pi': 'PI',
    'rio grande do norte': 'RN', 'rn': 'RN',
    'paraiba': 'PB', 'pb': 'PB',
    'acre': 'AC', 'ac': 'AC',
    'roraima': 'RR', 'rr': 'RR',
    'amapa': 'AP', 'ap': 'AP',
}


def _norm(texto: str) -> str:
    return unicodedata.normalize('NFKD', texto.lower()).encode('ascii', 'ignore').decode('ascii')


def detectar_uf(url: str, texto: str = '') -> str | None:
    """Detecta menção de UF na URL/texto de um release. Retorna a sigla (ex: 'RJ') ou None.

    Testa chaves multi-token primeiro (mais específicas) para evitar falso
    positivo — ex: 'para' não deve casar dentro de 'parana'.
    """
    combinado = _norm(url + ' ' + texto)
    tokens = set(re.split(r'[-/\s_]', combinado))
    for chave, uf in UF_MAP.items():
        chave_tokens = set(_norm(chave).split())
        if chave_tokens.issubset(tokens):
            return uf
    return None

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
