import logging
import sqlite3
from abc import ABC, abstractmethod

# Configuração do Logger
logger = logging.getLogger("COLLECTOR")
logger.setLevel(logging.INFO)

# Evita duplicação de logs se o handler já estiver adicionado
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(name)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False

class BaseCollector(ABC):
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.logger = logger

    def _get_page_requests(self, url: str) -> str:
        """Faz requisição utilizando requests com headers do coletor."""
        headers = getattr(self, "HEADERS", {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Referer": "https://www.google.com.br/"
        })
        from .utils import fetch_with_retry
        return fetch_with_retry(url, headers=headers)

    @property
    @abstractmethod
    def name(self) -> str:
        """Retorna o nome do instituto de pesquisa."""
        pass

    @property
    @abstractmethod
    def instituto_id(self) -> int:
        """Retorna o ID numérico correspondente no banco de dados."""
        pass

    @abstractmethod
    def fetch(self) -> list[dict]:
        """Método abstrato que realiza a busca e parsing dos dados.
        Deve retornar uma lista de dicionários contendo os dados das pesquisas e intenções."""
        pass

    def run(self):
        """Executa o ciclo completo de coleta: busca, logs e persistência."""
        logger.info("[%s] Iniciando execução do coletor...", self.name)
        try:
            pesquisas = self.fetch()
            logger.info("[%s] Coleta concluída com sucesso. %d registros obtidos.", self.name, len(pesquisas))
            self.save(pesquisas)
            logger.info("[%s] Dados processados e salvos com sucesso.", self.name)
        except Exception as e:
            logger.error("[%s] Erro durante a execução do coletor: %s", self.name, str(e))

    def save(self, pesquisas: list[dict]):
        """Realiza a persistência das pesquisas e intenções no banco SQLite em uma transação segura.
        Normaliza os dados agrupando por (instituto_id, cargo, data_coleta, fonte_url)."""
        if not pesquisas:
            return

        from datetime import date

        # Abre conexão e grava de forma transacional
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()

        try:
            # 1. Agrupar os dicts por (instituto_id, cargo, data_coleta, fonte_url)
            groups = {}
            for item in pesquisas:
                inst_id = item.get("instituto_id", self.instituto_id)
                cargo = item.get("cargo", "presidente")
                dt_coleta = item.get("data_coleta")
                url = item.get("fonte_url") or ""
                
                # Fallback para data_coleta
                if not dt_coleta:
                    dt_coleta = date.today().isoformat()
                    
                key = (inst_id, cargo, dt_coleta, url)
                if key not in groups:
                    groups[key] = []
                groups[key].append(item)

            n_pesquisas = 0
            n_intencoes = 0

            # 2. Para cada grupo
            for (inst_id, cargo, dt_coleta, url), group_items in groups.items():
                # a. Verifica se já existe registro em pesquisas com mesmo instituto_id + cargo + fonte_url
                cursor.execute(
                    "SELECT id FROM pesquisas WHERE instituto_id=? AND cargo=? AND fonte_url=?",
                    (inst_id, cargo, url)
                )
                row = cursor.fetchone()
                
                if row:
                    pesquisa_id = row[0]
                    # Atualiza data_pesquisa se o item traz uma data real (não apenas hoje)
                    first = group_items[0]
                    data_pesquisa_real = first.get("data_pesquisa")
                    if data_pesquisa_real and data_pesquisa_real != dt_coleta:
                        cursor.execute(
                            "UPDATE pesquisas SET data_pesquisa=? WHERE id=?",
                            (data_pesquisa_real, pesquisa_id)
                        )
                    # Limpa as intenções anteriores para evitar duplicação
                    cursor.execute("DELETE FROM intencoes WHERE pesquisa_id = ?", (pesquisa_id,))
                else:
                    # b. Se não existe: INSERT INTO pesquisas
                    first = group_items[0]
                    margem_erro = first.get("margem_erro")
                    if margem_erro is not None:
                        import re as _re
                        _m = _re.search(r'[\d]+[.,]?[\d]*', str(margem_erro))
                        margem_erro = float(_m.group().replace(',', '.')) if _m else 0.0
                    else:
                        margem_erro = 0.0
                    tamanho_amostra = first.get("tamanho_amostra")
                    if tamanho_amostra is None:
                        tamanho_amostra = 0
                    metodologia = first.get("metodologia") or "Não informado"
                    data_divulgacao = first.get("data_divulgacao") or dt_coleta
                    registro_tse = first.get("registro_tse") or f"GEN-{inst_id}-{cargo}-{dt_coleta}-{hash(url)}"

                    data_pesquisa = first.get("data_pesquisa") or dt_coleta

                    cursor.execute("""
                        INSERT INTO pesquisas
                        (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        inst_id,
                        cargo,
                        data_pesquisa,
                        data_divulgacao,
                        tamanho_amostra,
                        margem_erro,
                        metodologia,
                        registro_tse,
                        url
                    ))
                    pesquisa_id = cursor.lastrowid
                    n_pesquisas += 1

                # d. Para cada candidato do grupo:
                for item in group_items:
                    candidato = item.get("candidato")
                    percentual = item.get("percentual")
                    partido = item.get("partido")  # None por padrão
                    tipo = item.get("tipo") or "estimulada"

                    cursor.execute("""
                        INSERT OR REPLACE INTO intencoes (pesquisa_id, candidato, percentual, partido, tipo)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        pesquisa_id,
                        candidato,
                        percentual,
                        partido,
                        tipo
                    ))
                    n_intencoes += 1

            conn.commit()
            logger.info("[COLLECTOR] Salvo: %d pesquisas, %d intenções", n_pesquisas, n_intencoes)
        except Exception as e:
            conn.rollback()
            logger.error("[COLLECTOR] Erro ao salvar pesquisas no banco: %s", str(e))
        finally:
            conn.close()

    def _parse_com_gemini(self, html: str, url: str,
                           instituto_id: int,
                           permite_regional: bool = False) -> list[dict]:
        """
        Extrai texto limpo do HTML e usa Gemini para estruturar os dados.
        Retorna lista de dicts no formato padrão do save().
        """
        from collectors.gemini_extractor import extrair_com_gemini
        from bs4 import BeautifulSoup
        from datetime import date
        
        # Extrai texto limpo
        soup = BeautifulSoup(html, 'lxml')
        # Remove scripts, styles, nav, footer
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()
        texto = soup.get_text(separator=' ', strip=True)
        
        if len(texto) < 50:
            self.logger.warning(f"Texto muito curto em {url}: {len(texto)} chars")
            return []
        
        resultado = extrair_com_gemini(texto, fonte_url=url, permite_regional=permite_regional)
        candidatos = resultado.get("candidatos", [])
        
        if not candidatos:
            return []
        
        hoje = date.today().isoformat()
        
        # Determina o instituto_id (com detecção para Poder360)
        inst_id = instituto_id
        if inst_id == 0:
            inst_name = resultado.get("instituto") or ""
            mapping = {
                "datafolha": 1, "ibope": 2, "ipec": 2, "quaest": 3, "genial": 4,
                "atlas": 5, "paraná": 6, "parana": 6, "real time": 7, "realtime": 7
            }
            inst_id = 1
            for chave, idx in mapping.items():
                if chave in inst_name.lower() or chave in texto.lower():
                    inst_id = idx
                    break
                    
        data_real = resultado.get("data")  # YYYY-MM-DD extraída pelo Gemini, ou None
        tipo = resultado.get("tipo", "estimulada")

        return [
            {
                "instituto_id": inst_id,
                "cargo": resultado.get("cargo", "presidente"),
                "candidato": c["nome"],
                "percentual": float(c["percentual"]),
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

