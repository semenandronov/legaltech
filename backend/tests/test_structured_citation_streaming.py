"""Integration tests for structured citation SSE streaming."""
from __future__ import annotations

from typing import Any, Iterator, List

from langchain_core.messages import BaseMessage

from app.services.chat.structured_citation_streaming import collect_structured_citation_stream
from app.services.chat.structured_citations_core import (
    ChunkRecord,
    StructuredCitationPrepareResult,
)
from langchain_core.messages import HumanMessage, SystemMessage


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
