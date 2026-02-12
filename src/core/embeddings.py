import logging
from typing import List, Union

import httpx

from core.config import settings
from core.models import EMBEDDING_DIM

logger = logging.getLogger(__name__)


class Embedder:
    """Used only by the Python MCP server for vector search. The Bun app does not call the embedding service."""

    def __init__(self, endpoint_url: str | None = None) -> None:
        self.endpoint_url = (endpoint_url or getattr(settings, "EMBEDDING_URL", "") or "").rstrip("/")
        if not self.endpoint_url:
            raise RuntimeError("EMBEDDING_URL is required. Set it in .env (used by Python MCP for vector search).")
        logger.info("Embedder: %s (dim=%s)", self.endpoint_url, EMBEDDING_DIM)

    def _sync_post(
        self, text: Union[str, List[str]], path: str = "/embed"
    ) -> Union[List[float], List[List[float]]]:
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

    def encode_sync(
        self, text: Union[str, List[str]]
    ) -> Union[List[float], List[List[float]]]:
        return self._sync_post(text, "/embed")
