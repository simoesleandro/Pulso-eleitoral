# URL Base: https://realtimebigdata.com.br/

import logging
from .base import BaseCollector, logger

class RealTimeCollector(BaseCollector):
    @property
    def name(self) -> str:
        return "Real Time"

    @property
    def instituto_id(self) -> int:
        return 7

    def _parse(self, html: str) -> list[dict]:
        """Lógica futura para fazer parseamento de notícias e PDFs da Real Time."""
        pass

    def fetch(self) -> list[dict]:
        logger.info("[%s] TODO: implementar scraping real", self.name)
        return []
