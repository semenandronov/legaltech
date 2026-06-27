"""Tests for editor edit pipeline (deterministic validation, compact context, edit scope)."""
from app.services.langchain_agents.graphs.editor_edit_pipeline import (
    build_generate_edits_document_section,
    check_edit_plan_completeness,
    editor_needs_case_context,
    format_edit_turn_response,
    instruction_is_dialogue_continuation,
    instruction_targets_broader_document,
    instruction_targets_multiple_locations,
    requires_broad_document_context,
    validate_structured_edits_deterministic,
)


def _node_id_in_document(node_id: str, html: str) -> bool:
    return f'id="{node_id}"' in html or f"id='{node_id}'" in html


def _extract_block_text(node_id: str, html: str):
    import re

    m = re.search(
        rf'<p[^>]*\sid=["\']{re.escape(node_id)}["\'][^>]*>([\s\S]*?)</p>',
        html,
        re.I,
    )
    if not m:
        return None
    return re.sub(r"<[^>]+>", "", m.group(1)).strip()


def test_editor_needs_case_context_skips_local_edit():
    assert editor_needs_case_context(
        "Поменяй сумму неустойки на 150 000",
        editor_mode_hint="edit",
    ) is False


def test_editor_needs_case_context_for_case_signal():
    assert editor_needs_case_context(
        "Возьми ИНН кредитора из договора в деле",
        editor_mode_hint="edit",
    ) is True


def test_editor_needs_case_context_with_attachments():
    assert editor_needs_case_context(
        "исправь",
        editor_mode_hint="edit",
        attached_file_ids=["f1"],
    ) is True


def test_validate_structured_edits_enriches_node_id():
    html = '<p id="block-a">Старая сумма 100</p>'
    result = validate_structured_edits_deterministic(
        [{"node_id": "block-a", "new_text": "Новая сумма 150"}],
        html,
        node_id_in_document=_node_id_in_document,
        extract_block_text_by_node_id=lambda _h, nid: _extract_block_text(nid, _h),
    )
    assert result.is_valid is True
    assert len(result.enriched_edits) == 1
    assert result.enriched_edits[0]["found_in_document"] is True
    assert "Старая" in (result.enriched_edits[0].get("original_text") or "")


def test_validate_structured_edits_fail_closed_on_incomplete_scope():
    html = '<p id="a">1</p><p id="b">2</p>'
    scope = {
        "target_count": 2,
        "targets": [
            {"location": "блок a", "change": "x", "node_id": "a"},
            {"location": "блок b", "change": "y", "node_id": "b"},
        ],
    }
    result = validate_structured_edits_deterministic(
        [{"node_id": "a", "new_text": "новый a"}],
        html,
        node_id_in_document=_node_id_in_document,
        extract_block_text_by_node_id=lambda _h, nid: _extract_block_text(nid, _h),
        edit_scope=scope,
        fail_closed_on_incomplete_scope=True,
    )
    assert result.is_valid is False
    assert result.enriched_edits == []
    assert any("План охватывает" in e for e in result.errors)


def test_check_edit_plan_completeness_multi_target():
    scope = {
        "target_count": 2,
        "targets": [
            {"location": "основания", "change": "сумма", "node_id": "b1"},
            {"location": "заключение", "change": "сумма", "node_id": "b2"},
        ],
    }
    incomplete = check_edit_plan_completeness(scope, [{"node_id": "b1", "new_text": "x"}])
    assert incomplete.is_complete is False
    assert incomplete.expected_targets == 2
    assert incomplete.actual_edits == 1

    complete = check_edit_plan_completeness(
        scope,
        [
            {"node_id": "b1", "new_text": "x"},
            {"node_id": "b2", "new_text": "y"},
        ],
    )
    assert complete.is_complete is True


def test_build_compact_context_for_large_document():
    blocks = []
    parts = []
    filler = " " + ("юридический текст " * 40)
    for i in range(30):
        nid = f"block-{i:03d}"
        text = f"Абзац {i} про неустойку и кредитора{filler}"
        blocks.append(
            {
                "node_id": nid,
                "type": "p",
                "text": text[:200],
            }
        )
        parts.append(f'<p id="{nid}">{text}</p>')
    html = "\n".join(parts)
    assert len(html) > 12000
    section = build_generate_edits_document_section(
        html,
        "измени неустойку для кредитора",
        outline=blocks,
    )
    assert "compact context" in section
    assert len(section) < len(html)


def test_broad_context_includes_more_blocks():
    blocks = []
    parts = []
    filler = " " + ("юридический текст " * 40)
    for i in range(30):
        nid = f"block-{i:03d}"
        text = f"Абзац {i} про неустойку и кредитора{filler}"
        blocks.append({"node_id": nid, "type": "p", "text": text[:200]})
        parts.append(f'<p id="{nid}">{text}</p>')
    html = "\n".join(parts)
    narrow = build_generate_edits_document_section(html, "да", outline=blocks, broad_context=False)
    broad = build_generate_edits_document_section(
        html,
        "да",
        outline=blocks,
        broad_context=True,
        extra_search_text="основания заключение сумма 4131000",
    )
    assert broad.count("<p id=") >= narrow.count("<p id=")


def test_format_edit_turn_response():
    msg = format_edit_turn_response(
        [{"found_in_document": True}, {"found_in_document": False}],
    )
    assert "2" in msg
    assert "Примите" in msg or "сопоставлены" in msg


def test_instruction_targets_broader_document():
    assert instruction_targets_broader_document("в просительной части пункт 4 замени") is True
    assert instruction_targets_broader_document("исправь опечатку") is False


def test_instruction_targets_multiple_locations():
    assert instruction_targets_multiple_locations("приведи все суммы в соответствие") is True
    assert instruction_targets_multiple_locations("исправь опечатку") is False


def test_instruction_is_dialogue_continuation():
    assert instruction_is_dialogue_continuation("да сделай так") is True
    assert instruction_is_dialogue_continuation("согласен") is True
    assert instruction_is_dialogue_continuation(
        "в просительной части пункт 4 замени сумму на 6 млн"
    ) is False


def test_requires_broad_document_context():
    assert requires_broad_document_context("пункт 4", has_dialogue_history=False) is True
    assert requires_broad_document_context(
        "да сделай так",
        has_dialogue_history=True,
    ) is True
    assert requires_broad_document_context(
        "исправь опечатку",
        has_dialogue_history=False,
    ) is False
