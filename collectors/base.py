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
        Agrupa os dados pelo código único registro_tse antes de inserir na tabela de pesquisas
        e intenções."""
        if not pesquisas:
            return

        # Agrupar itens de intenção pelo registro_tse da pesquisa correspondente
        grouped = {}
        for item in pesquisas:
            tse = item.get("registro_tse")
            if not tse:
                # Fallback caso não seja provido registro_tse
                inst_id = item.get("instituto_id", self.instituto_id)
                cargo = item.get("cargo", "geral")
                dt_coleta = item.get("data_coleta", "1970-01-01")
                tse = f"GEN-{inst_id}-{cargo}-{dt_coleta}"

            if tse not in grouped:
                grouped[tse] = {
                    "metadata": {
                        "instituto_id": item.get("instituto_id", self.instituto_id),
                        "cargo": item.get("cargo"),
                        "data_pesquisa": item.get("data_coleta"),
                        "data_publicacao": item.get("data_divulgacao"),
                        "tamanho_amostra": item.get("tamanho_amostra"),
                        "margem_erro": item.get("margem_erro"),
                        "contratante": item.get("metodologia") or item.get("contratante") or "Não informado",
                        "registro_tse": tse,
                        "fonte_url": item.get("fonte_url")
                    },
                    "intencoes": []
                }

            # Adiciona a intenção de voto do candidato atual
            grouped[tse]["intencoes"].append({
                "candidato": item.get("candidato"),
                "partido": item.get("partido", "—"),
                "percentual": item.get("percentual"),
                "tipo": item.get("tipo", "estimulada")
            })

        # Abre conexão e grava de forma transacional
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()

        try:
            for tse, data in grouped.items():
                meta = data["metadata"]
                
                # Executa INSERT OR REPLACE para a pesquisa
                cursor.execute("""
                    INSERT OR REPLACE INTO pesquisas 
                    (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    meta["instituto_id"],
                    meta["cargo"],
                    meta["data_pesquisa"],
                    meta["data_publicacao"],
                    meta["tamanho_amostra"],
                    meta["margem_erro"],
                    meta["contratante"],
                    meta["registro_tse"],
                    meta["fonte_url"]
                ))
                
                # Obtém o ID da pesquisa inserida/substituída
                cursor.execute("SELECT id FROM pesquisas WHERE registro_tse = ?", (meta["registro_tse"],))
                pesquisa_row = cursor.fetchone()
                if pesquisa_row:
                    pesquisa_id = pesquisa_row["id"]
                    
                    # Limpa intenções antigas dessa pesquisa específica
                    cursor.execute("DELETE FROM intencoes WHERE pesquisa_id = ?", (pesquisa_id,))
                    
                    # Insere as novas intenções de voto
                    for intent in data["intencoes"]:
                        cursor.execute("""
                            INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo)
                            VALUES (?, ?, ?, ?, ?)
                        """, (
                            pesquisa_id,
                            intent["candidato"],
                            intent["partido"],
                            intent["percentual"],
                            intent["tipo"]
                        ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
