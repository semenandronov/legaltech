"""Deterministic entity/fact extraction pipeline with coverage contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple
import re

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.services.rag_service import RAGService

_JUDGE_MARKER_RE = re.compile(
    r"(?:судья|судьи|председательствующ(?:ий|ая|его)|состав\s+суда|в\s+составе\s+суда)",
    re.IGNORECASE,
)
_FIO_RE = re.compile(
    r"\b[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.[А-ЯЁ]\."
)
_JUDGE_ROLE_LINE_RE = re.compile(
    r"(?:судья|председательствующ(?:ий|ая|его)|в\s+составе\s+суда)[^\n]{0,180}",
    re.IGNORECASE,
)
_ORG_RE = re.compile(r"\b(?:ООО|АО|ПАО|ИП)\s+\"?[А-ЯЁA-Z][^,\n\"]+\"?", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"\b\d[\d\s]{0,15}(?:[.,]\d{1,2})?\s*(?:руб(?:\.|лей|ля)?|₽)\b", re.IGNORECASE)
_DATE_RE = re.compile(r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b")
_INN_RE = re.compile(r"\bИНН[:\s]*\d{10,12}\b", re.IGNORECASE)
_OGRN_RE = re.compile(r"\bОГРН[:\s]*\d{13,15}\b", re.IGNORECASE)
_CASE_NUM_RE = re.compile(r"\b[АA]\d{1,3}-\d+/\d{2,4}\b")


@dataclass
class CoverageProof:
    status: str
    searched_docs_count: int
    retrieved_chunks_count: int
    scanned_chars: int
    retrieval_passes: int
    negative_answer_allowed: bool
    reason: str
    retrieval_k: int

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "coverage_status": self.status,
            "searched_docs_count": self.searched_docs_count,
            "retrieved_chunks_count": self.retrieved_chunks_count,
            "scanned_chars": self.scanned_chars,
            "retrieval_passes": self.retrieval_passes,
            "negative_answer_allowed": self.negative_answer_allowed,
            "coverage_reason": self.reason,
            "retrieval_k": self.retrieval_k,
        }


@dataclass
class EntityPipelineResult:
    kind: str
    answer: str
    citations: List[Dict[str, Any]]
    entities: List[str]
    confidence: str
    coverage: CoverageProof


class EntityFactPipeline:
    """Entity-first pipeline for high-recall extraction with explicit coverage proof."""

    def __init__(self, rag_service: RAGService, db: Session):
        self.rag_service = rag_service
        self.db = db

    def run_judge_lookup(
        self,
        *,
        case_id: str,
        question: str,
        attached_file_ids: Optional[Sequence[str]] = None,
    ) -> EntityPipelineResult:
        retrieval_schedule = (8, 18, 36)
        docs, scans = self._retrieve_progressively(
            case_id=case_id,
            question=question,
            retrieval_schedule=retrieval_schedule,
            attached_file_ids=attached_file_ids,
        )
        entities, citations = self._extract_judges(docs)

        scanned_chars = sum(max(0, len(d.page_content or "")) for d in docs)
        coverage = CoverageProof(
            status="covered" if scans >= 2 or len(docs) >= retrieval_schedule[0] else "partial",
            searched_docs_count=len({str((d.metadata or {}).get("file_id") or (d.metadata or {}).get("doc_id") or "") for d in docs}),
            retrieved_chunks_count=len(docs),
            scanned_chars=scanned_chars,
            retrieval_passes=scans,
            negative_answer_allowed=(
                len(docs) >= retrieval_schedule[0]
                and (scans >= 2 or len(docs) >= retrieval_schedule[1])
            ),
            reason="judge_entity_lookup",
            retrieval_k=retrieval_schedule[min(max(scans - 1, 0), len(retrieval_schedule) - 1)],
        )

        if entities:
            answer = "Судьи, указанные в материалах дела: " + "; ".join(entities) + "."
            return EntityPipelineResult(
                kind="entity_hit",
                answer=answer,
                citations=citations[:6],
                entities=entities,
                confidence="confirmed",
                coverage=coverage,
            )

        if not coverage.negative_answer_allowed:
            return EntityPipelineResult(
                kind="insufficient_coverage",
                answer=(
                    "Пока недостаточно охвата контекста для корректного отрицательного вывода. "
                    "Уточните документ или повторите запрос, чтобы выполнить расширенный поиск."
                ),
                citations=[],
                entities=[],
                confidence="insufficient_coverage",
                coverage=coverage,
            )

        return EntityPipelineResult(
            kind="entity_miss",
            answer=(
                "После расширенного поиска по материалам дела данные о составе судей не обнаружены. "
                "Если нужный акт есть в деле, укажите файл или период для точечного поиска."
            ),
            citations=[],
            entities=[],
            confidence="probable",
            coverage=coverage,
        )

    def run_entity_fact_lookup(
        self,
        *,
        case_id: str,
        question: str,
        attached_file_ids: Optional[Sequence[str]] = None,
        budget_profile: Optional[Dict[str, Any]] = None,
    ) -> EntityPipelineResult:
        q = (question or "").lower()
        if any(marker in q for marker in ("судья", "состав суда", "председательствующ")):
            return self.run_judge_lookup(
                case_id=case_id,
                question=question,
                attached_file_ids=attached_file_ids,
            )

        schedule = (budget_profile or {}).get("k_schedule") if isinstance(budget_profile, dict) else None
        retrieval_schedule = tuple(int(x) for x in schedule if int(x) > 0) if isinstance(schedule, list) and schedule else (6, 12, 24)
        docs, scans = self._retrieve_progressively(
            case_id=case_id,
            question=question,
            retrieval_schedule=retrieval_schedule,
            attached_file_ids=attached_file_ids,
        )
        extracted, citations = self._extract_generic_entities(question, docs)
        scanned_chars = sum(max(0, len(d.page_content or "")) for d in docs)
        coverage = CoverageProof(
            status="covered" if scans >= 2 or len(docs) >= retrieval_schedule[0] else "partial",
            searched_docs_count=len({str((d.metadata or {}).get("file_id") or (d.metadata or {}).get("doc_id") or "") for d in docs}),
            retrieved_chunks_count=len(docs),
            scanned_chars=scanned_chars,
            retrieval_passes=scans,
            negative_answer_allowed=(len(docs) >= retrieval_schedule[0] and scans >= 2),
            reason="generic_entity_fact_lookup",
            retrieval_k=retrieval_schedule[min(max(scans - 1, 0), len(retrieval_schedule) - 1)],
        )
        if extracted:
            return EntityPipelineResult(
                kind="entity_hit",
                answer="Найденные факты: " + "; ".join(extracted[:8]) + ".",
                citations=citations[:8],
                entities=extracted,
                confidence="confirmed",
                coverage=coverage,
            )
        if not coverage.negative_answer_allowed:
            return EntityPipelineResult(
                kind="insufficient_coverage",
                answer=(
                    "Пока недостаточно охвата контекста для надёжного ответа. "
                    "Уточните тип факта (организация, дата, сумма, реквизиты) или документ."
                ),
                citations=[],
                entities=[],
                confidence="insufficient_coverage",
                coverage=coverage,
            )
        return EntityPipelineResult(
            kind="entity_miss",
            answer="По материалам дела запрошенные факты не обнаружены после расширенного поиска.",
            citations=[],
            entities=[],
            confidence="probable",
            coverage=coverage,
        )

    def _retrieve_progressively(
        self,
        *,
        case_id: str,
        question: str,
        retrieval_schedule: Sequence[int],
        attached_file_ids: Optional[Sequence[str]] = None,
    ) -> Tuple[List[Document], int]:
        seen: set[tuple[str, int]] = set()
        collected: List[Document] = []
        passes = 0
        for k in retrieval_schedule:
            passes += 1
            docs = self.rag_service.retrieve_context(
                case_id=case_id,
                query=question,
                k=k,
                retrieval_strategy="hybrid",
                db=self.db,
                file_ids=list(attached_file_ids) if attached_file_ids else None,
            )
            for doc in docs:
                meta = doc.metadata or {}
                key = (
                    str(meta.get("file_id") or meta.get("doc_id") or meta.get("source_file") or ""),
                    int(meta.get("chunk_index") or 0),
                )
                if key in seen:
                    continue
                seen.add(key)
                collected.append(doc)
            if self._has_judge_marker(collected):
                break
        return collected, passes

    @staticmethod
    def _has_judge_marker(docs: Sequence[Document]) -> bool:
        for doc in docs:
            text = doc.page_content or ""
            if _JUDGE_MARKER_RE.search(text):
                return True
        return False

    def _extract_judges(self, docs: Sequence[Document]) -> Tuple[List[str], List[Dict[str, Any]]]:
        entity_order: List[str] = []
        entity_seen: set[str] = set()
        citations: List[Dict[str, Any]] = []
        for doc in docs:
            text = doc.page_content or ""
            if not text:
                continue
            if not _JUDGE_MARKER_RE.search(text):
                continue
            matches = _FIO_RE.findall(text)
            if not matches:
                role_lines = _JUDGE_ROLE_LINE_RE.findall(text)
                for line in role_lines:
                    matches.extend(_FIO_RE.findall(line))
            if not matches:
                continue
            meta = doc.metadata or {}
            source_id = str(meta.get("file_id") or meta.get("doc_id") or "unknown")
            file_name = meta.get("source_file") or "Документ"
            page = meta.get("source_page") or meta.get("page")
            for fio in matches:
                normalized = self._normalize_fio(fio)
                if not normalized or normalized in entity_seen:
                    continue
                entity_seen.add(normalized)
                entity_order.append(normalized)
                quote = self._extract_quote_for_entity(text, normalized)
                cs = meta.get("char_start")
                ce = meta.get("char_end")
                cid = meta.get("chunk_id")
                citations.append(
                    {
                        "source_id": source_id,
                        "file_name": file_name,
                        "page": page,
                        "quote": quote,
                        "quote_anchor": (quote or "")[:800] or None,
                        "char_start": cs,
                        "char_end": ce,
                        "chunk_id": str(cid) if cid else None,
                        "source_type": "document",
                    }
                )
        return entity_order, citations

    def _extract_generic_entities(
        self,
        question: str,
        docs: Sequence[Document],
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        q = (question or "").lower()
        patterns: List[Tuple[str, re.Pattern]] = []
        if any(k in q for k in ("организац", "компан", "истец", "ответчик")):
            patterns.append(("org", _ORG_RE))
        if any(k in q for k in ("сумм", "руб", "₽")):
            patterns.append(("amount", _AMOUNT_RE))
        if any(k in q for k in ("дата", "когда", "срок")):
            patterns.append(("date", _DATE_RE))
        if "инн" in q:
            patterns.append(("inn", _INN_RE))
        if "огрн" in q:
            patterns.append(("ogrn", _OGRN_RE))
        if "номер дела" in q or "дело" in q:
            patterns.append(("case_number", _CASE_NUM_RE))
        if not patterns:
            patterns = [("generic", _CASE_NUM_RE), ("generic", _DATE_RE), ("generic", _AMOUNT_RE)]

        values: List[str] = []
        seen: set[str] = set()
        citations: List[Dict[str, Any]] = []
        for doc in docs:
            text = doc.page_content or ""
            meta = doc.metadata or {}
            for _, pattern in patterns:
                for match in pattern.findall(text):
                    value = self._normalize_fio(match) if isinstance(match, str) else ""
                    if not value:
                        continue
                    key = value.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    values.append(value)
                    q = self._extract_quote_for_entity(text, value)
                    cs = meta.get("char_start")
                    ce = meta.get("char_end")
                    cid = meta.get("chunk_id")
                    citations.append(
                        {
                            "source_id": str(meta.get("file_id") or meta.get("doc_id") or "unknown"),
                            "file_name": meta.get("source_file") or "Документ",
                            "page": meta.get("source_page") or meta.get("page"),
                            "quote": q,
                            "quote_anchor": (q or "")[:800] or None,
                            "char_start": cs,
                            "char_end": ce,
                            "chunk_id": str(cid) if cid else None,
                            "source_type": "document",
                        }
                    )
                    if len(values) >= 12:
                        return values, citations
        return values, citations

    @staticmethod
    def _normalize_fio(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip())

    @staticmethod
    def _extract_quote_for_entity(text: str, entity: str) -> str:
        idx = text.find(entity)
        if idx < 0:
            return (text[:260] + "...") if len(text) > 260 else text
        start = max(0, idx - 90)
        end = min(len(text), idx + len(entity) + 110)
        quote = text[start:end].strip()
        return quote if len(quote) <= 320 else quote[:317] + "..."
