import time
import unicodedata
from bs4 import BeautifulSoup
from .base import BaseCollector, logger
from .playwright_base import PlaywrightCollector
from .utils import fetch_with_retry

BASE_URL = "https://www.gazetadopovo.com.br"
LISTING_URL = "https://www.gazetadopovo.com.br/eleicoes/2026/pesquisa-eleitoral-2026/"

INSTITUTOS_ALVO = [
    'real time', 'real-time', 'realtimebigdata',
    'atlas', 'atlasintel', 'atlas intel',
    'ipespe', 'paraná', 'parana pesquisas',
    'vox populi', 'nexus', 'btg', 'nexus pesquisas',
    'doxa', 'verita',
]

INSTITUTO_ID_MAP = {
    'real time':  7,
    'realtime':   7,
    'real-time':  7,
    'atlas':      5,
    'atlasintel': 5,
    'ipespe':     2,
    'paraná':     6,
    'parana':     6,
    'nexus':      8,
    'btg':        8,
    'verita':     9,
}

EXCLUIR_ESTADOS = [
    'governador', 'senador', 'senado', 'deputado',
    'prefeito', 'vereador',
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://www.google.com.br/",
}


def _norm(texto: str) -> str:
    return unicodedata.normalize('NFKD', texto.lower()).encode('ascii', 'ignore').decode('ascii')


class GazetaDoPovoColetor(PlaywrightCollector, BaseCollector):
    @property
    def name(self) -> str:
        return "GazetaDoPovo"

    @property
    def instituto_id(self) -> int:
        return 7  # Real Time como padrão

    def _get_page(self, url: str) -> str:
        html = fetch_with_retry(url, HEADERS, max_retries=3, delay=2.0)
        if not html:
            self.logger.warning("[GazetaDoPovo] Página vazia: %s", url)
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

                # Deve ser URL da seção de pesquisas
                if '/eleicoes/2026/pesquisa-eleitoral-2026/' not in href:
                    continue

                # Deve mencionar instituto alvo
                if not any(_norm(inst) in combinado for inst in INSTITUTOS_ALVO):
                    continue

                # Exclui links que claramente são estaduais pelo slug
                # (mantém links ambíguos para o Gemini decidir)
                if any(excluir in combinado for excluir in EXCLUIR_ESTADOS):
                    continue

                url_abs = href if href.startswith('http') else BASE_URL + href
                # Remove âncoras (#comentarios, etc.)
                url_abs = url_abs.split('#')[0].rstrip('/')
                links.append(url_abs)

            seen = set()
            unique = []
            for link in links:
                if link not in seen:
                    seen.add(link)
                    unique.append(link)

            return unique[:15]
        except Exception as e:
            self.logger.warning("[GazetaDoPovo] Erro ao extrair links: %s", e)
            return []

    def _detectar_instituto_id(self, texto: str, url: str) -> int:
        combinado = _norm(texto + ' ' + url)
        if 'real time' in combinado or 'realtime' in combinado or 'real-time' in combinado:
            return 7
        if 'atlas' in combinado:
            return 5
        if 'parana' in combinado:
            return 6
        if 'ipespe' in combinado:
            return 2
        if 'nexus' in combinado or 'btg pactual' in combinado or 'btg' in combinado:
            return 8
        if 'verita' in combinado:
            return 9
        if 'doxa' in combinado:
            return 4
        self.logger.warning("[GazetaDoPovo] Instituto não identificado em %s — usando fallback 7", url[:60])
        return 7

    def _parse_release(self, html: str, url: str) -> list[dict]:
        instituto_id = self._detectar_instituto_id(html[:2000], url)
        return self._parse_com_gemini(html, url, instituto_id=instituto_id)

    def fetch(self) -> list[dict]:
        html = self._get_page(LISTING_URL)
        if not html:
            return []

        links = self._extract_links(html)
        resultados = []

        for idx, link in enumerate(links):
            self.logger.info("[GazetaDoPovo] Release %d/%d: %s", idx + 1, len(links), link)
            html_release = self._get_page(link)
            dados = self._parse_release(html_release, link)
            resultados.extend(dados)
            time.sleep(1)

        self.logger.info("[GazetaDoPovo] %d registros de %d releases", len(resultados), len(links))
        return resultados
