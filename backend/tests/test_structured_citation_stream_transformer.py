from __future__ import annotations

from app.services.chat.structured_citations_core import (
    ChunkCitationStreamTransformer,
    ChunkRecord,
    map_structured_answer_text,
)


def _record(chunk_id: str) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id="doc-1",
        file_name="doc.pdf",
        page=1,
        content=f"content for {chunk_id}",
        char_start=0,
        char_end=10,
    )


def test_transformer_single_piece_complete_ref():
    chunk_map = {"abc123": _record("abc123")}
    tr = ChunkCitationStreamTransformer(chunk_map=chunk_map)
    user_text, nums = tr.feed("Факт[CHUNK:abc123].")
    assert user_text == "Факт[1]."
    assert nums == [1]
    assert tr.raw_accumulated.endswith("[CHUNK:abc123].")


def test_transformer_split_across_pieces():
    chunk_map = {"abc123": _record("abc123"), "def456": _record("def456")}
    tr = ChunkCitationStreamTransformer(chunk_map=chunk_map)
    a, n1 = tr.feed("Текст[CHU")
    assert a == "Текст"
    assert n1 == []
    b, n2 = tr.feed("NK:abc123] и ещё[CHUNK:")
    assert b == "[1] и ещё"
    assert n2 == [1]
    c, n3 = tr.feed("def456] конец.")
    assert c == "[2] конец."
    assert n3 == [2]
    tail, n4 = tr.flush()
    assert tail == ""
    assert n4 == []


def test_transformer_never_leaks_chunk_marker_to_user():
    chunk_map = {"x": _record("x")}
    tr = ChunkCitationStreamTransformer(chunk_map=chunk_map)
    parts = []
    for piece in ("Д", "анные[CHUNK", ":x", "] ок"):
        user, _ = tr.feed(piece)
        parts.append(user)
    user, _ = tr.flush()
    parts.append(user)
    joined = "".join(parts)
    assert "CHUNK" not in joined
    assert "[1]" in joined


def test_map_structured_answer_text_matches_stream_numbering():
    chunk_map = {
        "abc": _record("abc"),
        "def": _record("def"),
    }
    raw = "A[CHUNK:abc] B[CHUNK:def]"
    mapped, citations = map_structured_answer_text(
        raw,
        chunk_map,
        num_chunks=2,
        chunk_ids_list=("abc", "def"),
    )
    assert mapped == "A[1] B[2]"
    assert len(citations) == 2
    assert citations[0].chunk_id == "abc"
