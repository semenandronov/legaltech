"""Integration tests for structured citation SSE streaming."""
from __future__ import annotations

from typing import Any, Iterator, List

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.services.chat.structured_citation_streaming import collect_structured_citation_stream
from app.services.chat.structured_citations_core import (
    ChunkRecord,
    StructuredCitationPrepareResult,
)
from app.services.rag_service import RAGService


class _FakeStreamingLLM:
    def __init__(self, pieces: List[str]) -> None:
        self._pieces = pieces

    def stream(self, messages: List[BaseMessage]) -> Iterator[Any]:
        for piece in self._pieces:
            yield type("Chunk", (), {"content": piece})()


def test_collect_structured_citation_stream_emits_text_and_citations():
    chunk_id = "abc123"
    chunk_map = {
        chunk_id: ChunkRecord(
            chunk_id=chunk_id,
            doc_id="doc1",
            file_name="doc.pdf",
            page=1,
            content="Текст фрагмента",
            char_start=0,
            char_end=10,
        )
    }
    prepared = StructuredCitationPrepareResult(
        chunk_map=chunk_map,
        chunk_ids_list=(chunk_id,),
        messages=(
            SystemMessage(content="sys"),
            HumanMessage(content="human"),
        ),
        num_chunks=1,
        context_chars=100,
    )
    llm = _FakeStreamingLLM(
        [
            "Ответ ",
            f"[CHUNK:{chunk_id}]",
            " завершён.",
        ]
    )
    events: List[dict] = []

    def writer(payload: dict) -> None:
        events.append(payload)

    answer, citations = collect_structured_citation_stream(
        llm,
        prepared,
        writer,
        enrich_citations=lambda dumped: [
            {**row, "citation_id": "c1", "quote": "Текст фрагмента"}
            for row in dumped
        ],
    )

    assert "[1]" in answer
    assert "Ответ" in answer
    assert len(citations) == 1
    text_deltas = [e for e in events if e.get("type") == "text_delta"]
    citation_events = [e for e in events if e.get("type") == "citations"]
    assert text_deltas
    assert citation_events
    assert citation_events[-1]["citations"][0]["citation_id"] == "c1"


def test_rag_stream_with_structured_citations_emits_live_deltas():
    """RAGService stream path must emit text_delta before returning."""
    chunk_id = "chunk_live_1"
    docs = [
        Document(
            page_content="Должники Шиошвили",
            metadata={
                "chunk_id": chunk_id,
                "file_id": "f1",
                "source_file": "doc.pdf",
                "page_start": 1,
                "char_start": 0,
                "char_end": 20,
            },
        )
    ]
    events: List[dict] = []

    def writer(payload: dict) -> None:
        events.append(payload)

    rag = RAGService.__new__(RAGService)
    llm = _FakeStreamingLLM(
        [
            "Должники — ",
            f"[CHUNK:{chunk_id}]",
            ".",
        ]
    )
    metrics: dict = {}
    awc = rag.stream_with_structured_citations(
        "кто должники?",
        docs,
        system_prompt="Ответь кратко.",
        llm=llm,
        writer=writer,
        enrich_citations=lambda dumped: [
            {**row, "citation_id": f"cit_{i}", "source_type": "document"}
            for i, row in enumerate(dumped)
        ],
        metrics_out=metrics,
    )

    assert (awc.answer or "").strip()
    assert "[1]" in awc.answer
    text_deltas = [e for e in events if e.get("type") == "text_delta"]
    assert text_deltas, "expected live text_delta events during structured citation stream"
    assert any(e.get("type") == "citations" for e in events)
    assert metrics.get("ttft_ms") is not None
    assert int(metrics.get("chunk_count") or 0) >= 1
    assert metrics.get("stream") is True
