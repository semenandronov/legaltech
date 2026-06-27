"""YandexGPT Embeddings for LangChain using official Yandex Cloud ML SDK"""
from typing import List, Any, Optional
import logging
import os
import random
import socket
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from langchain_core.embeddings import Embeddings
from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.auth import APIKeyAuth
from app.config import config
from app.services.yandex_embedding_http import (
    get_embedding_http_engine,
    parse_openai_embeddings_json,
)

logger = logging.getLogger(__name__)

_tiktoken_encoding: Any = None
_tiktoken_unavailable: bool = False


def _get_tiktoken_encoding():
    """Lazy cl100k_base encoder; None if tiktoken missing or failed."""
    global _tiktoken_encoding, _tiktoken_unavailable
    if _tiktoken_unavailable:
        return None
    if _tiktoken_encoding is not None:
        return _tiktoken_encoding
    try:
        import tiktoken

        _tiktoken_encoding = tiktoken.get_encoding("cl100k_base")
        return _tiktoken_encoding
    except Exception as exc:
        logger.warning("tiktoken unavailable for embedding size estimate: %s", exc)
        _tiktoken_unavailable = True
        return None


def _estimate_token_count(text: str) -> int:
    enc = _get_tiktoken_encoding()
    if enc is None:
        # Cyrillic-heavy legal text: conservative vs char-only split.
        return max(1, int(len(text) * 0.55))
    return len(enc.encode(text))


def _embedding_chunk_char_limit() -> int:
    n = int(getattr(config, "YANDEX_EMBEDDING_MAX_INPUT_CHARS", 4000) or 4000)
    return max(512, min(n, 32000))


def _effective_max_embedding_tokens() -> int:
    cap = max(256, int(getattr(config, "YANDEX_EMBEDDING_API_TOKEN_CAP", 2048) or 2048))
    ratio = float(getattr(config, "YANDEX_EMBEDDING_TOKEN_SAFETY_RATIO", 0.85) or 0.85)
    ratio = max(0.5, min(ratio, 1.0))
    from_ratio = int(cap * ratio)
    explicit = int(getattr(config, "YANDEX_EMBEDDING_MAX_INPUT_TOKENS", 0) or 0)
    if explicit > 0:
        return max(128, min(explicit, from_ratio))
    return max(256, from_ratio)


def _embedding_segment_overlap_chars() -> int:
    n = int(getattr(config, "YANDEX_EMBEDDING_SEGMENT_OVERLAP_CHARS", 150) or 150)
    return max(0, min(500, n))


def _split_text_for_embedding(text: str, max_chars: int) -> List[str]:
    """Split oversized text into segments under max_chars (first pass before token split)."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    parts: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            window = text[start:end]
            break_at = max(
                window.rfind("\n\n"),
                window.rfind("\n"),
                window.rfind(". "),
                window.rfind(" "),
            )
            if break_at >= max_chars // 4:
                end = start + break_at + 1
        piece = text[start:end].strip()
        if piece:
            parts.append(piece)
        if end >= n:
            break
        start = max(start + 1, end)
    return parts or [text[:max_chars]]


def _split_piece_to_max_tokens(text: str, max_tokens: int, overlap_chars: int) -> List[str]:
    """
    Split so each piece has estimated token count <= max_tokens.
    Consecutive pieces overlap by overlap_chars for mean-vector stitching.
    """
    text = (text or "").strip()
    if not text:
        return []
    if _estimate_token_count(text) <= max_tokens:
        return [text]
    pieces: List[str] = []
    start = 0
    n = len(text)
    guard = 0
    overlap_chars = max(0, overlap_chars)
    while start < n and guard < n + 20:
        guard += 1
        if _estimate_token_count(text[start:]) <= max_tokens:
            tail = text[start:].strip()
            if tail:
                pieces.append(tail)
            break
        lo, hi = start + 1, n
        best = start + 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if _estimate_token_count(text[start:mid]) <= max_tokens:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        end = best
        window = text[start:end]
        break_at = max(
            window.rfind("\n\n"),
            window.rfind("\n"),
            window.rfind(". "),
            window.rfind(" "),
        )
        min_take = max(32, min(256, (end - start) // 6))
        if break_at >= min_take:
            end = start + break_at + 1
        if end <= start:
            end = start + 1
        piece = text[start:end].strip()
        # Hard cap: if estimator undershoots, trim from end until under budget.
        while piece and _estimate_token_count(piece) > max_tokens and len(piece) > 32:
            piece = piece[: max(32, len(piece) * 3 // 4)].rstrip()
        if piece:
            pieces.append(piece)
        start = max(start + 1, end - overlap_chars)
    return pieces if pieces else [text[: max(1, n)]]


def split_text_for_embedding_api(text: str) -> List[str]:
    """
    Full pipeline: char coarse split, then token-bounded pieces with overlap.
    Used by YandexEmbeddings and unit tests.
    """
    text = text or ""
    if not text.strip():
        return []
    char_cap = _embedding_chunk_char_limit()
    max_toks = _effective_max_embedding_tokens()
    overlap = _embedding_segment_overlap_chars()
    coarse = _split_text_for_embedding(text, char_cap)
    out: List[str] = []
    for chunk in coarse:
        out.extend(_split_piece_to_max_tokens(chunk, max_toks, overlap))
    return out


def _mean_embedding_vectors(vectors: List[List[float]]) -> List[float]:
    if not vectors:
        return [0.0] * 256
    if len(vectors) == 1:
        return vectors[0]
    acc = [0.0] * 256
    for v in vectors:
        for i, x in enumerate(v):
            acc[i] += x
    inv = 1.0 / float(len(vectors))
    return [x * inv for x in acc]


def _sleep_backoff(attempt: int, base: float, cap: float) -> None:
    delay = min(cap, base * (2**attempt))
    # jitter
    delay = delay * (0.8 + 0.4 * random.random())
    time.sleep(delay)


_last_embed_pace = 0.0
_embed_pace_lock = threading.Lock()
_embedding_api_lock = threading.RLock()
_embeddings_warmup_done = False
_embeddings_warmup_lock = threading.Lock()


def _max_parallel_embedding_requests() -> int:
    raw = int(getattr(config, "YANDEX_EMBEDDING_MAX_PARALLEL_REQUESTS", 0) or 0)
    if raw <= 0:
        raw = int(getattr(config, "YANDEX_EMBEDDING_BATCH_SIZE", 8) or 8)
    return max(1, min(raw, 10))


def _embedding_min_request_interval() -> float:
    return max(0.0, float(getattr(config, "YANDEX_EMBEDDING_MIN_REQUEST_INTERVAL_SEC", 0.11) or 0.11))


def _pace_embedding_request() -> None:
    """Global pacing for Yandex text vectorization quota (~10 req/s)."""
    interval = _embedding_min_request_interval()
    if interval <= 0:
        return
    global _last_embed_pace
    with _embed_pace_lock:
        now = time.monotonic()
        wait = interval - (now - _last_embed_pace)
        if wait > 0:
            time.sleep(wait)
        _last_embed_pace = time.monotonic()


def _embedding_vector_dim() -> int:
    return 256


# Backward-compatible alias for tests and callers.
_parse_openai_embeddings_json = parse_openai_embeddings_json


def _resolve_embedding_model_uri(folder_id: str, *, for_query: bool) -> str:
    """Build emb:// URI for text-search-doc (index) or text-search-query (chat search)."""
    if for_query:
        uri = (getattr(config, "YANDEX_EMBEDDING_QUERY_MODEL_URI", "") or "").strip()
        short = (getattr(config, "YANDEX_EMBEDDING_QUERY_MODEL", "") or "").strip() or (
            getattr(config, "YANDEX_EMBEDDING_MODEL", "text-search-query/latest") or ""
        ).strip()
    else:
        uri = (getattr(config, "YANDEX_EMBEDDING_DOC_MODEL_URI", "") or "").strip()
        short = (getattr(config, "YANDEX_EMBEDDING_DOC_MODEL", "text-search-doc/latest") or "").strip()

    model = uri or short
    if model.startswith("emb://"):
        return model
    if folder_id:
        if "/" in model:
            return f"emb://{folder_id}/{model}"
        return f"emb://{folder_id}/{model}/latest"
    return model


def _prepare_embedding_work(texts: List[str]) -> tuple[List[Optional[List[float]]], List[tuple[int, str]]]:
    """Map input texts to per-doc vectors (or None) and flat (doc_idx, piece) work queue."""
    max_toks = _effective_max_embedding_tokens()
    vectors: List[Optional[List[float]]] = [None] * len(texts)
    work: List[tuple[int, str]] = []

    for doc_idx, t in enumerate(texts):
        if not t or not t.strip():
            vectors[doc_idx] = [0.0] * 256
            continue
        pieces = split_text_for_embedding_api(t)
        if len(pieces) > 1:
            logger.info(
                "embedding_segments_split chars=%s pieces=%s max_tokens_est=%s",
                len(t),
                len(pieces),
                max_toks,
            )
        for piece in pieces:
            work.append((doc_idx, piece))

    return vectors, work


class YandexEmbeddings(Embeddings):
    """YandexGPT embeddings for LangChain using official SDK"""

    sdk: Any = None  # Добавляем поле sdk
    _dns_ok: bool = True

    def __init__(self, **kwargs):
        """Initialize Yandex embeddings using official SDK"""
        # gRPC resolver: in some environments CoreDNS is blocked/unreachable and grpc's c-ares
        # resolver fails with "Could not contact DNS servers". Native resolver is more robust.
        os.environ.setdefault("GRPC_DNS_RESOLVER", "native")

        # Поддерживаем оба варианта: API ключ (приоритет) или IAM токен
        self.api_key = kwargs.get("api_key", config.YANDEX_API_KEY)
        self.iam_token = kwargs.get("iam_token", config.YANDEX_IAM_TOKEN)
        self.folder_id = kwargs.get("folder_id", config.YANDEX_FOLDER_ID)

        # Инициализируем SDK
        auth = None
        if self.api_key:
            auth = APIKeyAuth(self.api_key)
            logger.info("✅ Using Yandex API key for embeddings")
        elif self.iam_token:
            auth = self.iam_token
            logger.info("✅ Using Yandex IAM token for embeddings")
        else:
            logger.warning(
                "YANDEX_API_KEY or YANDEX_IAM_TOKEN not set. "
                "Yandex embeddings will not work."
            )
            self.sdk = None
            return

        # Создаем SDK экземпляр
        try:
            # Preflight DNS check (fast fail with actionable log)
            try:
                with ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(socket.getaddrinfo, "api.cloud.yandex.net", 443, 0, 0, socket.IPPROTO_TCP)
                    fut.result(timeout=2.0)
            except Exception as dns_exc:
                self._dns_ok = False
                logger.error(
                    "❌ DNS resolution failed for api.cloud.yandex.net. "
                    "This is an environment/network issue (VPN/proxy/Docker DNS/corporate DNS). "
                    "Will attempt to fallback to OpenAI-compat HTTPS embeddings (ai.api.cloud.yandex.net). "
                    "Original error: %s",
                    dns_exc,
                    exc_info=True,
                )

            if self.folder_id:
                self.sdk = YCloudML(folder_id=self.folder_id, auth=auth)
            else:
                # SDK требует folder_id - если не указан, не инициализируем
                logger.warning("YANDEX_FOLDER_ID not set, Yandex embeddings will not work.")
                self.sdk = None
                return
        except Exception as e:
            logger.error(f"Failed to initialize Yandex Cloud ML SDK: {e}", exc_info=True)
            self.sdk = None

    def _embed_openai_compat_texts(self, texts: List[str], *, for_query: bool) -> List[List[float]]:
        """OpenAI-compat HTTPS via process-wide async engine (time-window RPS)."""
        model = _resolve_embedding_model_uri(self.folder_id or "", for_query=for_query)
        vectors, work = _prepare_embedding_work(texts)
        if not work:
            dim = _embedding_vector_dim()
            return [v if v is not None else [0.0] * dim for v in vectors]

        engine = get_embedding_http_engine()
        pieces = [piece for _, piece in work]
        piece_vectors = engine.embed_texts(
            model=model,
            texts=pieces,
            priority=for_query,
        )

        part_vecs_by_doc: dict[int, List[List[float]]] = defaultdict(list)
        for (doc_idx, _), vec in zip(work, piece_vectors):
            part_vecs_by_doc[doc_idx].append(vec)

        for doc_idx, part_vecs in part_vecs_by_doc.items():
            vectors[doc_idx] = _mean_embedding_vectors(part_vecs)

        dim = _embedding_vector_dim()
        return [v if v is not None else [0.0] * dim for v in vectors]

    def _embed_grpc_texts(self, texts: List[str], *, for_query: bool) -> List[List[float]]:
        model_name_to_use = _resolve_embedding_model_uri(self.folder_id or "", for_query=for_query)
        embeddings_model = self.sdk.models.text_embeddings(model_name_to_use)

        def _normalize_embedding(raw: Any) -> List[float]:
            emb = raw
            if isinstance(emb, tuple) and emb:
                if len(emb) == 2 and isinstance(emb[0], (list, tuple)):
                    emb = emb[0]
                else:
                    emb = list(emb)
            if isinstance(emb, tuple):
                emb = list(emb)
            if not isinstance(emb, list):
                raise RuntimeError(f"Unexpected embedding type: {type(emb)}")
            if len(emb) != 256:
                raise RuntimeError(f"Unexpected embedding length: {len(emb)}")
            if emb and not isinstance(emb[0], (int, float)):
                raise RuntimeError(f"Unexpected embedding element type: {type(emb[0])}")
            return [float(x) for x in emb]

        vectors, work = _prepare_embedding_work(texts)
        if not work:
            return [v if v is not None else [0.0] * 256 for v in vectors]

        part_vecs_by_doc: dict[int, List[List[float]]] = defaultdict(list)
        workers = min(_max_parallel_embedding_requests(), len(work))

        def _embed_piece_grpc(piece: str) -> List[float]:
            last_err: Optional[BaseException] = None
            for attempt in range(3):
                try:
                    with _embedding_api_lock:
                        _pace_embedding_request()
                    result = embeddings_model.run(piece)
                    if not result or not hasattr(result, "embedding"):
                        raise RuntimeError(
                            f"Unexpected result format from Yandex embeddings SDK: {result}"
                        )
                    return _normalize_embedding(getattr(result, "embedding", None))
                except Exception as exc:
                    last_err = exc
                    msg = str(exc).lower()
                    is_transient = any(
                        s in msg
                        for s in (
                            "dns",
                            "could not contact dns servers",
                            "unavailable",
                            "deadline exceeded",
                            "temporarily unavailable",
                            "connection reset",
                            "timed out",
                        )
                    )
                    if attempt >= 2 or not is_transient:
                        break
                    _sleep_backoff(attempt=attempt, base=0.4, cap=3.0)
            assert last_err is not None
            raise last_err

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="yandex-emb-grpc") as pool:
            futures = {pool.submit(_embed_piece_grpc, piece): doc_idx for doc_idx, piece in work}
            for fut in futures:
                doc_idx = futures[fut]
                part_vecs_by_doc[doc_idx].append(fut.result())

        for doc_idx, part_vecs in part_vecs_by_doc.items():
            vectors[doc_idx] = _mean_embedding_vectors(part_vecs)

        return [v if v is not None else [0.0] * 256 for v in vectors]

    def _embed_texts(self, texts: List[str], *, for_query: bool) -> List[List[float]]:
        if not self.sdk:
            raise ValueError(
                "Yandex Cloud ML SDK not initialized. "
                "Check YANDEX_API_KEY or YANDEX_IAM_TOKEN in .env file"
            )

        transport = (getattr(config, "YANDEX_EMBEDDINGS_TRANSPORT", "") or "openai").strip().lower()
        if transport != "openai" and self._dns_ok is False:
            logger.warning(
                "YANDEX embeddings: forcing OpenAI-compat transport due to DNS preflight failure."
            )
            transport = "openai"

        if transport == "openai":
            try:
                return self._embed_openai_compat_texts(texts, for_query=for_query)
            except Exception as e:
                logger.error("OpenAI-compat Yandex embeddings failed: %s", e, exc_info=True)
                raise

        try:
            return self._embed_grpc_texts(texts, for_query=for_query)
        except Exception as grpc_err:
            msg = str(grpc_err).lower()
            is_dns = ("could not contact dns servers" in msg) or ("errors resolving" in msg) or ("dns" in msg)
            if is_dns or "unavailable" in msg or self._dns_ok is False:
                logger.warning(
                    "Yandex embeddings gRPC failed (%s). Falling back to OpenAI-compat HTTPS.",
                    grpc_err,
                )
                return self._embed_openai_compat_texts(texts, for_query=for_query)
            raise RuntimeError(f"Yandex embeddings failed after retries: {grpc_err}") from grpc_err

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Index chunks with text-search-doc (Yandex AI Studio)."""
        return self._embed_texts(texts, for_query=False)

    def embed_query(self, text: str) -> List[float]:
        """Search queries with text-search-query (Yandex AI Studio)."""
        return self._embed_texts([text], for_query=True)[0]

    def is_available(self) -> bool:
        """Проверяет, доступны ли Yandex embeddings"""
        return bool(self.sdk is not None)


_yandex_embeddings_singleton: Optional[YandexEmbeddings] = None
_yandex_embeddings_lock = threading.Lock()


def get_yandex_embeddings() -> YandexEmbeddings:
    """Process-wide YandexEmbeddings (SDK client + DNS preflight once per worker)."""
    global _yandex_embeddings_singleton
    if _yandex_embeddings_singleton is None:
        with _yandex_embeddings_lock:
            if _yandex_embeddings_singleton is None:
                _yandex_embeddings_singleton = YandexEmbeddings()
    return _yandex_embeddings_singleton


def warmup_yandex_embeddings() -> bool:
    """Single query embedding at startup (validates transport before traffic)."""
    global _embeddings_warmup_done
    with _embeddings_warmup_lock:
        if _embeddings_warmup_done:
            return True
        embeddings = get_yandex_embeddings()
        if not embeddings.is_available():
            logger.warning("Yandex embeddings warmup skipped: SDK not available")
            return False
        embeddings.embed_query("warmup")
        _embeddings_warmup_done = True
        logger.info("Yandex embeddings warmup ok (transport=%s)", getattr(config, "YANDEX_EMBEDDINGS_TRANSPORT", "openai"))
        return True
