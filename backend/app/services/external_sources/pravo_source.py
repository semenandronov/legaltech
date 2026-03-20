"""Client for publication.pravo.gov.ru — Official Legal Publications API"""
from __future__ import annotations

import io
import logging
from typing import Any, Dict, List, Optional

import aiohttp

from .base_source import BaseSource, SourceResult

logger = logging.getLogger(__name__)

BASE_URL = "https://publication.pravo.gov.ru"
SEARCH_TIMEOUT = 20  # seconds
PDF_TIMEOUT = 30     # seconds
MAX_PDF_TEXT = 8000  # chars to extract from PDF


class PravoSource(BaseSource):
    """
    Source for the Official Legal Publications portal (publication.pravo.gov.ru).

    Free, no auth required.  Endpoints used:
      GET /api/Documents   — full-text + metadata search
      GET /api/Document    — single document metadata by eoNumber
      GET /File/GetFile/{eoNumber}?type=pdf  — download PDF for text extraction
    """

    def __init__(self) -> None:
        super().__init__(name="pravo", enabled=True)

    # ------------------------------------------------------------------
    # BaseSource interface
    # ------------------------------------------------------------------

    async def initialize(self) -> bool:
        self._initialized = True
        return True

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{BASE_URL}/api/PublicBlocks",
                    timeout=aiohttp.ClientTimeout(total=10),
                    ssl=False,
                ) as resp:
                    return resp.status == 200
        except Exception as exc:
            logger.warning("[PravoSource] health_check failed: %s", exc)
            return False

    async def search(
        self,
        query: str,
        max_results: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
    ) -> List[SourceResult]:
        """Search documents by free text (DocumentText parameter)."""
        params: Dict[str, Any] = {
            "DocumentText": query,
            "PageSize": min(max_results, 30),
            "Index": 1,
            "SortedBy": 0,           # sort by document date
            "SortDestination": 1,    # descending
        }
        if filters:
            if filters.get("block"):
                params["Block"] = filters["block"]
            if filters.get("document_date_from"):
                params["DocumentDateFrom"] = filters["document_date_from"]
            if filters.get("document_date_to"):
                params["DocumentDateTo"] = filters["document_date_to"]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{BASE_URL}/api/Documents",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=SEARCH_TIMEOUT),
                    ssl=False,
                ) as resp:
                    if resp.status != 200:
                        logger.error("[PravoSource] search HTTP %s", resp.status)
                        return []
                    data = await resp.json(content_type=None)
        except Exception as exc:
            logger.error("[PravoSource] search error: %s", exc)
            return []

        items = data.get("items") or []
        results: List[SourceResult] = []
        for item in items[:max_results]:
            eo = item.get("eoNumber", "")
            name = item.get("name") or item.get("complexName") or "Без названия"
            title = item.get("complexName") or name
            doc_date = (item.get("documentDate") or "")[:10]
            view_date = item.get("viewDate", "")
            url = f"{BASE_URL}/Document/View/{eo}" if eo else ""
            results.append(
                SourceResult(
                    content=f"{title}\nДата подписания: {doc_date}\nДата публикации: {view_date}",
                    title=name,
                    source_name="pravo",
                    url=url,
                    relevance_score=0.8,
                    metadata={
                        "eo_number": eo,
                        "doc_date": doc_date,
                        "view_date": view_date,
                        "complex_name": title,
                        "pages_count": item.get("pagesCount"),
                        "signatory_authority_id": item.get("signatoryAuthorityId"),
                        "document_type_id": item.get("documentTypeId"),
                    },
                )
            )
        logger.info("[PravoSource] search '%s' → %d results", query[:60], len(results))
        return results

    # ------------------------------------------------------------------
    # Extra helpers (called from tools)
    # ------------------------------------------------------------------

    async def get_document_metadata(self, eo_number: str) -> Optional[Dict[str, Any]]:
        """Fetch full metadata for a single document by eoNumber."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{BASE_URL}/api/Document",
                    params={"eoNumber": eo_number},
                    timeout=aiohttp.ClientTimeout(total=SEARCH_TIMEOUT),
                    ssl=False,
                ) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json(content_type=None)
        except Exception as exc:
            logger.error("[PravoSource] get_document_metadata error: %s", exc)
            return None

    async def get_document_text(self, eo_number: str, max_chars: int = MAX_PDF_TEXT) -> Optional[str]:
        """Download the PDF and extract plain text (uses pypdf)."""
        pdf_url = f"{BASE_URL}/File/GetFile/{eo_number}?type=pdf"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    pdf_url,
                    timeout=aiohttp.ClientTimeout(total=PDF_TIMEOUT),
                    ssl=False,
                ) as resp:
                    if resp.status != 200:
                        logger.warning("[PravoSource] PDF HTTP %s for %s", resp.status, eo_number)
                        return None
                    raw = await resp.read()
        except Exception as exc:
            logger.error("[PravoSource] PDF download error: %s", exc)
            return None

        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            parts: List[str] = []
            for page in reader.pages:
                text = page.extract_text() or ""
                parts.append(text)
                if sum(len(p) for p in parts) >= max_chars:
                    break
            full_text = "\n".join(parts)
            return full_text[:max_chars]
        except Exception as exc:
            logger.error("[PravoSource] PDF parse error: %s", exc)
            return None
