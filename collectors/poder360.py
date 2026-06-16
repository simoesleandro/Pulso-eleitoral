# URL Base: https://poder360.com.br
# Listing URL: https://poder360.com.br/pesquisas-de-opiniao/

import re
import time
from datetime import date
from bs4 import BeautifulSoup
from .base import BaseCollector, logger
from .playwright_base import PlaywrightCollector
from .utils import fetch_with_retry

BASE_URL = "https://poder360.com.br"
LISTING_URL = "https://monitor.poder360.com.br/agregador-de-pesquisas"
INSTITUTO_ID_MAP = {
    "datafolha": 1,
    "ibope": 2,
    "ipec": 2,
    "quaest": 3,
    "genial": 4,
    "atlas": 5,
    "paraná": 6,
    "parana": 6,
    "real time": 7,
    "realtime": 7,
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://www.google.com.br/"
}

class Poder360Collector(PlaywrightCollector, BaseCollector):
    @property
    def name(self) -> str:
        return "Poder360"

    @property
    def instituto_id(self) -> int:
        return 0  # Identificador genérico para coletor agregador

    def _get_page(self, url: str) -> str:
        self.logger.info(f"Acessando Poder360 via Playwright: {url}")
        return self._get_page_playwright(
            url, 
            wait_selector=['table', '.agregador', '[class*="pesquisa"]'], 
            wait_seconds=5
        )

    def _extract_links(self, html: str) -> list[str]:
        """Varre o HTML da listagem de notícias de opinião e filtra links relevantes."""
        if not html:
            return []
            
        try:
            soup = BeautifulSoup(html, 'lxml')
            links = []
            
            for a in soup.find_all('a', href=True):
                href = a['href']
                # Filtra links irrelevantes (categorias, tags, paginações)
                if any(ex in href.lower() for ex in ['/category/', '/tag/', '/page/']):
                    continue
                    
                # Filtra URLs com termos importantes de pesquisas
                if any(term in href.lower() for term in ['pesquisa', 'eleicao', 'eleição', 'presidente', '2026']):
                    # Resolve URL absoluta
                    url = href
                    if href.startswith('/'):
                        url = BASE_URL + href
                    elif not href.startswith('http'):
                        url = BASE_URL + "/" + href
                    links.append(url)
                    
            # Remove duplicadas preservando a ordem
            seen = set()
            unique_links = []
            for l in links:
                if l not in seen:
                    seen.add(l)
                    unique_links.append(l)
                    
            # Limita a no máximo 8 links
            return unique_links[:8]
        except Exception as e:
            logger.warning("[%s] Erro ao extrair links da listagem: %s", self.name, str(e))
            return []

    def _detectar_instituto(self, texto: str) -> int:
        """Detecta o ID do instituto correspondente no texto da pesquisa."""
        texto_lower = texto.lower()
        for chave, inst_id in INSTITUTO_ID_MAP.items():
            if chave in texto_lower:
                return inst_id
        return 1  # Fallback Datafolha

    def _parse_release(self, html: str, url: str) -> list[dict]:
        return self._parse_com_gemini(html, url, instituto_id=self.instituto_id)

    def fetch(self) -> list[dict]:
        """Consulta a listagem do Poder360, extrai os links e processa os releases."""
        html = self._get_page(LISTING_URL)
        if not html:
            return []
            
        links = self._extract_links(html)
        
        # Se houver links extraídos, processa cada link
        if links:
            resultados = []
            for idx, link in enumerate(links):
                logger.info("[%s] Raspando release %d/%d: %s", self.name, idx + 1, len(links), link)
                html_release = self._get_page(link)
                dados = self._parse_release(html_release, link)
                resultados.extend(dados)
                time.sleep(2)
            logger.info("[%s] %d registros extraídos de %d releases", self.name, len(resultados), len(links))
            return resultados
        else:
            # Caso contrário, tenta processar o HTML da página do agregador diretamente
            logger.info("[%s] Nenhum link extraído. Processando página agregadora diretamente.", self.name)
            dados = self._parse_release(html, LISTING_URL)
            logger.info("[%s] %d registros extraídos diretamente da página agregadora", self.name, len(dados))
            return dados
