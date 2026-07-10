import time
import unicodedata
from bs4 import BeautifulSoup
from .base import BaseCollector, logger
from .playwright_base import PlaywrightCollector
from .utils import fetch_with_retry, detectar_uf as _detectar_uf_utils

BASE_URL = "https://www.gazetadopovo.com.br"
LISTING_URLS = [
    "https://www.gazetadopovo.com.br/eleicoes/2026/pesquisa-eleitoral-2026/",
    "https://www.gazetadopovo.com.br/eleicoes/2026/pesquisa-eleitoral-2026/?pagina=2",
]

INSTITUTOS_ALVO = [
    'real time', 'real-time', 'realtimebigdata',
    'atlas', 'atlasintel', 'atlas intel',
    'ipespe', 'paraná', 'parana pesquisas',
    'vox populi', 'vox', 'nexus', 'btg', 'nexus pesquisas',
    'gerp', 'instituto gerp',
    'doxa', 'verita',
    'futura', 'futura inteligencia', 'futurainteligencia',
    'poderdata', 'poder data', 'poderdata/aya', 'aya',
    'meio', 'ideia', 'meio/ideia', 'canal meio',
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
    'futura':           10,
    'futurainteligencia': 10,
    'poderdata':        11,
    'poder data':       11,
    'aya':              11,
    'meio':             12,
    'ideia':            12,
    'vox populi':       13,
    'vox':              13,
    'gerp':             14,
    'instituto gerp':   14,
}

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

                # Mantém apenas links presidenciais (nacionais ou estaduais)
                if 'presidente' not in combinado:
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

            return unique[:20]
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
        if 'futura' in combinado:
            return 10
        if 'poderdata' in combinado or 'poder data' in combinado or 'aya' in combinado:
            return 11
        if 'meio' in combinado or 'ideia' in combinado:
            return 12
        if 'vox' in combinado:
            return 13
        if 'gerp' in combinado:
            return 14
        self.logger.warning("[GazetaDoPovo] Instituto não identificado em %s — usando fallback 7", url[:60])
        return 7

    def _detectar_uf(self, url: str, texto: str = '') -> str | None:
        return _detectar_uf_utils(url, texto)

    def _parse_release(self, html: str, url: str) -> list[dict]:
        uf = self._detectar_uf(url, html[:1000])
        instituto_id = self._detectar_instituto_id(html[:2000], url)
        dados = self._parse_com_gemini(html, url, instituto_id=instituto_id, permite_regional=bool(uf))

        if uf and dados:
            # _salvar_regional (BaseCollector) filtra não-presidenciais antes de persistir.
            self._salvar_regional(dados, uf)
            return []

        return dados

    def fetch(self) -> list[dict]:
        todos_links = []
        for listing_url in LISTING_URLS:
            html = self._get_page(listing_url)
            if html:
                todos_links.extend(self._extract_links(html))

        seen = set()
        unique_links = []
        for l in todos_links:
            if l not in seen:
                seen.add(l)
                unique_links.append(l)
        unique_links = unique_links[:20]

        resultados = []
        for idx, link in enumerate(unique_links):
            self.logger.info("[GazetaDoPovo] Release %d/%d: %s", idx + 1, len(unique_links), link)
            html_release = self._get_page(link)
            dados = self._parse_release(html_release, link)
            resultados.extend(dados)
            time.sleep(1)

        self.logger.info("[GazetaDoPovo] %d registros de %d releases", len(resultados), len(unique_links))
        return resultados
