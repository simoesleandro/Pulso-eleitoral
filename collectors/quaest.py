# URL Base: https://quaest.com.br/

import logging
from .base import BaseCollector, logger

class QuaestCollector(BaseCollector):
    @property
    def name(self) -> str:
        return "Quaest"

    @property
    def instituto_id(self) -> int:
        return 3

    def _parse(self, html: str) -> list[dict]:
        """Lógica futura para baixar os PDFs públicos da Quaest e extrair as tabelas."""
        pass

    def fetch(self) -> list[dict]:
        logger.info("[%s] TODO: implementar scraping real", self.name)
        return []
