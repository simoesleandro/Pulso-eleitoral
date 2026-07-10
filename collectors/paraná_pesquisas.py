# URL Base: https://paranapesquisas.com.br
# Listing URL: https://paranapesquisas.com.br/pesquisas/
#
# Estratégia de extração (governador do RJ):
#   1. Baixa a listagem e extrai links de releases de pesquisa do RJ
#   2. Em cada release, extrai a URL do PDF do relatório (não o do registro TSE)
#   3. requests baixa o PDF; pdfplumber extrai o texto
#   4. extrair_governador_rj() estrutura os dados (cargo forçado governador_rj)
#
# Os números do Paraná Pesquisas ficam SÓ no PDF — a página HTML não os traz.
# Só releases do Rio de Janeiro são processados (o instituto publica vários estados).

import io
import time
import requests
import pdfplumber
from datetime import date
from bs4 import BeautifulSoup
from .base import BaseCollector, logger
from .playwright_base import PlaywrightCollector

BASE_URL = "https://paranapesquisas.com.br"
LISTING_URL = "https://paranapesquisas.com.br/pesquisas/"
INSTITUTO_ID = 6

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": BASE_URL,
}

# Marcadores de que o release/PDF é do Rio de Janeiro.
_RJ_MARKERS = ("rio-de-janeiro", "rio_de_janeiro", "-rj-", "_rj_", "rj-04", "/rj/")


def _e_release_rj(href: str) -> bool:
    h = href.lower()
    return "/pesquisas/" in h and any(m in h for m in _RJ_MARKERS)


def _e_pdf_registro(filename: str) -> bool:
    """O PDF de registro no TSE (não é o relatório com os números)."""
    f = filename.lower()
    return "registrotse" in f or "registro_tse" in f or f.startswith("1-job")


class ParanaPesquisasCollector(PlaywrightCollector, BaseCollector):
    @property
    def name(self) -> str:
        return "Paraná"

    @property
    def instituto_id(self) -> int:
        return INSTITUTO_ID

    def _get_page(self, url: str) -> str:
        """requests primeiro (rápido); Playwright como fallback se vier vazio/curto."""
        html = super()._get_page_requests(url)
        if not html or len(html) < 2000:
            self.logger.info("[Paraná] Fallback para Playwright: %s", url)
            html = self._get_page_playwright(url, wait_seconds=3)
        return html

    def _extract_links(self, html: str) -> list[str]:
        """Extrai links de releases de pesquisa do RJ da página de listagem."""
        if not html:
            return []
        try:
            soup = BeautifulSoup(html, 'lxml')
            seen = set()
            unique = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                if not _e_release_rj(href):
                    continue
                url = href if href.startswith('http') else BASE_URL + '/' + href.lstrip('/')
                if url not in seen:
                    seen.add(url)
                    unique.append(url)
            return unique
        except Exception as e:
            self.logger.warning("[Paraná] Erro ao extrair links: %s", e)
            return []

    def _extract_pdf_url(self, html: str) -> str | None:
        """Extrai a URL do PDF do relatório (ignora o PDF de registro no TSE)."""
        if not html:
            return None
        try:
            soup = BeautifulSoup(html, 'lxml')
            candidatos = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                if not href.lower().split('?')[0].endswith('.pdf'):
                    continue
                url = href if href.startswith('http') else BASE_URL + '/' + href.lstrip('/')
                filename = url.split('/')[-1]
                if _e_pdf_registro(filename):
                    continue
                candidatos.append(url)
            # Prefere um PDF cujo nome mencione RJ; senão o primeiro relatório.
            for url in candidatos:
                if 'rj' in url.split('/')[-1].lower():
                    return url
            return candidatos[0] if candidatos else None
        except Exception as e:
            self.logger.warning("[Paraná] Erro ao extrair URL do PDF: %s", e)
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
            self.logger.error("[Paraná] Falha ao baixar/extrair PDF %s: %s", pdf_url, e)
            return ""

    def _build_items(self, resultado: dict, url: str) -> list[dict]:
        """Monta os itens no formato de save() a partir da saída do extrator."""
        candidatos = resultado.get("candidatos") or []
        if not candidatos:
            return []
        hoje = date.today().isoformat()
        data_real = resultado.get("data")
        tipo = resultado.get("tipo", "estimulada")
        return [
            {
                "instituto_id": self.instituto_id,
                "cargo": "governador_rj",
                "candidato": c["nome"],
                "percentual": c["percentual"],
                "tipo": tipo,
                "data_pesquisa": data_real or hoje,
                "data_coleta": hoje,
                "data_divulgacao": data_real,
                "tamanho_amostra": resultado.get("tamanho_amostra"),
                "margem_erro": resultado.get("margem_erro"),
                "fonte_url": url,
                "metodologia": "Espontânea" if tipo == "espontanea" else "Estimulada",
            }
            for c in candidatos
            if c.get("nome") and c.get("percentual") is not None
        ]

    def _parse_release(self, html: str, url: str) -> list[dict]:
        from .gemini_extractor import extrair_governador_rj
        pdf_url = self._extract_pdf_url(html)
        if not pdf_url:
            self.logger.warning("[Paraná] PDF do relatório não encontrado em %s", url)
            return []
        self.logger.info("[Paraná] PDF: %s", pdf_url.split('/')[-1])

        texto = self._download_pdf_text(pdf_url)
        if not texto:
            self.logger.warning("[Paraná] Texto vazio do PDF em %s", pdf_url)
            return []
        self.logger.info("[Paraná] PDF extraído: %d chars", len(texto))

        resultado = extrair_governador_rj(texto, fonte_url=url)
        return self._build_items(resultado, url)

    def fetch(self) -> list[dict]:
        html_listing = self._get_page(LISTING_URL)
        links = self._extract_links(html_listing)
        self.logger.info("[Paraná] %d releases do RJ na listagem", len(links))

        resultados = []
        for idx, link in enumerate(links[:10]):
            self.logger.info("[Paraná] Release %d/%d: %s", idx + 1, min(len(links), 10), link)
            html = self._get_page(link)
            resultados.extend(self._parse_release(html, link))
            time.sleep(2)

        self.logger.info("[Paraná] %d registros de %d releases", len(resultados), min(len(links), 10))
        return resultados
