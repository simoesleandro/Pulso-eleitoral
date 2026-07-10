import time
import unicodedata
from bs4 import BeautifulSoup
from .base import BaseCollector, logger
from .utils import fetch_with_retry, detectar_uf as _detectar_uf_utils

BASE_URL = "https://www.cnnbrasil.com.br"
LISTING_URL = "https://www.cnnbrasil.com.br/eleicoes/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://www.google.com.br/",
}


def _norm(texto: str) -> str:
    return unicodedata.normalize('NFKD', texto.lower()).encode('ascii', 'ignore').decode('ascii')


class CnnBrasilColetor(BaseCollector):
    @property
    def name(self) -> str:
        return "CnnBrasil"

    @property
    def instituto_id(self) -> int:
        return 7  # Real Time Big Data

    def _get_page(self, url: str) -> str:
        html = fetch_with_retry(url, HEADERS, max_retries=3, delay=2.0)
        if not html:
            self.logger.warning("[CnnBrasil] Página vazia: %s", url)
        return html

    def _extract_links(self, html: str) -> list[str]:
        if not html:
            return []
        try:
            soup = BeautifulSoup(html, 'lxml')
            links = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                texto = a.get_text(strip=True)
                combinado = _norm(href + ' ' + texto)

                if '/eleicoes/' not in href:
                    continue

                if 'real-time' not in combinado and 'real time' not in combinado:
                    continue

                # Pula a própria listing page e âncoras
                href_clean = href.split('#')[0].rstrip('/')
                if href_clean in ('/eleicoes', LISTING_URL.rstrip('/')):
                    continue

                url_abs = href if href.startswith('http') else BASE_URL + href
                url_abs = url_abs.split('#')[0].rstrip('/')
                links.append(url_abs)

            seen = set()
            unique = []
            for link in links:
                if link not in seen:
                    seen.add(link)
                    unique.append(link)
            return unique[:20]
        except Exception as e:
            self.logger.warning("[CnnBrasil] Erro ao extrair links: %s", e)
            return []

    def _detectar_uf(self, url: str, texto: str = '') -> str | None:
        return _detectar_uf_utils(url, texto)

    def _parse_release(self, html: str, url: str) -> list[dict]:
        uf = self._detectar_uf(url, html[:500])
        dados = self._parse_com_gemini(
            html, url,
            instituto_id=self.instituto_id,
            permite_regional=bool(uf),
        )

        if uf and dados:
            # _salvar_regional (BaseCollector) filtra não-presidenciais antes de persistir.
            self._salvar_regional(dados, uf)
            return []

        return dados

    def fetch(self) -> list[dict]:
        html = self._get_page(LISTING_URL)
        links = self._extract_links(html)
        self.logger.info("[CnnBrasil] %d links encontrados na listing", len(links))

        resultados = []
        for idx, link in enumerate(links):
            self.logger.info("[CnnBrasil] Release %d/%d: %s", idx + 1, len(links), link)
            html_release = self._get_page(link)
            if html_release:
                dados = self._parse_release(html_release, link)
                resultados.extend(dados)
            time.sleep(1)

        self.logger.info("[CnnBrasil] %d registros nacionais de %d releases", len(resultados), len(links))
        return resultados
