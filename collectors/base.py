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

    @abstractmethod
    def _get_page(self, url: str) -> str:
        """Busca o HTML de uma URL específica (usado pelo admin coletar-url)."""

    def _parse_release(self, html: str, url: str) -> list[dict]:
        """Parseia um release individual. Default: delega ao parser Gemini."""
        return self._parse_com_gemini(html, url, self.instituto_id)

    def run(self) -> dict:
        """Executa o ciclo completo de coleta: busca, logs e persistência.
        Retorna {"status": "ok"|"parcial"|"erro", "salvas": int, "falhas": list}."""
        logger.info("[%s] Iniciando execução do coletor...", self.name)
        try:
            pesquisas = self.fetch()
            logger.info("[%s] Coleta concluída com sucesso. %d registros obtidos.", self.name, len(pesquisas))
            resultado = self.save(pesquisas)
            falhas = resultado.get("falhas", [])
            status = "parcial" if falhas else "ok"
            logger.info(
                "[%s] Persistência concluída: %d pesquisas, %d intenções, %d rejeições (%d falha(s)).",
                self.name, resultado.get("pesquisas", 0), resultado.get("intencoes", 0),
                resultado.get("rejeicoes", 0), len(falhas)
            )
            return {"status": status, "salvas": resultado.get("pesquisas", 0), "falhas": falhas}
        except Exception as e:
            logger.error("[%s] Erro durante a execução do coletor: %s", self.name, str(e))
            return {"status": "erro", "salvas": 0, "falhas": []}

    def save(self, pesquisas: list[dict]) -> dict:
        """Realiza a persistência das pesquisas e intenções no banco SQLite, commitando cada
        release (grupo instituto_id+cargo+data_coleta+fonte_url) individualmente — uma falha
        num release não derruba os demais do mesmo lote.
        Retorna {"pesquisas": int, "intencoes": int, "rejeicoes": int, "falhas": [(url, erro), ...]}."""
        vazio = {"pesquisas": 0, "intencoes": 0, "rejeicoes": 0, "falhas": []}
        if not pesquisas:
            return vazio

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
            n_rejeicoes = 0
            falhas = []

            # 2. Para cada grupo, commit individual — uma falha não derruba os demais
            for (inst_id, cargo, dt_coleta, url), group_items in groups.items():
                grupo_pesquisas = 0
                grupo_intencoes = 0
                grupo_rejeicoes = 0
                try:
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
                        # Limpa intenções e rejeições anteriores para evitar duplicação
                        cursor.execute("DELETE FROM intencoes WHERE pesquisa_id = ?", (pesquisa_id,))
                        cursor.execute("DELETE FROM rejeicoes WHERE pesquisa_id = ?", (pesquisa_id,))
                    else:
                        # b. Se não existe: INSERT INTO pesquisas
                        first = group_items[0]
                        import hashlib
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
                        registro_tse = first.get("registro_tse") or f"GEN-{inst_id}-{cargo}-{dt_coleta}-{hashlib.sha1(url.encode()).hexdigest()[:10]}"

                        data_pesquisa = first.get("data_pesquisa") or dt_coleta
                        pct_pode_mudar_voto = first.get("pct_pode_mudar_voto")

                        cursor.execute("""
                            INSERT INTO pesquisas
                            (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url, pct_pode_mudar_voto)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            inst_id,
                            cargo,
                            data_pesquisa,
                            data_divulgacao,
                            tamanho_amostra,
                            margem_erro,
                            metodologia,
                            registro_tse,
                            url,
                            pct_pode_mudar_voto
                        ))
                        pesquisa_id = cursor.lastrowid
                        grupo_pesquisas += 1

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
                        grupo_intencoes += 1

                    # e. Insere rejeições (vêm no primeiro item do grupo)
                    rejeicoes = group_items[0].get("rejeicoes") or []
                    for rej in rejeicoes:
                        nome = rej.get("nome") or rej.get("candidato")
                        pct = rej.get("percentual")
                        if nome and pct is not None:
                            cursor.execute(
                                "INSERT INTO rejeicoes (pesquisa_id, candidato, percentual) VALUES (?, ?, ?)",
                                (pesquisa_id, nome, float(pct))
                            )
                            grupo_rejeicoes += 1

                    conn.commit()
                    n_pesquisas += grupo_pesquisas
                    n_intencoes += grupo_intencoes
                    n_rejeicoes += grupo_rejeicoes
                except Exception as e:
                    conn.rollback()
                    logger.error("[COLLECTOR] Falha ao salvar release %s: %s", url, e)
                    falhas.append((url, str(e)))

            logger.info(
                "[COLLECTOR] Salvo: %d pesquisas, %d intenções, %d rejeições (%d falha(s))",
                n_pesquisas, n_intencoes, n_rejeicoes, len(falhas)
            )
            return {"pesquisas": n_pesquisas, "intencoes": n_intencoes, "rejeicoes": n_rejeicoes, "falhas": falhas}
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

        # Normaliza rejeições (mesmo mapa de nomes)
        from collectors.gemini_extractor import normalizar_nome, _to_pct
        rejeicoes_raw = resultado.get("rejeicoes") or []
        rejeicoes = []
        for r in rejeicoes_raw:
            nome_rej = normalizar_nome(r.get("nome", ""))
            pct_rej = _to_pct(r.get("percentual"))
            if nome_rej and pct_rej is not None:
                rejeicoes.append({"nome": nome_rej, "percentual": pct_rej})

        items = [
            {
                "instituto_id": inst_id,
                "cargo": resultado.get("cargo", "presidente"),
                "candidato": c["nome"],
                "percentual": _to_pct(c["percentual"]),
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
            if c.get("nome") and _to_pct(c.get("percentual")) is not None
        ]

        # Anexa rejeições e % pode mudar de voto ao primeiro item para save() persistir
        if items and rejeicoes:
            items[0]["rejeicoes"] = rejeicoes
        if items:
            items[0]["pct_pode_mudar_voto"] = resultado.get("pct_pode_mudar_voto")

        return items

    def _filtrar_presidenciais(self, dados: list[dict]) -> list[dict]:
        """A tabela pesquisas_regionais é presidencial-por-estado. Quando a UF é
        detectada na URL, uma matéria de eleição ESTADUAL (governador de GO/RS
        etc.) também casa e traz candidatos a governador — que poluiriam a visão
        presidencial por estado. Descarta quem não for candidato presidencial
        conhecido. Fail-open: se a lista não carregar, não filtra (no-op seguro,
        mesma política da normalização)."""
        from collectors.gemini_extractor import normalizar_nome
        try:
            from database import get_nomes_presidenciais
            pres = get_nomes_presidenciais()
        except Exception:
            pres = set()
        if not pres:
            return dados
        filtrados = [
            d for d in dados
            if (d.get('candidato') or '').lower().strip() in pres
            or (normalizar_nome(d.get('candidato')) or '').lower().strip() in pres
        ]
        descartados = len(dados) - len(filtrados)
        if descartados:
            self.logger.info("[%s] Regional: descartados %d candidatos não-presidenciais",
                             self.name, descartados)
        return filtrados

    def _salvar_regional(self, dados: list[dict], uf: str) -> None:
        """Filtra para candidatos presidenciais e persiste em pesquisas_regionais
        (uma linha por candidato/UF). Compartilhado pelos coletores que recortam
        intenção presidencial por estado (GazetaDoPovo, CNN Brasil). O filtro
        impede que matérias de eleição estadual (governador) contaminem a visão
        presidencial por estado."""
        dados = self._filtrar_presidenciais(dados)
        if not dados:
            return
        try:
            conn = sqlite3.connect(self.db_path)
            inseridos = 0
            for d in dados:
                conn.execute(
                    "INSERT OR REPLACE INTO pesquisas_regionais "
                    "(instituto_id, data_pesquisa, uf, candidato, percentual) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (d.get('instituto_id', self.instituto_id),
                     d.get('data_pesquisa', ''),
                     uf,
                     d['candidato'],
                     d['percentual'])
                )
                inseridos += 1
            conn.commit()
            conn.close()
            self.logger.info("[%s] Regional %s: %d intenções salvas", self.name, uf, inseridos)
        except Exception as e:
            self.logger.error("[%s] Erro ao salvar regional %s: %s", self.name, uf, e)

