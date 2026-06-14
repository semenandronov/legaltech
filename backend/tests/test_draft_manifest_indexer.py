"""Индексация шаблона по placeholders из manifest."""
import pytest

from app.services.draft_template_indexer import (
    build_specs_from_manifest_placeholders,
    scan_placeholder_occurrences,
)


def test_build_specs_from_manifest_placeholders():
    html = (
        "<p>Кредитор <span>[наименование кредитора]</span></p>"
        "<p>Снова [наименование кредитора]</p>"
        "<p>ИНН [ИНН кредитора]</p>"
    )
    occs = scan_placeholder_occurrences(html)
    placeholders = [
        {
            "marker": "[наименование кредитора]",
            "fill_question": "Какое полное наименование кредитора?",
            "entity_role": "creditor",
        },
        {
            "marker": "[ИНН кредитора]",
            "fill_question": "Какой ИНН кредитора?",
            "entity_role": "creditor",
        },
    ]
    specs = build_specs_from_manifest_placeholders(
        html,
        occs,
        placeholders=placeholders,
        template_title="Тест",
    )
    assert len(specs) == 3
    names = [s.fill_question for s in specs if s.marker == "[наименование кредитора]"]
    assert len(names) == 2
    assert names[0] == names[1] == "Какое полное наименование кредитора?"
    keys = {s.question_key for s in specs if s.marker == "[наименование кредитора]"}
    assert len(keys) == 1


def test_build_specs_raises_on_missing_manifest_question():
    html = "<p>[неизвестное поле]</p>"
    occs = scan_placeholder_occurrences(html)
    with pytest.raises(ValueError, match="manifest"):
        build_specs_from_manifest_placeholders(
            html,
            occs,
            placeholders=[],
            template_title="Тест",
        )
