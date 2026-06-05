"""
LLM streaming helpers — single responsibility: collect tokens from LangChain stream.

UI emission belongs in the graph/SSE layer (LangGraph custom channel), not in RAGService.

Contract:
- Providers may emit true incremental tokens OR cumulative text-so-far; normalize here once.
- Downstream (SSE) appends pieces blindly; canonical answer is replaced via content_sync after post-process.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Iterator, List, Optional

StreamWriter = Callable[[Dict[str, Any]], None]


def incremental_stream_piece(accumulated: str, raw_piece: str) -> str:
    """
    Convert one provider chunk into an incremental suffix (never cumulative repeat).

    Handles:
    - incremental tokens (``Hel``, ``lo``)
    - cumulative snapshots (``Hel``, ``Hello``, ``Hello world``)
    - exact duplicates (empty suffix)
    """
    piece = raw_piece if isinstance(raw_piece, str) else str(raw_piece or "")
    if not piece:
        return ""
    if not accumulated:
        return piece
    if piece == accumulated:
        return ""
    if piece.startswith(accumulated):
        tail = piece[len(accumulated) :]
        return tail if tail else ""
    if accumulated.endswith(piece):
        return ""
    return piece


def iter_llm_text_chunks(llm: Any, messages: List[Any]) -> Iterator[str]:
    """Yield incremental text pieces from llm.stream (normalized, never cumulative)."""
    accumulated = ""
    for chunk in llm.stream(messages):
        if not hasattr(chunk, "content") or not chunk.content:
            continue
        raw = chunk.content
        piece = raw if isinstance(raw, str) else str(raw)
        incremental = incremental_stream_piece(accumulated, piece)
        if not incremental:
            continue
        accumulated += incremental
        yield incremental


def collect_llm_stream_text(
    llm: Any,
    messages: List[Any],
    *,
    metrics_out: Optional[Dict[str, Any]] = None,
) -> str:
    """Buffer-only streaming: no SSE / LangGraph side effects."""
    t0 = time.monotonic()
    ttft_ms: Optional[int] = None
    chunk_count = 0
    parts: List[str] = []
    for piece in iter_llm_text_chunks(llm, messages):
        chunk_count += 1
        if ttft_ms is None:
            ttft_ms = int((time.monotonic() - t0) * 1000)
        parts.append(piece)
    text = "".join(parts)
    if metrics_out is not None:
        wall_ms = int((time.monotonic() - t0) * 1000)
        metrics_out.update(
            {
                "stream": True,
                "ttft_ms": ttft_ms if ttft_ms is not None else wall_ms,
                "stream_wall_ms": wall_ms,
                "chunk_count": chunk_count,
                "output_chars": len(text),
                "output_chars_after_ttft": len(text) if ttft_ms is not None else 0,
            }
        )
    return text


def collect_llm_stream_text_with_writer(
    llm: Any,
    messages: List[Any],
    writer: StreamWriter,
    *,
    metrics_out: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Stream to LangGraph custom channel (incremental textDelta only) and return full text.

    Contract: writer receives only incremental pieces; consumers must not also subscribe
    to LangGraph stream_mode=messages for the same LLM call.
    """
    t0 = time.monotonic()
    ttft_ms: Optional[int] = None
    chunk_count = 0
    parts: List[str] = []
    for piece in iter_llm_text_chunks(llm, messages):
        chunk_count += 1
        if ttft_ms is None:
            ttft_ms = int((time.monotonic() - t0) * 1000)
        parts.append(piece)
        writer({"type": "text_delta", "textDelta": piece})
    text = "".join(parts)
    if metrics_out is not None:
        wall_ms = int((time.monotonic() - t0) * 1000)
        metrics_out.update(
            {
                "stream": True,
                "ttft_ms": ttft_ms if ttft_ms is not None else wall_ms,
                "stream_wall_ms": wall_ms,
                "chunk_count": chunk_count,
                "output_chars": len(text),
                "output_chars_after_ttft": len(text) if ttft_ms is not None else 0,
            }
        )
    return text
