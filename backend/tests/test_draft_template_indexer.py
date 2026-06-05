"""Тесты индексатора полей шаблона Draft."""
from app.services.draft_template_indexer import (
    inject_field_anchors,
    scan_placeholder_occurrences,
)
from app.services.draft_field_fill import apply_field_values


def test_scan_duplicate_markers_distinct_occurrences():
    html = (
        "<p>В суд [наименование суда]</p>"
        "<p>Кредитор: [наименование]</p>"
        "<p>ИНН [ИНН]</p>"
    )
    occs = scan_placeholder_occurrences(html)
    assert len(occs) == 3
    markers = [o.marker for o in occs]
    assert markers.count("[наименование]") == 1
    assert "[наименование суда]" in markers
    assert occs[0].occurrence_index == 0
    assert occs[1].occurrence_index == 0


def test_inject_and_apply_isolated_field_values():
    html = "<p>A [наименование]</p><p>B [наименование]</p>"
    occs = scan_placeholder_occurrences(html)
    from app.services.draft_template_schemas import TemplateFieldSpec

    specs = []
    for i, o in enumerate(occs):
        specs.append(
            TemplateFieldSpec(
                field_id=f"ph_{i:03d}",
                marker=o.marker,
                occurrence_index=o.occurrence_index,
                start_offset=o.start_offset,
                end_offset=o.end_offset,
                context_snippet="ctx",
                semantic_label=f"label{i}",
                what_to_find="x",
                retrieval_query="q",
            )
        )
    indexed = inject_field_anchors(html, specs)
    assert 'data-draft-field="ph_000"' in indexed
    assert 'data-draft-field="ph_001"' in indexed
    out, n = apply_field_values(indexed, {"ph_000": "Суд А", "ph_001": "ООО Б"})
    assert n == 2
    assert "Суд А" in out
    assert "ООО Б" in out
    assert "[наименование]" not in out
