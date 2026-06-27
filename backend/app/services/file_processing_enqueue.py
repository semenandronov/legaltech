"""Постановка файлов в обработку: планировщик на дело, локально или на worker."""
from __future__ import annotations

import asyncio
import logging
from typing import List, Sequence

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


def schedule_case_files_processing(
    case_id: str,
    file_ids: Sequence[str],
) -> None:
    """
    Fire-and-forget ingest scheduling (non-blocking HTTP).

    Routes all uploads through ``file_ingest_scheduler`` so repeated uploads to the
    same case coalesce into one drain loop instead of spawning unbounded tasks.
    """
    ids = [str(fid) for fid in file_ids if fid]
    if not ids or not case_id:
        return

    async def _enqueue() -> None:
        from app.services.file_ingest_scheduler import enqueue_case_files

        await enqueue_case_files(ids, case_id)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_enqueue())
    else:
        loop.create_task(_enqueue())

    logger.info(
        "File ingest scheduled: case=%s files=%s",
        case_id,
        len(ids),
    )


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
