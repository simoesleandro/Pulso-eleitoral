# URL Base: https://atlaspolitico.com.br
# Listing URL: https://atlaspolitico.com.br/pesquisas

import re
import time
from datetime import date
from bs4 import BeautifulSoup
from .base import BaseCollector, logger
from .playwright_base import PlaywrightCollector
from .utils import fetch_with_retry

BASE_URL = "https://atlaspolitico.com.br"
LISTING_URL = "https://atlaspolitico.com.br/pesquisas"
INSTITUTO_ID = 5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://www.google.com.br/"
}

class AtlasCollector(PlaywrightCollector, BaseCollector):
    @property
    def name(self) -> str:
        return "Atlas"

    @property
    def instituto_id(self) -> int:
        return INSTITUTO_ID

    def _get_page(self, url: str) -> str:
        # Primeiro tenta com requests (rápido)
        html = super()._get_page_requests(url)
        # Se retornar página de cookie/GDPR, usa Playwright
        if not html or 'cookie' in html[:500].lower() or len(html) < 5000:
            self.logger.info(f"Fallback para Playwright: {url}")
            html = self._get_page_playwright(url, wait_seconds=3)
        return html

    def _extract_links(self, html: str) -> list[str]:
        """Varre o HTML da listagem de notícias de política e filtra links relevantes."""
        if not html:
            return []
            
        try:
            soup = BeautifulSoup(html, 'lxml')
            links = []
            
            for a in soup.find_all('a', href=True):
                href = a['href']
                # Filtra URLs com termos eleitorais importantes
                if any(term in href.lower() for term in ['presidente', 'eleicao', 'eleição', '2026', 'pesquisa-nacional']):
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
            return unique_links
        except Exception as e:
            logger.warning("[%s] Erro ao extrair links da listagem: %s", self.name, str(e))
            return []

    def _inferir_cargo(self, url: str, text: str) -> str:
        """Infere o cargo da pesquisa eleitoral com base no texto ou na URL do release."""
        sample = text[:500].lower()
        url_lower = url.lower()
        if 'governador' in url_lower or 'governo' in url_lower or 'governador' in sample or 'governo' in sample:
            return 'governador_rj'
        return 'presidente'

    def _parse_release(self, html: str, url: str) -> list[dict]:
        return self._parse_com_gemini(html, url, instituto_id=self.instituto_id)

    def fetch(self) -> list[dict]:
        """Consulta a listagem do Atlas, extrai os links e processa os releases."""
        logger.warning("Atlas: domínio atlaspolitico.com.br fora do ar (DNS não resolve) — coletor desabilitado")
        return None
        html = self._get_page(LISTING_URL)
        if not html:
            return []
            
        links = self._extract_links(html)
        
        # Limita a no máximo 5 links
        links = links[:5]
        
        resultados = []
        for idx, link in enumerate(links):
            self.logger.info("[%s] Raspando release %d/%d: %s", self.name, idx + 1, len(links), link)
            html_release = self._get_page(link)
            dados = self._parse_release(html_release, link)
            resultados.extend(dados)
            # Respeita o servidor
            time.sleep(2)
            
        self.logger.info("[%s] %d registros extraídos de %d releases", self.name, len(resultados), len(links))
        return resultados
