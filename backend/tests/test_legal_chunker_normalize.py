"""LegalChunkerV2 segment normalization (oversized nodes, table sharding)."""

from app.services.legal_chunker import (
    _PROFILES,
    _Segment,
    _expand_oversized_non_table_segment,
    _normalize_docling_segments,
    _shard_markdown_table_text,
)


def _regulations_profile():
    return _PROFILES["regulations"]


def test_shard_markdown_table_includes_separator():
    md = "| Col1 | Col2 |\n| --- | --- |\n| a | 1 |\n| b | 2 |\n"
    shards = _shard_markdown_table_text(md, rows_per_group=1)
    assert len(shards) == 2
    for s in shards:
        assert "| Col1 | Col2 |" in s
        assert "| --- | --- |" in s


def test_normalize_splits_oversized_plain_segment():
    profile = _regulations_profile()
    big = "Слово " * 3000 + "\n\n"
    segments = [
        _Segment(
            text=big,
            section_title="Статья 1",
            section_number="1",
            parent_path=["Глава I"],
            page_no=1,
            char_start=0,
            char_end=len(big),
            is_heading=False,
        )
    ]
    out = _normalize_docling_segments(segments, profile)
    assert len(out) > 1
    for s in out:
        assert "Статья 1" == s.section_title
        assert s.parent_path == ["Глава I"]


def test_expand_oversized_preserves_parent_path():
    profile = _regulations_profile()
    seg = _Segment(
        text=("п. " * 4000) + "\n\n",
        section_title="",
        section_number="",
        parent_path=["НК РФ", "Глава 21"],
        page_no=None,
        char_start=0,
        char_end=10,
        is_heading=False,
    )
    max_seg = max(2200, profile.macro_size)
    pieces = _expand_oversized_non_table_segment(seg, max_seg, profile.macro_overlap)
    assert len(pieces) >= 2
    assert all(p.parent_path == ["НК РФ", "Глава 21"] for p in pieces)


def test_table_shard_metadata_flags():
    profile = _regulations_profile()
    rows = ["| Услуга | Ставка |", "| --- | --- |"] + [f"| x{i} | {i}% |" for i in range(200)]
    md = "\n".join(rows) + "\n"
    seg = _Segment(
        text=md,
        section_title="Статья 164",
        section_number="164",
        parent_path=["НК РФ"],
        page_no=5,
        char_start=0,
        char_end=len(md),
        is_heading=False,
        is_table=True,
    )
    out = _normalize_docling_segments([seg], profile)
    assert len(out) >= 2
    assert all(x.is_table_fragment for x in out)
    assert all(x.table_shard_index is not None for x in out)
