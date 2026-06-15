# URL Base: https://datafolha.folha.uol.com.br/eleicoes/

import re
import requests
from bs4 import BeautifulSoup
from datetime import date
from .base import BaseCollector, logger

class DatafolhaCollector(BaseCollector):
    @property
    def name(self) -> str:
        return "Datafolha"

    @property
    def instituto_id(self) -> int:
        return 1

    def _get_listing(self, url: str) -> str:
        """Faz a requisição HTTP para a URL especificada utilizando headers realistas."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Referer": "https://www.google.com.br/"
        }
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                logger.warning("[%s] Falha ao obter listagem. Status HTTP: %d", self.name, response.status_code)
                return ""
            return response.text
        except Exception as e:
            logger.warning("[%s] Exceção ao acessar %s: %s", self.name, url, str(e))
            return ""

    def _parse(self, html: str) -> list[dict]:
        """Varre o HTML da página em busca de links sobre eleições 2026/presidente
        e extrai título, url e data da publicação."""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            results = []
            
            for a in soup.find_all('a', href=True):
                href = a['href']
                # Filtra links eleitorais de 2026 ou de pesquisas presidenciais
                if '/eleicoes/2026/' in href or '/eleicoes/presidente/' in href:
                    # Reconstrói URLs relativas se necessário
                    url = href
                    if href.startswith('/'):
                        url = "https://datafolha.folha.uol.com.br" + href
                    elif not href.startswith('http'):
                        url = "https://datafolha.folha.uol.com.br/eleicoes/" + href
                    
                    titulo = a.get_text(strip=True)
                    if not titulo:
                        continue
                    
                    # Tenta extrair a data a partir do padrão de URL da Folha: YYYY/MM/DD
                    data_texto = None
                    m = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', url)
                    if m:
                        data_texto = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                        
                    results.append({
                        'titulo': titulo,
                        'url': url,
                        'data_texto': data_texto
                    })
            
            # Deduplica os resultados por URL do artigo
            seen_urls = set()
            dedup_results = []
            for item in results:
                if item['url'] not in seen_urls:
                    seen_urls.add(item['url'])
                    dedup_results.append(item)
                    
            return dedup_results
        except Exception as e:
            logger.warning("[%s] Erro durante o parsing do HTML: %s", self.name, str(e))
            return []

    def _extract_data_from_title(self, titulo: str) -> dict:
        """Extrai intenções de voto no formato 'Nome Candidato XX%' de dentro do título."""
        try:
            matches = re.findall(r'(\w[\w\s]+?)\s+(\d{1,2})%', titulo)
            if not matches:
                return {}
            
            result = {}
            for name, val in matches:
                clean_name = name.strip()
                # Remove conjunções de ligação como "e" ou "ou" no início do nome extraído
                clean_name = re.sub(r'^(e|ou)\s+', '', clean_name, flags=re.IGNORECASE)
                result[clean_name] = float(val)
            return result
        except Exception:
            return {}

    def fetch(self) -> list[dict]:
        """Obtém os dados da página principal de eleições e formata no padrão esperado pelo BaseCollector."""
        url = "https://datafolha.folha.uol.com.br/eleicoes/"
        html = self._get_listing(url)
        if not html:
            return []
            
        items = self._parse(html)
        if not items:
            logger.warning("[%s] Datafolha: layout não reconhecido ou bloqueio. Retornando []", self.name)
            return []
            
        result = []
        today_str = date.today().isoformat()
        
        for item in items:
            extracted = self._extract_data_from_title(item['titulo'])
            for candidate, pct in extracted.items():
                result.append({
                    'instituto_id': self.instituto_id,
                    'cargo': 'presidente',
                    'candidato': candidate,
                    'percentual': pct,
                    'fonte_url': item['url'],
                    'data_coleta': today_str,
                    'data_divulgacao': item.get('data_texto'),
                    'tamanho_amostra': None,
                    'margem_erro': None,
                    'metodologia': 'Espontânea',
                    # Agrupador único por data para unificar candidatos da mesma pesquisa no banco
                    'registro_tse': f"DF-PRES-{item.get('data_texto') or today_str}"
                })
        return result
