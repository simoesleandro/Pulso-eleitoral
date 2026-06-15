# URL Base: https://atlasintel.org/api/v1/polls

import logging
from .base import BaseCollector, logger

class AtlasCollector(BaseCollector):
    @property
    def name(self) -> str:
        return "Atlas"

    @property
    def instituto_id(self) -> int:
        return 5

    def _parse(self, html: str) -> list[dict]:
        """Lógica futura para fazer parseamento de JSON da API da AtlasIntel."""
        pass

    def fetch(self) -> list[dict]:
        logger.info("[%s] TODO: implementar scraping real", self.name)
        return []
