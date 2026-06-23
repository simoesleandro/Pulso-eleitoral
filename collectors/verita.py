# URL Base: https://eleicoes26.institutoverita.com.br
# Listing URL: https://eleicoes26.institutoverita.com.br/
#
# Estratégia de extração:
#   1. Playwright carrega a SPA e extrai a URL do PDF embutida na página
#   2. requests baixa o PDF do Supabase
#   3. pdfplumber extrai o texto do PDF
#   4. _parse_com_gemini() estrutura os dados

import io
import time
import requests
import pdfplumber
from bs4 import BeautifulSoup
from .base import BaseCollector, logger
from .playwright_base import PlaywrightCollector

BASE_URL = "https://eleicoes26.institutoverita.com.br"
LISTING_URL = "https://eleicoes26.institutoverita.com.br/"
INSTITUTO_ID = 9

URLS_CONHECIDAS = [
    "https://eleicoes26.institutoverita.com.br/pesquisa/e13762d1-0545-4e9d-b26b-1e30b966b494",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/pdf,*/*",
    "Referer": BASE_URL,
}


class VeritaCollector(PlaywrightCollector, BaseCollector):
    @property
    def name(self) -> str:
        return "Verita"

    @property
    def instituto_id(self) -> int:
        return INSTITUTO_ID

    def _get_page(self, url: str, wait_selector=None) -> str:
        """SPA React — sempre usa Playwright; nunca tenta requests."""
        return self._get_page_playwright(
            url,
            wait_selector=wait_selector or "main",
            wait_seconds=5,
        )

    def _extract_links(self, html: str) -> list[str]:
        """Extrai links /pesquisa/{uuid} da página de listagem."""
        if not html:
            return []
        try:
            soup = BeautifulSoup(html, 'lxml')
            seen = set()
            unique = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/pesquisa/' in href:
                    url = href if href.startswith('http') else BASE_URL + href
                    if url not in seen:
                        seen.add(url)
                        unique.append(url)
            return unique
        except Exception as e:
            self.logger.warning("[Verita] Erro ao extrair links: %s", e)
            return []

    def _extract_pdf_url(self, html: str) -> str | None:
        """Extrai a URL do PDF da página de pesquisa individual."""
        try:
            soup = BeautifulSoup(html, 'lxml')
            for a in soup.find_all('a', href=True):
                if '/pesquisas/pdfs/' in a['href']:
                    return a['href']
        except Exception as e:
            self.logger.warning("[Verita] Erro ao extrair URL do PDF: %s", e)
        return None

    def _download_pdf_text(self, pdf_url: str) -> str:
        """Baixa o PDF e retorna o texto extraído com pdfplumber."""
        try:
            resp = requests.get(pdf_url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                partes = [page.extract_text() or "" for page in pdf.pages]
            return "\n".join(partes).strip()
        except Exception as e:
            self.logger.error("[Verita] Falha ao baixar/extrair PDF %s: %s", pdf_url, e)
            return ""

    def _parse_release(self, html: str, url: str) -> list[dict]:
        pdf_url = self._extract_pdf_url(html)
        if not pdf_url:
            self.logger.warning("[Verita] PDF não encontrado em %s", url)
            return []

        self.logger.info("[Verita] PDF encontrado: %s", pdf_url)
        texto = self._download_pdf_text(pdf_url)
        if not texto:
            self.logger.warning("[Verita] Texto vazio do PDF em %s", pdf_url)
            return []

        self.logger.info("[Verita] PDF extraído: %d chars", len(texto))
        return self._parse_com_gemini(texto, url, instituto_id=self.instituto_id)

    def fetch(self) -> list[dict]:
        html_listing = self._get_page(LISTING_URL, wait_selector="a[href*='/pesquisa/']")
        links = self._extract_links(html_listing)

        seen = set(links)
        for url in URLS_CONHECIDAS:
            if url not in seen:
                links.append(url)
                seen.add(url)

        resultados = []
        for idx, link in enumerate(links):
            self.logger.info("[Verita] Pesquisa %d/%d: %s", idx + 1, len(links), link)
            html = self._get_page(link)
            dados = self._parse_release(html, link)
            resultados.extend(dados)
            time.sleep(2)

        self.logger.info("[Verita] %d registros de %d pesquisas", len(resultados), len(links))
        return resultados
