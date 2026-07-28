"""Parent–child (small-to-big) production policy + geometry pool."""
from __future__ import annotations

from langchain_core.documents import Document

from app.services.legal_chunker import (
    LegalChunkerV2,
    _PROFILES,
    _Segment,
    _StructureHit,
    _assert_parent_child_invariant,
    _build_macro_chunks,
    _classify_ocr_block_heading,
    _looks_like_compact_section_title,
    _yandex_loader_documents_segmentation,
)
from app.services.file_char_basis import peel_char_basis
from app.services.tabular_cell_pipeline import PreparedCellContext, docs_for_cell_geometry


def test_classify_legal_keyword_is_hard():
    hit = _classify_ocr_block_heading("Статья 5. Предмет договора", layout="TEXT")
    assert isinstance(hit, _StructureHit)
    assert hit.is_hard is True
    assert hit.level == 5
    assert hit.section_number == "5"
    assert "Статья 5" in hit.title


def test_classify_layout_title_is_hard():
    hit = _classify_ocr_block_heading("1. ПРЕДМЕТ ДОГОВОРА", layout="TITLE")
    assert hit is not None
    assert hit.is_hard is True
    assert hit.section_number == "1"


def test_classify_nested_clause_is_soft_never_hard():
    hit = _classify_ocr_block_heading("1.1. Исполнитель обязуется выполнить работы", layout="TEXT")
    assert hit is not None
    assert hit.is_hard is False
    assert hit.strength == "soft"
    assert hit.section_number == "1.1"


def test_classify_compact_top_level_numbered_title_is_hard():
    hit = _classify_ocr_block_heading("2. ОБЯЗАННОСТИ СТОРОН", layout="TEXT")
    assert hit is not None
    assert hit.is_hard is True
    assert hit.section_number == "2"


def test_classify_long_numbered_prose_is_soft():
    prose = (
        "1. Подрядчик обязуется выполнить весь комплекс строительных работ "
        "по проекту в согласованные сторонами сроки и надлежащего качества."
    )
    hit = _classify_ocr_block_heading(prose, layout="TEXT")
    assert hit is not None
    assert hit.is_hard is False
    assert _looks_like_compact_section_title(prose) is False


def test_yandex_soft_clause_updates_breadcrumb_without_heading_flag():
    docs = [
        Document(
            page_content="ignored",
            metadata={
                "source_page": 0,
                "yandex_page_bbox": {"width": 100.0, "height": 200.0},
                "yandex_blocks": [
                    {
                        "text": "1. ПРЕДМЕТ ДОГОВОРА",
                        "layout_type": "TITLE",
                        "bbox": {"x0": 10, "y0": 10, "x1": 90, "y1": 30},
                    },
                    {
                        "text": "1.1. Подрядчик выполняет работы.",
                        "layout_type": "TEXT",
                        "bbox": {"x0": 10, "y0": 40, "x1": 90, "y1": 60},
                    },
                ],
            },
        )
    ]
    segments, full = _yandex_loader_documents_segmentation(docs)
    assert full
    assert len(segments) == 2
    assert segments[0].is_heading is True
    assert segments[0].section_title.startswith("1. ПРЕДМЕТ")
    # Soft nested clause: breadcrumb yes, macro boundary no.
    assert segments[1].is_heading is False
    assert segments[1].section_number == "1.1"
    assert any("ПРЕДМЕТ" in p for p in segments[1].parent_path)


def test_macro_flushes_on_hard_heading_only():
    profile = _PROFILES["contracts"]
    pieces = [
        ("Преамбула стороны.\n\n", "", False),
        ("1. ПРЕДМЕТ\n\n", "1. ПРЕДМЕТ", True),
        ("1.1. Подрядчик выполняет работы по проекту.\n\n", "1.1. Подрядчик", False),
        ("Дополнительный текст того же раздела.\n\n", "1. ПРЕДМЕТ", False),
    ]
    offset = 0
    fixed: list[_Segment] = []
    for text, title, hard in pieces:
        cs = offset
        ce = cs + len(text)
        offset = ce
        fixed.append(
            _Segment(
                text=text,
                section_title=title,
                section_number="",
                parent_path=[title] if title else [],
                page_no=1,
                char_start=cs,
                char_end=ce,
                is_heading=hard,
            )
        )
    macros = _build_macro_chunks(fixed, profile, {"doc_id": "doc-a"})
    # Preamble + one section parent (soft 1.1 must not create its own macro).
    assert len(macros) == 2
    assert any(m.section_title == "1. ПРЕДМЕТ" for m in macros)
    assert all("1.1" not in (m.section_title or "") for m in macros)


def test_dense_soft_clauses_share_one_section_root():
    """Size may split macros; hard section root must stay shared."""
    profile = _PROFILES["contracts"]
    # Force small macros so one hard section becomes multiple size windows.
    small = type(profile)(
        name="contracts",
        macro_size=200,
        macro_overlap=40,
        micro_size=profile.micro_size,
        micro_overlap=profile.micro_overlap,
    )
    offset = 0
    segs: list[_Segment] = []
    title = "1. ПРЕДМЕТ ДОГОВОРА"
    head = f"{title}\n\n"
    segs.append(
        _Segment(
            text=head,
            section_title=title,
            section_number="1",
            parent_path=[title],
            page_no=1,
            char_start=0,
            char_end=len(head),
            is_heading=True,
        )
    )
    offset = len(head)
    for i in range(1, 6):
        text = f"1.{i}. Условие номер {i} о выполнении работ сторонами достаточно длинное для окна.\n\n"
        cs = offset
        ce = cs + len(text)
        offset = ce
        segs.append(
            _Segment(
                text=text,
                section_title=f"1.{i}. Условие",
                section_number=f"1.{i}",
                parent_path=[title, f"1.{i}. Условие"],
                page_no=1,
                char_start=cs,
                char_end=ce,
                is_heading=False,
            )
        )
    macros = _build_macro_chunks(segs, small, {"doc_id": "dense"})
    assert len(macros) >= 2
    roots = {m.section_root_id for m in macros}
    assert len(roots) == 1
    assert all(m.section_title == title for m in macros)


def test_chunk_from_segments_parent_child_invariant():
    chunker = LegalChunkerV2()
    profile = _PROFILES["contracts"]
    text_a = "Стороны заключили договор.\n\n"
    text_b = "1. ПРЕДМЕТ ДОГОВОРА\n\n"
    text_c = "1.1. Подрядчик выполняет строительные работы по проекту.\n\n"
    segments = [
        _Segment(
            text=text_a,
            section_title="",
            section_number="",
            parent_path=[],
            page_no=1,
            char_start=0,
            char_end=len(text_a),
            is_heading=False,
        ),
        _Segment(
            text=text_b,
            section_title="1. ПРЕДМЕТ ДОГОВОРА",
            section_number="1",
            parent_path=["1. ПРЕДМЕТ ДОГОВОРА"],
            page_no=1,
            char_start=len(text_a),
            char_end=len(text_a) + len(text_b),
            is_heading=True,
        ),
        _Segment(
            text=text_c,
            section_title="1.1. Подрядчик выполняет строительные работы по проекту.",
            section_number="1.1",
            parent_path=[
                "1. ПРЕДМЕТ ДОГОВОРА",
                "1.1. Подрядчик выполняет строительные работы по проекту.",
            ],
            page_no=1,
            char_start=len(text_a) + len(text_b),
            char_end=len(text_a) + len(text_b) + len(text_c),
            is_heading=False,  # soft nested clause
        ),
    ]
    full = "".join(s.text for s in segments)
    docs = chunker.chunk_from_segments(
        segments=segments,
        full_text=full,
        preseg_strategy="ocr_markdown_recursive_legal",
        profile=profile,
        base_metadata={"doc_id": "file-1", "file_id": "file-1", "case_id": "c1"},
        filename="contract.pdf",
    )
    docs, basis, basis_name = peel_char_basis(docs)
    assert basis == full
    assert basis_name == "legal_chunker_full_text"
    macros = [d for d in docs if d.metadata.get("chunk_level") == "macro"]
    micros = [d for d in docs if d.metadata.get("chunk_level") == "micro"]
    assert macros
    assert micros
    assert all(d.metadata.get("chunking_contract_version") == "v2.2" for d in docs)
    assert all(d.metadata.get("char_basis") == "legal_chunker_full_text" for d in docs)
    macro_ids = {d.metadata["macro_id"] for d in macros}
    section_roots = {d.metadata["section_root_id"] for d in macros}
    assert all(d.metadata.get("section_root_id") for d in macros)
    for m in micros:
        assert m.metadata.get("parent_macro_id")
        assert m.metadata["parent_macro_id"] in macro_ids
        assert m.metadata["parent_macro_id"] == m.metadata["macro_id"]
        assert m.metadata.get("section_root_id") in section_roots
        cs = int(m.metadata["char_start"])
        ce = int(m.metadata["char_end"])
        assert basis[cs:ce] == m.page_content or m.page_content in basis[cs:ce]
    _assert_parent_child_invariant(docs, filename="contract.pdf")


def test_docs_for_cell_geometry_prefers_micro_recall_pool():
    macro = Document(
        page_content="full parent clause text with 1.1 inside",
        metadata={"chunk_level": "macro", "macro_id": "p1", "char_start": 0, "char_end": 200},
    )
    micro = Document(
        page_content="1.1. Подрядчик выполняет работы",
        metadata={
            "chunk_level": "micro",
            "parent_macro_id": "p1",
            "macro_id": "p1",
            "char_start": 40,
            "char_end": 80,
            "dl_meta": {
                "doc_items": [
                    {"prov": [{"bbox": {"l": 1, "t": 2, "r": 3, "b": 4}, "page_no": 1}]}
                ]
            },
        },
    )
    prepared = PreparedCellContext(
        file_chunks=[micro],
        context_text=macro.page_content,
        included_docs=[macro],
    )
    geo = docs_for_cell_geometry(prepared)
    assert len(geo) == 1
    assert geo[0].metadata["chunk_level"] == "micro"


def test_docs_for_cell_geometry_empty_when_only_macros():
    macro = Document(
        page_content="parent only",
        metadata={"chunk_level": "macro", "macro_id": "p1"},
    )
    prepared = PreparedCellContext(
        file_chunks=[macro],
        context_text=macro.page_content,
        included_docs=[macro],
    )
    assert docs_for_cell_geometry(prepared) == []
