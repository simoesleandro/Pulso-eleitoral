# URL Base: https://www.paranapesquisas.com.br/

import logging
from .base import BaseCollector, logger

class ParanaPesquisasCollector(BaseCollector):
    @property
    def name(self) -> str:
        return "Paraná"

    @property
    def instituto_id(self) -> int:
        return 6

    def _parse(self, html: str) -> list[dict]:
        """Lógica futura para fazer parse das tabelas do Paraná Pesquisas."""
        pass

    def fetch(self) -> list[dict]:
        logger.info("[%s] TODO: implementar scraping real", self.name)
        return []
