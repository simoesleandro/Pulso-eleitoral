# URL Base: https://quaest.com.br/genial

import logging
from .base import BaseCollector, logger

class GenialQuaestCollector(BaseCollector):
    @property
    def name(self) -> str:
        return "Genial/Quaest"

    @property
    def instituto_id(self) -> int:
        return 4

    def _parse(self, html: str) -> list[dict]:
        """Lógica futura para extrair dados específicos da parceria Genial/Quaest."""
        pass

    def fetch(self) -> list[dict]:
        logger.info("[%s] TODO: implementar scraping real", self.name)
        return []
