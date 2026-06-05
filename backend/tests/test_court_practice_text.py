"""Unit tests for court practice text preparation."""
from datetime import date

from app.services.court_practice_text import (
    chunk_act_text,
    clean_act_text,
    extract_case_numbers,
    extract_metadata,
    focus_motivational_text,
    infer_court_tier,
)


def test_extract_case_numbers_normalizes_cyrillic_a():
    text = "по делу № A40-12345/2020 установлено"
    nums = extract_case_numbers(text)
    assert nums
    assert nums[0].startswith("А40")


def test_chunk_act_short_single_piece():
    body = "установил: " + ("факт " * 50)
    chunks = chunk_act_text(body, single_chunk_max_chars=10_000)
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert len(chunks[0].chunk_text) > 100


def test_chunk_act_long_splits():
    body = "установил:\n\n" + ("абзац судебного акта. " * 800)
    chunks = chunk_act_text(
        body,
        single_chunk_max_chars=500,
        split_chunk_chars=400,
        overlap_chars=50,
    )
    assert len(chunks) >= 2
    assert all(c.chunk_text for c in chunks)


def test_extract_metadata_from_columns():
    meta = extract_metadata(
        "Определение\nАрбитражный суд города Москвы\nдело № А40-1/2024\nустановил: спор",
        case_number="А40-1/2024",
        court_name="АС г. Москвы",
        judgment_date="2024-05-10",
        court_tier="first",
    )
    assert meta.case_number == "А40-1/2024"
    assert meta.court_name == "АС г. Москвы"
    assert meta.judgment_date == date(2024, 5, 10)
    assert meta.court_tier == "first"


def test_focus_motivational_prefers_middle():
    text = (
        "шапка документа\n"
        + "установил: мотивировочная часть с существенными обстоятельствами. " * 5
        + "определил: резолютивная часть"
    )
    focused = focus_motivational_text(text)
    assert "установил" in focused.lower()
    assert "определил" not in focused.lower() or focused.lower().index("установил") < focused.lower().find("определил")


def test_infer_court_tier_vs_rf():
    assert infer_court_tier("Верховный Суд Российской Федерации постановил") == "vs_rf"


def test_clean_act_text_collapses_blank_lines():
    assert clean_act_text("a\n\n\n\nb") == "a\n\nb"
