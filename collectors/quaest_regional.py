import sqlite3
import time
import unicodedata
import requests
from bs4 import BeautifulSoup
from datetime import date
from .base import BaseCollector, logger

WP_API_URL = "https://quaest.com.br/wp-json/wp/v2/posts"
BASE_URL = "https://quaest.com.br"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

# Termos que indicam pesquisa regional/estadual no slug ou título
TERMOS_REGIONAIS = ('mapa', 'estadual', 'estaduais', 'estados', 'regional', 'regionais')


def _norm(texto: str) -> str:
    return unicodedata.normalize('NFKD', texto.lower()).encode('ascii', 'ignore').decode('ascii')


class QuaestRegionalColetor(BaseCollector):
    @property
    def name(self) -> str:
        return "QuaestRegional"

    @property
    def instituto_id(self) -> int:
        return 3  # Quaest

    def _get_posts_wp_api(self) -> list[dict]:
        """Busca posts via WP REST API filtrando pelos termos regionais."""
        encontrados = {}
        for termo in ('eleicoes', 'estados', 'mapa'):
            try:
                r = requests.get(
                    WP_API_URL,
                    params={"per_page": 20, "search": termo},
                    headers={**HEADERS, "Accept": "application/json"},
                    timeout=15,
                )
                if r.status_code != 200:
                    self.logger.warning("[QuaestRegional] WP API retornou %d para search=%s", r.status_code, termo)
                    continue
                for post in r.json():
                    slug = post.get("slug", "")
                    titulo = _norm(post.get("title", {}).get("rendered", ""))
                    if any(t in _norm(slug) or t in titulo for t in TERMOS_REGIONAIS):
                        pid = post["id"]
                        if pid not in encontrados:
                            encontrados[pid] = {
                                "id": pid,
                                "slug": slug,
                                "link": post.get("link", ""),
                                "date": post.get("date", "")[:10],
                            }
            except Exception as e:
                self.logger.warning("[QuaestRegional] Erro na WP API (search=%s): %s", termo, e)

        posts = list(encontrados.values())
        self.logger.info("[QuaestRegional] %d posts regionais encontrados via WP API", len(posts))
        return posts

    def _get_page(self, url: str) -> str:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r.text
            self.logger.warning("[QuaestRegional] HTTP %d: %s", r.status_code, url)
            return ""
        except Exception as e:
            self.logger.warning("[QuaestRegional] Erro ao buscar %s: %s", url, e)
            return ""

    def _salvar_regionais(self, registros: list[dict], data_pesquisa: str) -> int:
        """Salva lista de {uf, candidato, percentual} em pesquisas_regionais."""
        if not registros:
            return 0
        hoje = date.today().isoformat()
        data_ref = data_pesquisa or hoje
        try:
            conn = sqlite3.connect(self.db_path)
            inseridos = 0
            for r in registros:
                uf = r.get("uf", "").upper().strip()
                candidato = r.get("candidato", "")
                percentual = r.get("percentual")
                data_final = r.get("data") or data_ref
                if not uf or not candidato or percentual is None:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO pesquisas_regionais "
                    "(instituto_id, data_pesquisa, uf, candidato, percentual) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (self.instituto_id, data_final, uf, candidato, float(percentual))
                )
                inseridos += 1
            conn.commit()
            conn.close()
            self.logger.info("[QuaestRegional] %d registros salvos em pesquisas_regionais", inseridos)
            return inseridos
        except Exception as e:
            self.logger.error("[QuaestRegional] Erro ao salvar regionais: %s", e)
            return 0

    def _parse_page(self, html: str, url: str, data_post: str) -> int:
        from collectors.gemini_extractor import extrair_regional_multiestado

        soup = BeautifulSoup(html, 'lxml')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()
        texto = soup.get_text(separator=' ', strip=True)

        if len(texto) < 100:
            self.logger.warning("[QuaestRegional] Texto muito curto em %s", url)
            return 0

        registros = extrair_regional_multiestado(texto, fonte_url=url)
        if not registros:
            self.logger.info("[QuaestRegional] Nenhum dado regional extraído de %s", url)
            return 0

        return self._salvar_regionais(registros, data_pesquisa=data_post)

    def fetch(self) -> list[dict]:
        """Descobre posts regionais via WP API, extrai e salva em pesquisas_regionais.
        Retorna [] porque os dados vão direto para pesquisas_regionais, não para pesquisas."""
        posts = self._get_posts_wp_api()

        total = 0
        for idx, post in enumerate(posts):
            url = post["link"]
            self.logger.info("[QuaestRegional] Post %d/%d: %s", idx + 1, len(posts), url)
            html = self._get_page(url)
            if html:
                n = self._parse_page(html, url, post["date"])
                total += n
            time.sleep(1)

        self.logger.info("[QuaestRegional] Total: %d registros regionais de %d posts", total, len(posts))
        return []
