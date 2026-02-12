import logging

import httpx
from common.embeddings import Embedder as SharedEmbedder

from core.config import settings
from core.models import EMBEDDING_DIM

logger = logging.getLogger(__name__)


class Embedder(SharedEmbedder):
    def __init__(self, endpoint_url: str | None = None) -> None:
        super().__init__(endpoint_url or settings.EMBEDDING_URL, dim=EMBEDDING_DIM)
        if not self.endpoint_url:
            logger.warning("EMBEDDING_URL not set; semantic search will fail")
        else:
            logger.info(
                "Embedder: TEI at %s (dim=%s)", self.endpoint_url, EMBEDDING_DIM
            )

    def _sync_post(
        self, text: str | list[str], path: str = "/embed"
    ) -> list[float] | list[list[float]]:
        if not text:
            return [] if isinstance(text, list) else [0.0] * EMBEDDING_DIM
        if not self.endpoint_url:
            raise RuntimeError("EMBEDDING_URL is not set.")
        timeout = 300.0 if path == "/embed" else 60.0
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{self.endpoint_url}{path}",
                json={"inputs": text if isinstance(text, list) else [text]},
            )
            resp.raise_for_status()
            data = resp.json()
        if path == "/embed":
            if isinstance(text, str):
                return data[0] if data and isinstance(data[0], list) else data
            return data
        return data

    def encode_sync(self, text: str | list[str]) -> list[float] | list[list[float]]:
        return self._sync_post(text, "/embed")
