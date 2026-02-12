import logging
from typing import List, Union

import httpx

from common.embeddings import Embedder as SharedEmbedder
from .config import settings
from .models import EMBEDDING_DIM

logger = logging.getLogger(__name__)


class Embedder(SharedEmbedder):
    """Used only by the Python MCP server for vector search. The Bun app does not call the embedding service."""

    def __init__(self, endpoint_url: str | None = None) -> None:
        super().__init__(endpoint_url or settings.EMBEDDING_URL, dim=EMBEDDING_DIM)
