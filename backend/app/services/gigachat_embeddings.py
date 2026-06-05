"""GigaChat Embeddings (EmbeddingsGigaR, 2560-dim) for LangChain-compatible RAG."""
from __future__ import annotations

import logging
import threading
import time
from typing import List, Optional

from langchain_core.embeddings import Embeddings

from app.config import clean_env_str, config

logger = logging.getLogger(__name__)

_embed_lock = threading.Lock()
_last_request_ts = 0.0

_gigachat_embeddings_singleton: Optional["GigaChatEmbeddings"] = None
_singleton_lock = threading.Lock()


def _min_interval_sec() -> float:
    return max(0.0, float(getattr(config, "GIGACHAT_EMBEDDING_MIN_INTERVAL_SEC", 0.12) or 0.12))


def _embedding_model() -> str:
    return str(getattr(config, "GIGACHAT_EMBEDDING_MODEL", "EmbeddingsGigaR") or "EmbeddingsGigaR")


def _expected_dim() -> int:
    return int(getattr(config, "GIGACHAT_EMBEDDING_DIM", 2560) or 2560)


def _normalize_gigachat_credentials(raw: Optional[str]) -> str:
    """Обрезка кавычек и доп. padding '=' для Authorization Key из .env."""
    creds = clean_env_str(raw)
    if not creds:
        return ""
    missing = (-len(creds) % 4)
    if missing:
        creds += "=" * missing
    return creds


class GigaChatEmbeddings(Embeddings):
    """Embeddings via GigaChat API (EmbeddingsGigaR). Serialized requests for 1-stream quota."""

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        credentials: Optional[str] = None,
        verify_ssl: Optional[bool] = None,
        scope: Optional[str] = None,
    ) -> None:
        self.model = model or _embedding_model()
        self.credentials = _normalize_gigachat_credentials(
            credentials or config.GIGACHAT_CREDENTIALS
        )
        self.verify_ssl = (
            verify_ssl if verify_ssl is not None else bool(config.GIGACHAT_VERIFY_SSL)
        )
        self.scope = scope or config.GIGACHAT_SCOPE
        self._client = None

    def is_available(self) -> bool:
        return bool(self.credentials and str(self.credentials).strip())

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from gigachat import GigaChat
        except ImportError as exc:
            raise RuntimeError(
                "gigachat package is not installed. Add gigachat to requirements-core.txt"
            ) from exc
        self._client = GigaChat(
            credentials=self.credentials,
            verify_ssl_certs=self.verify_ssl,
            scope=self.scope,
        )
        if not self.verify_ssl:
            logger.info(
                "GigaChat embeddings: SSL verification disabled (GIGACHAT_VERIFY_SSL=false). "
                "For production use a trusted CA chain and set GIGACHAT_VERIFY_SSL=true."
            )
        return self._client

    def _pace(self) -> None:
        global _last_request_ts
        interval = _min_interval_sec()
        if interval <= 0:
            return
        with _embed_lock:
            now = time.monotonic()
            wait = interval - (now - _last_request_ts)
            if wait > 0:
                time.sleep(wait)
            _last_request_ts = time.monotonic()

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if not self.is_available():
            raise RuntimeError(
                "GigaChat embeddings unavailable: set GIGACHAT_CREDENTIALS in environment"
            )
        cleaned = [str(t or "").strip() for t in texts]
        if not any(cleaned):
            return [[0.0] * _expected_dim() for _ in cleaned]

        batch_size = max(1, int(getattr(config, "GIGACHAT_EMBEDDING_BATCH_SIZE", 8) or 8))
        out: List[List[float]] = []
        client = self._get_client()
        for start in range(0, len(cleaned), batch_size):
            batch = cleaned[start : start + batch_size]
            non_empty = [t if t else " " for t in batch]
            last_exc: Optional[Exception] = None
            for attempt in range(3):
                try:
                    self._pace()
                    with _embed_lock:
                        result = client.embeddings(non_empty, model=self.model)
                    vectors = []
                    for item in result.data:
                        vec = list(item.embedding)
                        if len(vec) != _expected_dim():
                            logger.warning(
                                "GigaChat embedding dim %s != expected %s",
                                len(vec),
                                _expected_dim(),
                            )
                        vectors.append(vec)
                    if len(vectors) != len(batch):
                        raise RuntimeError(
                            f"GigaChat returned {len(vectors)} vectors for {len(batch)} inputs"
                        )
                    out.extend(vectors)
                    break
                except Exception as exc:
                    last_exc = exc
                    is_rate = "429" in str(exc) or "Too Many Requests" in str(exc)
                    if is_rate and attempt < 2:
                        time.sleep(0.5 * (2**attempt))
                        continue
                    raise
            else:
                if last_exc:
                    raise last_exc
        return out

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed_batch(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._embed_batch([text])[0]


def get_gigachat_embeddings() -> GigaChatEmbeddings:
    global _gigachat_embeddings_singleton
    with _singleton_lock:
        if _gigachat_embeddings_singleton is None:
            _gigachat_embeddings_singleton = GigaChatEmbeddings()
        return _gigachat_embeddings_singleton
