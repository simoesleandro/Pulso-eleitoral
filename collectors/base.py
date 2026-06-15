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
                # a. Verifica se já existe registro em pesquisas com mesmo instituto_id + cargo + data_pesquisa + fonte_url
                cursor.execute(
                    "SELECT id FROM pesquisas WHERE instituto_id=? AND cargo=? AND date(data_pesquisa)=? AND fonte_url=?",
                    (inst_id, cargo, dt_coleta, url)
                )
                row = cursor.fetchone()
                
                if row:
                    pesquisa_id = row[0]
                    # Limpa as intenções anteriores para evitar duplicação
                    cursor.execute("DELETE FROM intencoes WHERE pesquisa_id = ?", (pesquisa_id,))
                else:
                    # b. Se não existe: INSERT INTO pesquisas
                    first = group_items[0]
                    margem_erro = first.get("margem_erro")
                    if margem_erro is None:
                        margem_erro = 0.0
                    tamanho_amostra = first.get("tamanho_amostra")
                    if tamanho_amostra is None:
                        tamanho_amostra = 0
                    metodologia = first.get("metodologia") or "Não informado"
                    data_divulgacao = first.get("data_divulgacao") or dt_coleta
                    registro_tse = first.get("registro_tse") or f"GEN-{inst_id}-{cargo}-{dt_coleta}-{hash(url)}"

                    cursor.execute("""
                        INSERT INTO pesquisas 
                        (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        inst_id,
                        cargo,
                        dt_coleta,
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
