# URL Base: https://www.ipecinteligencia.com.br/

import logging
from .base import BaseCollector, logger

class IbopeCollector(BaseCollector):
    @property
    def name(self) -> str:
        return "Ibope/IPEC"

    @property
    def instituto_id(self) -> int:
        return 2

    def _parse(self, html: str) -> list[dict]:
        """Lógica futura para parsing do site do Ipec/Ibope."""
        pass

    def fetch(self) -> list[dict]:
        logger.info("[%s] TODO: implementar scraping real", self.name)
        return []
