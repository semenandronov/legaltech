"""Shared structured-citation context, mapping, and stream transform (case assistant)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.services.chat.chunk_file_passport import attach_passports_to_source_headers
from app.services.langchain_agents.schemas.citation_schema import EnhancedCitation

_CHUNK_REF_RE = re.compile(r"\[CHUNK:([^\]]+)\]")
_CHUNK_OPEN = "[CHUNK:"
_MAX_HOLD_CHARS = 256


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    doc_id: str
    file_name: str
    page: int
    content: str
    char_start: int
    char_end: int
    bbox: Optional[Dict[str, float]] = None
    bbox_regions: Optional[List[Dict[str, float]]] = None
    page_bbox: Optional[Dict[str, float]] = None


@dataclass(frozen=True)
class StructuredCitationPrepareResult:
    chunk_map: Dict[str, ChunkRecord]
    chunk_ids_list: Tuple[str, ...]
    messages: Tuple[BaseMessage, ...]
    num_chunks: int
    context_chars: int


def _resolve_chunk_id(metadata: Dict[str, Any], *, doc_index: int, content: str) -> str:
    chunk_id = metadata.get("chunk_id")
    if chunk_id:
        return str(chunk_id)
    from app.services.chunk_ids import generate_chunk_id

    doc_id = metadata.get("doc_id", metadata.get("source_id", f"doc_{doc_index}"))
    chunk_index = metadata.get("chunk_index", doc_index)
    char_start = metadata.get("char_start", 0)
    return generate_chunk_id(str(doc_id), chunk_index, char_start)


def _resolve_page(rag_service: Any, metadata: Dict[str, Any]) -> int:
    source_page = (
        rag_service._docling_page_no_1based(metadata)
        or (
            int(metadata.get("source_page"))
            if metadata.get("source_page") is not None
            else None
        )
        or 1
    )
    return int(source_page)


def build_structured_citation_context(
    *,
    query: str,
    documents: List[Document],
    rag_service: Any,
    system_prompt: Optional[str] = None,
    content_cap: int = 2000,
) -> StructuredCitationPrepareResult:
    """Prepare chunk map, LLM messages, and context size for structured citations."""
    chunk_map: Dict[str, ChunkRecord] = {}
    context_parts: List[str] = []
    _, passport_lines = attach_passports_to_source_headers(documents)

    for i, doc in enumerate(documents):
        content = doc.page_content or ""
        metadata = dict(doc.metadata or {})
        chunk_id = _resolve_chunk_id(metadata, doc_index=i, content=content)
        source_file = str(metadata.get("source_file") or f"doc_{i + 1}")
        source_page = _resolve_page(rag_service, metadata)
        doc_id = str(metadata.get("doc_id") or metadata.get("source_id") or f"doc_{i + 1}")
        char_start = int(metadata.get("char_start") or 0)
        char_end = int(metadata.get("char_end") or len(content))
        bbox_regions, page_bbox = rag_service._extract_bbox_regions(metadata)
        passport = passport_lines[i] if i < len(passport_lines) else ""

        chunk_map[chunk_id] = ChunkRecord(
            chunk_id=chunk_id,
            doc_id=doc_id,
            file_name=source_file,
            page=source_page,
            content=content,
            char_start=char_start,
            char_end=char_end,
            bbox=bbox_regions[0] if bbox_regions else None,
            bbox_regions=bbox_regions or None,
            page_bbox=page_bbox,
        )
        head = f"[CHUNK:{chunk_id}] {source_file}, стр. {source_page}"
        if passport:
            head = f"{head}\n{passport}"
        context_parts.append(f"{head}:\n{content[:content_cap]}")

    context = "\n\n".join(context_parts)
    chunk_ids_list = tuple(chunk_map.keys())
    example_a = chunk_ids_list[0] if chunk_ids_list else "abc123"
    example_b = chunk_ids_list[1] if len(chunk_ids_list) > 1 else "def456"

    prompt = f"""Ты юридический помощник. Ответь на вопрос, используя информацию из документов.

ВАЖНО - ФОРМАТ ССЫЛОК:
Каждый документ имеет уникальный ID в формате [CHUNK:xxx]. 
Ставь ссылки СРАЗУ после фактов, используя ТОЧНЫЙ ID из контекста.

ФОРМАТ ОТВЕТА:
1. Пиши СВЯЗНЫЙ, ПЛАВНЫЙ текст
2. Ссылку [CHUNK:xxx] ставь СРАЗУ после того смыслового фрагмента, который этим чанком подтверждается (одно предложение или несколько предложений одной мысли — тогда после последнего предложения мысли). Не откладывай все ссылки в конец абзаца.
3. Ссылку ставь БЕЗ переноса строки между фактом и [CHUNK:xxx]
4. Используй ТОЧНЫЕ chunk_id из контекста выше

✅ ПРАВИЛЬНО:
"Договор заключён на 5 лет[CHUNK:{example_a}]. Штраф составляет 0.1%[CHUNK:{example_b}]."

❌ НЕПРАВИЛЬНО:
"Договор заключён на 5 лет.
[1]"

ДОКУМЕНТЫ:
{context}

ВОПРОС: {query}

Дай СВЯЗНЫЙ ответ. Ссылки [CHUNK:xxx] должны быть ВНУТРИ предложений."""

    default_system = (
        "Ты эксперт-юрист. Отвечай связным текстом; каждый [CHUNK:xxx] сразу после "
        "соответствующего смыслового фрагмента (не в конце абзаца пачкой). "
        "Точные chunk_id из контекста."
    )
    sys_content = (system_prompt or "").strip() or default_system
    messages: Tuple[BaseMessage, ...] = (
        SystemMessage(content=sys_content),
        HumanMessage(content=prompt),
    )
    return StructuredCitationPrepareResult(
        chunk_map=chunk_map,
        chunk_ids_list=chunk_ids_list,
        messages=messages,
        num_chunks=len(chunk_map),
        context_chars=len(context),
    )


def match_chunk_record(chunk_ref: str, chunk_map: Dict[str, ChunkRecord]) -> Optional[ChunkRecord]:
    ref = (chunk_ref or "").strip()
    if not ref:
        return None
    if ref in chunk_map:
        return chunk_map[ref]
    for chunk_id, record in chunk_map.items():
        if ref == chunk_id or ref in chunk_id or chunk_id in ref:
            return record
    return None


def enhanced_citation_from_record(record: ChunkRecord) -> EnhancedCitation:
    content = record.content
    quote = content[:300].strip()
    if len(content) > 300:
        quote += "..."
    return EnhancedCitation(
        source_id=str(record.doc_id),
        file_name=record.file_name,
        page=record.page,
        quote=quote,
        char_start=record.char_start,
        char_end=record.char_end,
        context_before=content[:50] if record.char_start > 0 else "",
        context_after=content[-50:] if len(content) > 50 else "",
        chunk_id=record.chunk_id,
        bbox=record.bbox,
        bbox_regions=record.bbox_regions,
        page_bbox=record.page_bbox,
    )


def _hold_suffix_len(text: str) -> int:
    """Bytes/chars to keep buffered — may be an incomplete [CHUNK:...] marker."""
    last_open = text.rfind("[")
    if last_open < 0:
        return 0
    tail = text[last_open:]
    if "]" in tail:
        return 0
    if len(tail) > _MAX_HOLD_CHARS:
        return 0
    if tail.startswith(_CHUNK_OPEN) or _CHUNK_OPEN.startswith(tail) or tail == "[":
        return len(tail)
    return 0


def _replace_complete_chunk_refs(
    text: str,
    chunk_map: Dict[str, ChunkRecord],
    chunk_to_number: Dict[str, int],
    *,
    new_numbers: List[int],
) -> str:
    def _repl(match: re.Match[str]) -> str:
        chunk_ref = match.group(1)
        if chunk_ref not in chunk_to_number:
            num = len(chunk_to_number) + 1
            chunk_to_number[chunk_ref] = num
            new_numbers.append(num)
        num = chunk_to_number[chunk_ref]
        return f"[{num}]"

    return _CHUNK_REF_RE.sub(_repl, text)


@dataclass
class ChunkCitationStreamTransformer:
    """
    Transform raw LLM stream: hide [CHUNK:id] markers, emit user-facing [N] incrementally.

    Thread-safe for single-threaded stream consumption only.
    """

    chunk_map: Dict[str, ChunkRecord]
    _buffer: str = ""
    _chunk_to_number: Dict[str, int] = field(default_factory=dict)
    _raw_accumulated: str = ""

    @property
    def raw_accumulated(self) -> str:
        return self._raw_accumulated

    @property
    def chunk_to_number(self) -> Dict[str, int]:
        return dict(self._chunk_to_number)

    def feed(self, piece: str) -> Tuple[str, List[int]]:
        """
        Consume one incremental LLM token piece.

        Returns:
            (user_visible_text, list of newly assigned citation numbers in this feed)
        """
        if not piece:
            return "", []
        self._raw_accumulated += piece
        self._buffer += piece
        hold = _hold_suffix_len(self._buffer)
        emit_region = self._buffer[: len(self._buffer) - hold] if hold else self._buffer
        if not emit_region:
            return "", []

        new_numbers: List[int] = []
        user_text = _replace_complete_chunk_refs(
            emit_region,
            self.chunk_map,
            self._chunk_to_number,
            new_numbers=new_numbers,
        )
        self._buffer = self._buffer[len(emit_region) :]
        return user_text, new_numbers

    def flush(self) -> Tuple[str, List[int]]:
        """Emit any trailing buffer at end of stream (best-effort)."""
        if not self._buffer:
            return "", []
        new_numbers: List[int] = []
        user_text = _replace_complete_chunk_refs(
            self._buffer,
            self.chunk_map,
            self._chunk_to_number,
            new_numbers=new_numbers,
        )
        self._buffer = ""
        return user_text, new_numbers

    def new_citations_for_numbers(self, numbers: List[int]) -> List[EnhancedCitation]:
        """Build EnhancedCitation payloads for citation numbers first seen in this feed."""
        if not numbers:
            return []
        number_to_ref = {num: ref for ref, num in self._chunk_to_number.items()}
        out: List[EnhancedCitation] = []
        for num in numbers:
            chunk_ref = number_to_ref.get(num)
            if not chunk_ref:
                continue
            record = match_chunk_record(chunk_ref, self.chunk_map)
            if record is None:
                continue
            out.append(enhanced_citation_from_record(record))
        return out


def map_structured_answer_text(
    answer_text: str,
    chunk_map: Dict[str, ChunkRecord],
    *,
    num_chunks: int,
    chunk_ids_list: Tuple[str, ...],
) -> Tuple[str, List[EnhancedCitation]]:
    """Map a complete LLM answer: [CHUNK:...] -> [N] and build citation list."""
    chunk_refs = _CHUNK_REF_RE.findall(answer_text or "")
    unique_chunk_refs: List[str] = []
    seen: set[str] = set()
    for ref in chunk_refs:
        if ref not in seen:
            unique_chunk_refs.append(ref)
            seen.add(ref)

    chunk_to_number: Dict[str, int] = {}
    citations: List[EnhancedCitation] = []

    for idx, chunk_ref in enumerate(unique_chunk_refs, 1):
        record = match_chunk_record(chunk_ref, chunk_map)
        chunk_to_number[chunk_ref] = idx
        if record is not None:
            citations.append(enhanced_citation_from_record(record))

    def replace_chunk_ref(match: re.Match[str]) -> str:
        chunk_ref = match.group(1)
        num = chunk_to_number.get(chunk_ref, 1)
        return f"[{num}]"

    mapped = _CHUNK_REF_RE.sub(replace_chunk_ref, answer_text or "")

    if not citations and re.search(r"\[\d+\]", mapped):
        mapped, citations = _fallback_numeric_citations(
            mapped,
            chunk_map=chunk_map,
            num_chunks=num_chunks,
            chunk_ids_list=chunk_ids_list,
        )

    mapped = re.sub(r"([.!?])\s*\n\s*(\[\d+\])", r"\1\2", mapped)
    mapped = re.sub(r"\n\s*(\[\d+\])", r"\1", mapped)
    mapped = re.sub(r"\n{3,}", "\n\n", mapped)
    return mapped, citations


def _fallback_numeric_citations(
    answer_text: str,
    *,
    chunk_map: Dict[str, ChunkRecord],
    num_chunks: int,
    chunk_ids_list: Tuple[str, ...],
) -> Tuple[str, List[EnhancedCitation]]:
    text = re.sub(
        r"\[[\d,\s]+\]",
        lambda m: "".join(f"[{n}]" for n in re.findall(r"\d+", m.group(0))),
        answer_text,
    )
    text = re.sub(r"\[\s*(\d+)\s*\]", r"[\1]", text)
    text = re.sub(r"(\[\d+\])\1+", r"\1", text)

    citation_markers = re.findall(r"\[(\d+)\]", text)
    unique_markers = sorted({int(m) for m in citation_markers})
    citations: List[EnhancedCitation] = []
    for marker in unique_markers:
        if marker <= num_chunks and marker - 1 < len(chunk_ids_list):
            chunk_id = chunk_ids_list[marker - 1]
            record = chunk_map.get(chunk_id)
            if record is not None:
                citations.append(enhanced_citation_from_record(record))
    return text, citations


def iter_transformed_llm_stream(
    llm: Any,
    messages: List[BaseMessage],
    transformer: ChunkCitationStreamTransformer,
) -> Iterator[Tuple[str, List[EnhancedCitation]]]:
    """
    Yield (user_visible_text_piece, new_citations) for each normalized LLM stream chunk.
    """
    from app.services.chat.llm_streaming import iter_llm_text_chunks

    for piece in iter_llm_text_chunks(llm, list(messages)):
        user_text, new_numbers = transformer.feed(piece)
        new_citations = transformer.new_citations_for_numbers(new_numbers)
        if user_text or new_citations:
            yield user_text, new_citations

    tail_text, tail_numbers = transformer.flush()
    tail_citations = transformer.new_citations_for_numbers(tail_numbers)
    if tail_text or tail_citations:
        yield tail_text, tail_citations
