"""Client for publication.pravo.gov.ru — Official Legal Publications API"""
from __future__ import annotations

import io
import re
import logging
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from .base_source import BaseSource, SourceResult

logger = logging.getLogger(__name__)

# Use HTTP — the portal uses a GOST TLS certificate that standard
# Python/OpenSSL cannot negotiate, so HTTPS hangs at the TLS handshake.
BASE_URL = "http://publication.pravo.gov.ru"
SEARCH_TIMEOUT = 20  # seconds
PDF_TIMEOUT = 30     # seconds
MAX_PDF_TEXT = 8000  # chars to extract from PDF

# PageSize only accepts specific values
_VALID_PAGE_SIZES = (10, 30, 100, 200)

# Keyword → Block code mapping for topic-based search
_TOPIC_TO_BLOCK: Dict[str, str] = {
    "банкротство": "federal_authorities",
    "несостоятельность": "federal_authorities",
    "кредитор": "federal_authorities",
    "конкурсный": "federal_authorities",
    "арбитраж": "court",
    "суд": "court",
    "конституционный": "court",
    "президент": "president",
    "правительство": "government",
    "постановление правительства": "government",
    "федеральный закон": "federal_authorities",
    "кодекс": "federal_authorities",
    "приказ": "federal_authorities",
    "министерство": "federal_authorities",
    "федеральное собрание": "assembly",
    "государственная дума": "assembly",
    "совет федерации": "assembly",
}

# Regex to detect law/order numbers like "127-ФЗ", "44-ФЗ", "395-1", "3"
_LAW_NUMBER_RE = re.compile(
    r'\b(\d{1,4}(?:-[А-ЯЁA-Z]{1,4})?)\b',
    re.IGNORECASE,
)

# Common Russian code abbreviations → their base federal law number
# NOTE: publication.pravo.gov.ru only has documents from ~2011+;
# these codes were enacted earlier, so only amendments appear on the portal.
_CODE_ABBREV_TO_NUMBER: Dict[str, str] = {
    "АПК": "95-ФЗ",      # Арбитражный процессуальный кодекс, 24.07.2002
    "ГПК": "138-ФЗ",     # Гражданский процессуальный кодекс, 14.11.2002
    "УПК": "174-ФЗ",     # Уголовно-процессуальный кодекс, 18.12.2001
    "УК": "63-ФЗ",       # Уголовный кодекс, 13.06.1996
    "ТК": "197-ФЗ",      # Трудовой кодекс, 30.12.2001
    "КоАП": "195-ФЗ",    # Кодекс об административных правонарушениях, 30.12.2001
    "ЖК": "188-ФЗ",      # Жилищный кодекс, 29.12.2004
    "ЗК": "136-ФЗ",      # Земельный кодекс, 25.10.2001
    "СК": "223-ФЗ",      # Семейный кодекс, 29.12.1995
    "БК": "145-ФЗ",      # Бюджетный кодекс, 31.07.1998
    "НК": "146-ФЗ",      # Налоговый кодекс ч.1, 31.07.1998
    "ГК": "51-ФЗ",       # Гражданский кодекс ч.1, 30.11.1994
    "ЛК": "200-ФЗ",      # Лесной кодекс, 04.12.2006
    "ВК": "74-ФЗ",       # Водный кодекс, 03.06.2006
}

# Full names of codes for context in LLM prompts
_CODE_FULL_NAMES: Dict[str, str] = {
    "АПК": "Арбитражный процессуальный кодекс Российской Федерации",
    "ГПК": "Гражданский процессуальный кодекс Российской Федерации",
    "УПК": "Уголовно-процессуальный кодекс Российской Федерации",
    "УК": "Уголовный кодекс Российской Федерации",
    "ТК": "Трудовой кодекс Российской Федерации",
    "КоАП": "Кодекс Российской Федерации об административных правонарушениях",
    "ЖК": "Жилищный кодекс Российской Федерации",
    "ЗК": "Земельный кодекс Российской Федерации",
    "СК": "Семейный кодекс Российской Федерации",
    "БК": "Бюджетный кодекс Российской Федерации",
    "НК": "Налоговый кодекс Российской Федерации",
    "ГК": "Гражданский кодекс Российской Федерации",
    "ЛК": "Лесной кодекс Российской Федерации",
    "ВК": "Водный кодекс Российской Федерации",
}


def _pick_page_size(n: int) -> int:
    for ps in _VALID_PAGE_SIZES:
        if n <= ps:
            return ps
    return 30


def _extract_code_abbrev(query: str) -> Optional[str]:
    """Detect a code abbreviation (АПК, ГПК, ГК etc.) in query.
    Returns the canonical abbreviation (e.g. 'АПК') or None.
    """
    # Match whole-word abbreviations, longest first (КоАП before АП)
    for abbrev in sorted(_CODE_ABBREV_TO_NUMBER, key=len, reverse=True):
        if re.search(rf'\b{re.escape(abbrev)}\b', query, re.IGNORECASE):
            return abbrev
    return None


def _extract_law_number(query: str) -> Optional[str]:
    """Try to find an explicit law number like '127-ФЗ' or '44-ФЗ' in query."""
    # Specific pattern: digits + dash + Cyrillic suffix (e.g. 127-ФЗ, 44-ФЗ, 395-1)
    m = re.search(r'\b(\d{1,4}-[А-ЯЁA-Z0-9]{1,4})\b', query, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _guess_block(query: str) -> Optional[str]:
    """Map query keywords to a publication block code."""
    q_lower = query.lower()
    for kw, block in _TOPIC_TO_BLOCK.items():
        if kw in q_lower:
            return block
    return None


class PravoSource(BaseSource):
    """
    Source for the Official Legal Publications portal (publication.pravo.gov.ru).

    Free, no auth required.  Endpoints used:
      GET /api/Documents   — search by Number, Block, date range
      GET /api/Document    — single document metadata by eoNumber
      GET /File/GetFile/{eoNumber}?type=pdf  — download PDF for text extraction

    NOTE: DocumentText / Name / ComplexName parameters return empty results
    (likely not indexed or geo-restricted).  Reliable search strategies:
      1. Number search when a law number is detected in the query
      2. Block filter for topic-based browsing (recent documents)
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
        """
        Search strategy:
          1. If query contains a law number (e.g. '127-ФЗ') → Number search (exact)
          2. Otherwise → Block filter (inferred from keywords) + recent docs
        """
        page_size = _pick_page_size(max_results)

        params: Dict[str, Any] = {
            "PageSize": page_size,
            "Index": 1,
            "SortedBy": 0,        # sort by document date
            "SortDestination": 1, # descending
        }

        code_abbrev = _extract_code_abbrev(query)
        law_number = _extract_law_number(query)
        if code_abbrev and not law_number:
            # Code abbreviation detected (АПК, ГПК, ГК...) — resolve to law number
            law_number = _CODE_ABBREV_TO_NUMBER[code_abbrev]
            logger.info("[PravoSource] code abbrev %s → law number %s", code_abbrev, law_number)

        if law_number:
            # Exact number match
            params["Number"] = law_number
            params["NumberSearchType"] = 0
            search_desc = f"Number={law_number}"
        else:
            block = (_guess_block(query) if not filters else None) or (filters or {}).get("block")
            if block:
                params["Block"] = block
            search_desc = f"Block={block or 'all'}"

        if filters:
            if filters.get("document_date_from"):
                params["DocumentDateFrom"] = filters["document_date_from"]
            if filters.get("document_date_to"):
                params["DocumentDateTo"] = filters["document_date_to"]

        logger.info("[PravoSource] search query=%r strategy=%s", query[:60], search_desc)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{BASE_URL}/api/Documents",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=SEARCH_TIMEOUT),
                ) as resp:
                    if resp.status != 200:
                        logger.error("[PravoSource] search HTTP %s", resp.status)
                        return []
                    data = await resp.json(content_type=None)
        except Exception as exc:
            logger.error("[PravoSource] search error: %s", exc)
            return []

        items = data.get("items") or []
        total = data.get("itemsTotalCount", 0)

        # When searching by law number, prefer the base law over amendments.
        # Amendments are titled "О внесении изменений в..." — sort them after base laws.
        if law_number:
            def _is_amendment(item: Dict[str, Any]) -> bool:
                n = (item.get("name") or item.get("complexName") or "").lower()
                return "о внесении изменений" in n or "о признании утратившим" in n

            base = [i for i in items if not _is_amendment(i)]
            amendments = [i for i in items if _is_amendment(i)]
            items = base + amendments
            if base:
                logger.info(
                    "[PravoSource] search: %d base laws, %d amendments for Number=%s",
                    len(base), len(amendments), law_number,
                )

        # If a code abbreviation was used, prepend a note so the inner LLM has context
        code_note = ""
        if code_abbrev:
            full_name = _CODE_FULL_NAMES.get(code_abbrev, code_abbrev)
            code_note = (
                f"ПРИМЕЧАНИЕ: {full_name} ({code_abbrev} РФ, {law_number}) был принят до 2011 года "
                f"и не размещён в полном объёме на portal publication.pravo.gov.ru. "
                f"Ниже представлены последние поправки к этому кодексу с портала. "
                f"Для получения актуального текста конкретной статьи используй знания о российском законодательстве.\n\n"
            )

        results: List[SourceResult] = []
        for item in items[:max_results]:
            eo = item.get("eoNumber", "")
            name = item.get("name") or item.get("complexName") or "Без названия"
            title = item.get("complexName") or name
            doc_date = (item.get("documentDate") or "")[:10]
            view_date = item.get("viewDate", "")
            url = f"http://publication.pravo.gov.ru/Document/View/{eo}" if eo else ""
            results.append(
                SourceResult(
                    content=f"{code_note}{title}\nДата подписания: {doc_date}\nДата публикации: {view_date}",
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
                        "total_found": total,
                        "code_abbrev": code_abbrev,
                    },
                )
            )
        logger.info("[PravoSource] search → %d results (total %d)", len(results), total)
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
                ) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json(content_type=None)
        except Exception as exc:
            logger.error("[PravoSource] get_document_metadata error: %s", exc)
            return None

    async def get_document_text(self, eo_number: str, max_chars: int = MAX_PDF_TEXT) -> Optional[str]:
        """
        Download the PDF and extract plain text (uses pypdf).
        NOTE: Many documents on pravo.gov.ru are scanned PDFs — pypdf extracts empty text
        for those. In that case returns None; callers should fall back to metadata.
        """
        pdf_url = f"{BASE_URL}/file/pdf?eoNumber={eo_number}"
        logger.info("[PravoSource] get_document_text %s: downloading PDF from %s", eo_number, pdf_url)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    pdf_url,
                    timeout=aiohttp.ClientTimeout(total=PDF_TIMEOUT),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("[PravoSource] PDF HTTP %s for %s", resp.status, eo_number)
                        return None
                    raw = await resp.read()
                    logger.info("[PravoSource] PDF downloaded: %d bytes for %s", len(raw), eo_number)
        except Exception as exc:
            logger.error("[PravoSource] PDF download error for %s: %s", eo_number, exc)
            return None

        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            page_count = len(reader.pages)
            parts: List[str] = []
            for page in reader.pages:
                text = page.extract_text() or ""
                parts.append(text)
                if sum(len(p) for p in parts) >= max_chars:
                    break
            full_text = "\n".join(parts).strip()
            logger.info(
                "[PravoSource] PDF parsed: %d pages, %d chars text for %s",
                page_count, len(full_text), eo_number,
            )
            if not full_text:
                logger.warning(
                    "[PravoSource] ⚠️ PDF text empty for %s (%d pages) — likely a scanned document",
                    eo_number, page_count,
                )
                return None
            return full_text[:max_chars]
        except Exception as exc:
            logger.error("[PravoSource] PDF parse error for %s: %s", eo_number, exc)
            return None
