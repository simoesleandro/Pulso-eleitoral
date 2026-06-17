import time
import unicodedata
from bs4 import BeautifulSoup
from .base import BaseCollector, logger
from .playwright_base import PlaywrightCollector

BASE_URL = "https://datafolha.folha.uol.com.br"
LISTING_URL = "https://datafolha.folha.uol.com.br/eleicoes/"
INSTITUTO_ID = 1

FILTRO_NACIONAL = [
    'presidente', 'nacional', 'brasil', 'primeiro turno',
    '1º turno', 'intenção de voto', 'lula', 'bolsonaro',
    'disputa presidencial', 'eleição presidencial'
]

FILTRO_ESTADUAL = [
    'pernambuco', 'bahia', 'são paulo', 'rio de janeiro',
    'minas gerais', 'goiás', 'paraná', 'ceará', 'maranhão',
    'amazonas', 'piauí', 'rio grande', 'santa catarina',
    'espírito santo', 'mato grosso', 'pará', 'fortaleza',
    'belo horizonte', 'recife', 'salvador', 'manaus',
    'governador', 'prefeito', 'senado', 'câmara'
]


def _normalizar(texto: str) -> str:
    """Lowercase e remove acentos para comparação robusta."""
    return unicodedata.normalize('NFKD', texto.lower()).encode('ascii', 'ignore').decode('ascii')


class DatafolhaCollector(PlaywrightCollector, BaseCollector):
    @property
    def name(self) -> str:
        return "Datafolha"

    @property
    def instituto_id(self) -> int:
        return INSTITUTO_ID

    def _get_page(self, url: str) -> str:
        html = self._get_page_requests(url)
        if not html or 'cookie' in html[:500].lower() or len(html) < 5000:
            self.logger.info(f"Fallback para Playwright: {url}")
            html = self._get_page_playwright(url, wait_seconds=3)
        return html

    def _extract_links(self, html: str) -> list[str]:
        if not html:
            return []

        try:
            soup = BeautifulSoup(html, 'lxml')
            links = []

            nacional_norm = [_normalizar(p) for p in FILTRO_NACIONAL]
            # Estadual usa só lower() — strip de acento causaria falsos positivos
            # ('pará' → 'para' colidiria com a preposição "para")
            estadual_lower = [p.lower() for p in FILTRO_ESTADUAL]

            for a in soup.find_all('a', href=True):
                href = a['href']
                texto = a.get_text(strip=True)

                # 1. href deve ser do domínio Datafolha ou relativo
                if not (
                    'datafolha.folha.uol.com.br' in href
                    or href.startswith('/')
                ):
                    continue

                # Exclui seções de aprovação de governo (não são pesquisas eleitorais)
                href_lower = href.lower()
                if any(p in href_lower for p in ['avaliacao-de-governo', 'aprovacao', 'rejeicao']):
                    continue

                # 2. texto OU href deve conter alguma palavra de FILTRO_NACIONAL
                combinado = _normalizar(texto + ' ' + href)
                if not any(p in combinado for p in nacional_norm):
                    continue

                # 3. texto NÃO deve conter palavras de FILTRO_ESTADUAL
                texto_lower = texto.lower()
                if any(p in texto_lower for p in estadual_lower):
                    continue

                # Resolve URL absoluta
                if href.startswith('/'):
                    url_abs = BASE_URL + href
                elif href.startswith('http'):
                    url_abs = href
                else:
                    url_abs = BASE_URL + '/' + href

                links.append(url_abs)

            # Remove duplicatas preservando ordem
            seen = set()
            unique = []
            for l in links:
                if l not in seen:
                    seen.add(l)
                    unique.append(l)

            return unique[:6]

        except Exception as e:
            logger.warning("[Datafolha] Erro ao extrair links: %s", e)
            return []

    def _parse_release(self, html: str, url: str) -> list[dict]:
        return self._parse_com_gemini(html, url, instituto_id=self.instituto_id)

    def fetch(self) -> list[dict]:
        html = self._get_page(LISTING_URL)
        links = self._extract_links(html)

        resultados = []
        for idx, link in enumerate(links):
            self.logger.info("[Datafolha] Raspando release %d/%d: %s", idx + 1, len(links), link)
            html_release = self._get_page(link)
            dados = self._parse_release(html_release, link)
            resultados.extend(dados)
            time.sleep(2)

        self.logger.info("[Datafolha] %d registros extraídos de %d releases", len(resultados), len(links))
        return resultados
