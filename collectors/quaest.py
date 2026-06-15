# URL Base: https://quaest.com.br
# Listing URL: https://quaest.com.br/category/politica/

import re
import time
from datetime import date
from bs4 import BeautifulSoup
from .base import BaseCollector, logger
from .utils import fetch_with_retry

BASE_URL = "https://quaest.com.br"
LISTING_URL = "https://quaest.com.br/category/politica/"
INSTITUTO_ID = 3
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://www.google.com.br/"
}

class QuaestCollector(BaseCollector):
    @property
    def name(self) -> str:
        return "Quaest"

    @property
    def instituto_id(self) -> int:
        return INSTITUTO_ID

    def _get_page(self, url: str) -> str:
        """Faz requisição utilizando o utilitário com re-tentativas (retry)."""
        return fetch_with_retry(url, headers=HEADERS)

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
                if any(term in href.lower() for term in ['presidente', 'eleicao', 'eleicao', '2026', 'pesquisa-nacional']):
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
        """Extrai dados de pesquisas e candidatos do texto de um release individual da Quaest."""
        if not html:
            return []
            
        try:
            soup = BeautifulSoup(html, 'lxml')
            text = soup.get_text()
            
            # 1. Busca candidatos e percentuais
            candidate_regex = r'([A-ZÀ-Ú][a-zà-ú]+(?:[^\S\r\n][A-ZÀ-Ú][a-zà-ú]+)*)\s*[:\-]?\s*(\d{1,2})[\s]*%'
            matches = re.findall(candidate_regex, text)
            
            # 2. Busca data
            data_divulgacao = None
            date_regex = r'(\d{1,2})\s+de\s+(janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+de\s+(\d{4})'
            date_match = re.search(date_regex, text, re.IGNORECASE)
            if date_match:
                dia = int(date_match.group(1))
                mes_nome = date_match.group(2).lower()
                ano = date_match.group(3)
                meses = {
                    "janeiro": "01", "fevereiro": "02", "março": "03", "abril": "04", 
                    "maio": "05", "junho": "06", "julho": "07", "agosto": "08", 
                    "setembro": "09", "outubro": "10", "novembro": "11", "dezembro": "12"
                }
                mes = meses.get(mes_nome, "01")
                data_divulgacao = f"{ano}-{mes}-{dia:02d}"
                
            # 3. Busca tamanho de amostra
            tamanho_amostra = None
            sample_match = re.search(r'(\d[\d\.]+)\s+entrevistados?', text)
            if sample_match:
                tamanho_amostra = int(sample_match.group(1).replace(".", ""))
                
            # 4. Busca margem de erro
            margem_erro = None
            margin_match = re.search(r'margem\s+de\s+erro\s+de\s+(\d[\d,]*)\s*(?:ponto|pp|%)', text, re.IGNORECASE)
            if margin_match:
                margem_erro = float(margin_match.group(1).replace(",", "."))
                
            # 5. Infere o cargo
            cargo = self._inferir_cargo(url, text)
            
            # 6. Monta resultados
            resultados = []
            hoje_iso = date.today().isoformat()
            
            # Lista de candidatos válidos monitorados para filtrar ruídos do regex
            candidatos_validos = {
                'lula', 'bolsonaro', 'tarcísio', 'tarcisio', 'ciro', 'simone', 
                'eduardo paes', 'cláudio castro', 'claudio castro', 'marcelo freixo', 
                'rodrigo neves', 'outros', 'brancos', 'nulos', 'indecisos'
            }
            
            for name, val in matches:
                clean_name = name.strip()
                clean_name = re.sub(r'^(e|ou)\s+', '', clean_name, flags=re.IGNORECASE)
                
                if clean_name.lower() in candidatos_validos:
                    resultados.append({
                        "instituto_id": self.instituto_id,
                        "cargo": cargo,
                        "candidato": clean_name,
                        "percentual": float(val),
                        "data_coleta": hoje_iso,
                        "data_divulgacao": data_divulgacao,
                        "tamanho_amostra": tamanho_amostra,
                        "margem_erro": margem_erro,
                        "fonte_url": url,
                        "metodologia": "Espontânea"
                    })
            return resultados
        except Exception as e:
            logger.warning("[%s] Erro no parsing do release %s: %s", self.name, url, str(e))
            return []

    def fetch(self) -> list[dict]:
        """Consulta a listagem, filtra os links e extrai dados dos 5 mais recentes."""
        html = self._get_page(LISTING_URL)
        if not html:
            return []
            
        links = self._extract_links(html)
        # Limita a 5 links mais recentes
        links = links[:5]
        
        resultados = []
        for idx, link in enumerate(links):
            logger.info("[%s] Raspando release %d/%d: %s", self.name, idx + 1, len(links), link)
            html_release = self._get_page(link)
            dados = self._parse_release(html_release, link)
            resultados.extend(dados)
            # Respeita o servidor aplicando sleep
            time.sleep(2)
            
        logger.info("[%s] %d registros extraídos de %d releases", self.name, len(resultados), len(links))
        return resultados
