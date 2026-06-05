"""SSE text stream contract: incremental deltas + canonical content_sync."""
import json

from app.services.chat.sse_text_stream import (
    apply_sse_event_to_text,
    extract_content_sync,
    extract_text_delta_piece,
)
from app.services.langchain_agents.chat_graph_service import _finalize_generate_response_text


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def test_delta_appends():
    ev = _sse({"type": "text_delta", "textDelta": "Привет"})
    assert extract_text_delta_piece(ev) == "Привет"
    assert apply_sse_event_to_text("", ev) == "Привет"
    assert apply_sse_event_to_text("Привет", _sse({"textDelta": ", мир"})) == "Привет, мир"


def test_content_sync_replaces_streamed_garbage():
    streamed = "Представленные фрагментыленные фрагменты"
    canonical = "Представленные фрагменты — процессуальный документ."
    ev = _sse({"type": "content_sync", "content": canonical})
    assert extract_content_sync(ev) == canonical
    assert apply_sse_event_to_text(streamed, ev) == canonical


def test_finalize_always_sync_after_live_stream():
    streamed = "черновик с артефактом"
    canonical = "Чистый финальный ответ."
    full, events = _finalize_generate_response_text(
        resp=canonical,
        streamed_text=streamed,
        text_streamed_live=True,
        turn_emitter=None,
    )
    assert full == canonical
    assert len(events) == 1
    assert "content_sync" in events[0]
    assert canonical in events[0]


def test_finalize_sync_even_when_stream_matches():
    text = "Один и тот же ответ."
    full, events = _finalize_generate_response_text(
        resp=text,
        streamed_text=text,
        text_streamed_live=True,
        turn_emitter=None,
    )
    assert full == text
    assert len(events) == 1
    assert "content_sync" in events[0]


def test_finalize_single_shot_without_stream():
    text = "Ответ без стрима."
    full, events = _finalize_generate_response_text(
        resp=text,
        streamed_text="",
        text_streamed_live=False,
        turn_emitter=None,
    )
    assert full == text
    assert len(events) == 1
    assert "textDelta" in events[0] or "text-delta" in events[0]
