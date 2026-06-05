"""Постановка файлов в обработку: локально или на worker-контейнер."""
from __future__ import annotations

import asyncio
import logging
from typing import List

from app.config import config
from app.services.yandex_metadata_iam import resolve_worker_invoke_iam_token

logger = logging.getLogger(__name__)


def _worker_dispatch_headers(secret: str) -> dict[str, str]:
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Internal-Worker-Secret": secret,
    }
    iam_token = resolve_worker_invoke_iam_token()
    if iam_token:
        headers["Authorization"] = f"Bearer {iam_token}"
    else:
        logger.warning(
            "Worker dispatch without IAM Bearer token "
            "(metadata unavailable and YANDEX_IAM_TOKEN empty); expect 403 on Yandex"
        )
    return headers


def schedule_case_files_processing(file_ids: List[str], case_id: str) -> None:
    """Не блокирует HTTP-ответ загрузки — fire-and-forget локальная обработка."""
    if not file_ids:
        return
    if config.file_processing_via_worker():
        asyncio.create_task(_dispatch_with_fallback(file_ids, case_id))
        return

    async def _bg() -> None:
        await _run_local(file_ids, case_id)

    asyncio.create_task(_bg())


async def dispatch_files_to_worker(file_ids: List[str], case_id: str) -> bool:
    """POST на worker; True если worker принял задачу (202)."""
    base = config.WORKER_BASE_URL
    secret = config.INTERNAL_WORKER_SECRET
    if not base or not secret:
        logger.error("WORKER_BASE_URL or INTERNAL_WORKER_SECRET is not set")
        return False

    url = f"{base}/internal/process-files"
    headers = _worker_dispatch_headers(secret)
    payload = {"file_ids": file_ids, "case_id": case_id}
    timeout = config.WORKER_DISPATCH_TIMEOUT_SEC

    def _post() -> bool:
        import requests

        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code not in (200, 202):
            logger.error(
                "Worker rejected dispatch: status=%s body=%s",
                resp.status_code,
                (resp.text or "")[:500],
            )
            return False
        return True

    try:
        return await asyncio.to_thread(_post)
    except Exception as exc:
        logger.error(
            "Failed to dispatch files to worker (case=%s): %s",
            case_id,
            exc,
            exc_info=True,
        )
        return False


async def _dispatch_with_fallback(file_ids: List[str], case_id: str) -> None:
    ok = await dispatch_files_to_worker(file_ids, case_id)
    if not ok:
        logger.warning(
            "Worker dispatch failed for case %s — falling back to local processing",
            case_id,
        )
        await _run_local(file_ids, case_id)


async def _run_local(file_ids: List[str], case_id: str) -> None:
    from app.services.file_processor_bg import process_files_background

    try:
        await asyncio.to_thread(process_files_background, file_ids, case_id)
    except Exception as exc:
        logger.error(
            "Background processing error for case %s: %s",
            case_id,
            exc,
            exc_info=True,
        )
