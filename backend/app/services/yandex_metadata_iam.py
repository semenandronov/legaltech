"""IAM-токен сервисного аккаунта из metadata (Yandex Compute / Serverless Containers)."""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_METADATA_TOKEN_URL = (
    "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token"
)
_METADATA_HEADERS = {"Metadata-Flavor": "Google"}


def fetch_sa_iam_token_from_metadata(timeout_sec: float = 2.0) -> Optional[str]:
    """Токен SA, привязанного к контейнеру (как yc iam create-token, но изнутри)."""
    try:
        import requests

        resp = requests.get(
            _METADATA_TOKEN_URL,
            headers=_METADATA_HEADERS,
            timeout=timeout_sec,
        )
        if resp.status_code != 200:
            logger.warning(
                "Metadata IAM token request failed: status=%s",
                resp.status_code,
            )
            return None
        data = resp.json()
        token = data.get("access_token")
        if isinstance(token, str) and token.strip():
            return token.strip()
    except Exception as exc:
        logger.debug("Metadata IAM token unavailable: %s", exc)
    return None


def resolve_worker_invoke_iam_token() -> Optional[str]:
    """
    Токен для Authorization при вызове worker-контейнера (serverless.containers.invoker).

    1) metadata — в Yandex Serverless с привязанным SA
    2) YANDEX_IAM_TOKEN — fallback (локальная разработка API → облачный worker)
    """
    from app.config import config

    if config.WORKER_DISPATCH_USE_METADATA_IAM:
        token = fetch_sa_iam_token_from_metadata()
        if token:
            return token

    static = (config.YANDEX_IAM_TOKEN or "").strip()
    if static:
        return static

    return None
