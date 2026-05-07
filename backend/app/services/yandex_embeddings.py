"""YandexGPT Embeddings for LangChain using official Yandex Cloud ML SDK"""
from typing import List, Any, Optional
import logging
import os
import random
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from langchain_core.embeddings import Embeddings
from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.auth import APIKeyAuth
from app.config import config

logger = logging.getLogger(__name__)

def _sleep_backoff(attempt: int, base: float, cap: float) -> None:
    delay = min(cap, base * (2**attempt))
    # jitter
    delay = delay * (0.8 + 0.4 * random.random())
    time.sleep(delay)


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
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed documents using YandexGPT via official SDK
        
        Args:
            texts: List of texts to embed
        
        Returns:
            List of embedding vectors
        """
        if not self.sdk:
            raise ValueError(
                "Yandex Cloud ML SDK not initialized. "
                "Check YANDEX_API_KEY or YANDEX_IAM_TOKEN in .env file"
            )

        def _embed_via_openai_compat(_texts: List[str]) -> List[List[float]]:
            from app.services.yandex_openai_llm import yandex_openai_sdk_client

            model_uri = (getattr(config, "YANDEX_EMBEDDING_MODEL_URI", "") or "").strip()
            model_name = (getattr(config, "YANDEX_EMBEDDING_MODEL", "text-search-query/latest") or "").strip()
            model = model_uri or model_name
            # For OpenAI-compat, prefer full emb:// URI when folder is known.
            if not model.startswith("emb://") and self.folder_id:
                if "/" in model:
                    model = f"emb://{self.folder_id}/{model}"
                else:
                    model = f"emb://{self.folder_id}/{model}/latest"

            client = yandex_openai_sdk_client()
            # Yandex OpenAI-compat embeddings API: input must be an array of exactly ONE string per request.
            vectors: List[List[float]] = []
            for t in _texts:
                if not t or not t.strip():
                    vectors.append([0.0] * 256)
                    continue
                resp = client.embeddings.create(
                    model=model,
                    input=[t],
                    encoding_format="float",
                )
                data = getattr(resp, "data", None) or []
                if len(data) != 1:
                    raise RuntimeError(
                        f"OpenAI-compat embeddings: expected 1 vector per request, got {len(data)}"
                    )
                emb = getattr(data[0], "embedding", None)
                if isinstance(emb, tuple):
                    emb = list(emb)
                if not isinstance(emb, list) or len(emb) != 256:
                    raise RuntimeError(
                        f"OpenAI-compat embeddings: unexpected embedding format/size: "
                        f"{type(emb)} len={len(emb) if isinstance(emb, list) else 'n/a'}"
                    )
                vectors.append([float(x) for x in emb])
            return vectors

        transport = (getattr(config, "YANDEX_EMBEDDINGS_TRANSPORT", "") or "openai").strip().lower()
        # If DNS/service discovery is broken for gRPC endpoint, do not waste time on gRPC retries.
        if transport != "openai" and self._dns_ok is False:
            logger.warning(
                "YANDEX embeddings: forcing OpenAI-compat transport due to DNS preflight failure (api.cloud.yandex.net)."
            )
            transport = "openai"
        if transport == "openai":
            try:
                return _embed_via_openai_compat(texts)
            except Exception as e:
                logger.error("OpenAI-compat Yandex embeddings failed: %s", e, exc_info=True)
                raise

        embeddings: List[List[float]] = []
        
        try:
            # Используем полный URI из конфига, если указан
            embedding_model_uri = getattr(config, 'YANDEX_EMBEDDING_MODEL_URI', '')
            embedding_model_name = embedding_model_uri or getattr(config, 'YANDEX_EMBEDDING_MODEL', 'text-search-query')
            
            # Если model_name не полный URI и folder_id есть, формируем полный URI
            if not embedding_model_name.startswith("emb://") and self.folder_id:
                # Формируем полный URI из короткого имени
                # Добавляем /latest если версия не указана
                if "/" in embedding_model_name:
                    # Уже есть версия (например, text-search-query/latest)
                    model_name_to_use = f"emb://{self.folder_id}/{embedding_model_name}"
                else:
                    # Только имя модели, добавляем /latest
                    model_name_to_use = f"emb://{self.folder_id}/{embedding_model_name}/latest"
                logger.info(f"Converted short embedding model name to full URI: {model_name_to_use}")
            elif embedding_model_name.startswith("emb://"):
                model_name_to_use = embedding_model_name
                logger.debug(f"Using full embedding model URI: {model_name_to_use}")
            else:
                model_name_to_use = embedding_model_name
                logger.warning(f"Using short embedding model name without folder_id (may fail): {model_name_to_use}")
            
            # Получаем модель embeddings
            embeddings_model = self.sdk.models.text_embeddings(model_name_to_use)

            def _normalize_embedding(raw: Any) -> List[float]:
                """
                Normalize embedding payloads across SDK/runtime variants.
                Expected: list[float] length 256.
                Accept: tuple[float] length 256; or (vector, meta) tuples.
                """
                emb = raw
                # Some SDK builds may return (embedding, meta) or similar.
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
                # Quick numeric sanity check (avoid silently accepting garbage).
                if emb and not isinstance(emb[0], (int, float)):
                    raise RuntimeError(f"Unexpected embedding element type: {type(emb[0])}")
                return [float(x) for x in emb]
            
            # Обрабатываем каждый текст
            for text in texts:
                # Пустые тексты — детерминированно возвращаем нули, без сетевых вызовов.
                if not text or not text.strip():
                    embeddings.append([0.0] * 256)
                    continue

                last_err: Optional[BaseException] = None
                for attempt in range(3):
                    try:
                        logger.debug("Embedding text (length: %s) via Yandex SDK (attempt %s)", len(text), attempt + 1)
                        result = embeddings_model.run(text)
                        if not result or not hasattr(result, "embedding"):
                            raise RuntimeError(f"Unexpected result format from Yandex embeddings SDK: {result}")
                        embedding = _normalize_embedding(getattr(result, "embedding", None))
                        embeddings.append(embedding)
                        last_err = None
                        break
                    except Exception as e:
                        last_err = e
                        # Retry only transient network / DNS / gRPC errors (best-effort by message).
                        msg = str(e).lower()
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

                if last_err is not None:
                    msg = str(last_err).lower()
                    is_dns = ("could not contact dns servers" in msg) or ("errors resolving" in msg) or ("dns" in msg)
                    is_unavailable = "unavailable" in msg
                    if is_dns or is_unavailable or (self._dns_ok is False):
                        logger.warning(
                            "Yandex embeddings gRPC failed (%s). Falling back to OpenAI-compat HTTPS embeddings.",
                            last_err,
                        )
                        try:
                            return _embed_via_openai_compat(texts)
                        except Exception as openai_err:
                            logger.error(
                                "Fallback OpenAI-compat embeddings also failed: %s", openai_err, exc_info=True
                            )
                            raise RuntimeError(
                                f"Yandex embeddings failed (grpc + openai-compat fallback). "
                                f"grpc_error={last_err}; openai_error={openai_err}"
                            ) from openai_err

                    # IMPORTANT: do not silently degrade retrieval quality
                    raise RuntimeError(f"Yandex embeddings failed after retries: {last_err}") from last_err
                    
        except Exception as e:
            logger.error(f"Error initializing embeddings model: {e}", exc_info=True)
            raise
        
        return embeddings
    
    def embed_query(self, text: str) -> List[float]:
        """
        Embed a single query text
        
        Args:
            text: Text to embed
        
        Returns:
            Embedding vector
        """
        embeddings = self.embed_documents([text])
        return embeddings[0]
    
    def is_available(self) -> bool:
        """Проверяет, доступны ли Yandex embeddings"""
        return bool(self.sdk is not None)
