"""LLM streaming helpers — incremental-only contract."""
from unittest.mock import MagicMock

from app.services.chat.llm_streaming import (
    collect_llm_stream_text,
    collect_llm_stream_text_with_writer,
    incremental_stream_piece,
    iter_llm_text_chunks,
)


def _fake_llm(chunks):
    llm = MagicMock()
    llm.stream.return_value = [MagicMock(content=c) for c in chunks]
    return llm


def test_incremental_stream_piece_tokens():
    assert incremental_stream_piece("", "Hel") == "Hel"
    assert incremental_stream_piece("Hel", "lo") == "lo"
    assert incremental_stream_piece("Hello", "Hello") == ""


def test_incremental_stream_piece_cumulative():
    assert incremental_stream_piece("", "Hel") == "Hel"
    assert incremental_stream_piece("Hel", "Hello") == "lo"
    assert incremental_stream_piece("Hello", "Hello world") == " world"


def test_iter_llm_text_chunks_incremental():
    llm = _fake_llm(["Hel", "lo"])
    assert list(iter_llm_text_chunks(llm, [])) == ["Hel", "lo"]


def test_iter_llm_text_chunks_cumulative():
    llm = _fake_llm(["Hel", "Hello", "Hello world"])
    assert list(iter_llm_text_chunks(llm, [])) == ["Hel", "lo", " world"]


def test_collect_llm_stream_text_joins_incremental():
    llm = _fake_llm(["a", "b", "c"])
    assert collect_llm_stream_text(llm, []) == "abc"


def test_collect_llm_stream_text_cumulative_provider():
    llm = _fake_llm(["При", "Привет"])
    assert collect_llm_stream_text(llm, []) == "Привет"


def test_collect_llm_stream_text_with_writer_emits_incremental():
    llm = _fake_llm(["x", "y"])
    emitted = []
    text = collect_llm_stream_text_with_writer(
        llm, [], lambda p: emitted.append(p.get("textDelta"))
    )
    assert text == "xy"
    assert emitted == ["x", "y"]
