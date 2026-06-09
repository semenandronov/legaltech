"""Tests for tabular column type contract (infer + strict normalize)."""
from types import SimpleNamespace

import pytest

from app.services.tabular_column_type_contract import (
    finalize_extraction_dict,
    infer_column_type_heuristic,
    strict_normalize_cell_value,
    validate_column_config,
    validate_column_type,
)
from app.services.tabular_extraction_schemas import (
    extraction_schema_for_column,
    typed_extraction_to_cell_model,
)


def test_infer_date_from_signing_question():
    inferred = infer_column_type_heuristic("Дата подписания", "Какая дата подписания договора?")
    assert inferred.column_type == "date"
    assert inferred.confidence >= 0.7


def test_infer_verbatim_only_when_explicit():
    inferred = infer_column_type_heuristic("Цитата", "Выпиши дословно пункт о неустойке")
    assert inferred.column_type == "verbatim"


def test_infer_text_default_for_summary():
    inferred = infer_column_type_heuristic("Краткое содержание", "Опиши суть документа в 2 предложениях")
    assert inferred.column_type == "text"


def test_parse_and_normalize_date_skips_na():
    from app.services.date_validator import parse_and_normalize_date
    import pytest

    with pytest.raises(ValueError, match="N/A"):
        parse_and_normalize_date("N/A")


def test_strict_normalize_date_na_without_warning_path():
    cell, norm, rejection = strict_normalize_cell_value("N/A", "date")
    assert cell == "N/A"
    assert norm == "N/A"
    assert rejection is not None


def test_strict_normalize_date_russian_format():
    cell, norm, rejection = strict_normalize_cell_value("20.09.2023", "date")
    assert cell == "2023-09-20"
    assert norm == "2023-09-20"
    assert rejection is None


def test_strict_normalize_date_extracts_from_sentence():
    cell, norm, reason = strict_normalize_cell_value(
        "Договор подписан 20 сентября 2023 г.",
        "date",
    )
    assert cell == "2023-09-20"
    assert norm == "2023-09-20"
    assert reason is None
    cell, norm, rejection = strict_normalize_cell_value("неизвестно", "date")
    assert cell == "N/A"
    assert norm == "N/A"
    assert rejection is not None


def test_strict_normalize_yes_no_unknown_becomes_na():
    cell, norm, rejection = strict_normalize_cell_value("возможно", "yes_no")
    assert cell == "N/A"
    assert rejection is not None


def test_strict_normalize_yes_no_russian_canon():
    cell, norm, rejection = strict_normalize_cell_value("да", "yes_no")
    assert cell == "Да"
    assert norm == "да"
    assert rejection is None

    cell2, norm2, _ = strict_normalize_cell_value("нет", "yes_no")
    assert cell2 == "Нет"
    assert norm2 == "нет"


def test_strict_normalize_yes_no_legacy_english():
    cell, norm, rejection = strict_normalize_cell_value("Yes", "yes_no")
    assert cell == "Да"
    assert norm == "да"
    assert rejection is None

    cell2, norm2, _ = strict_normalize_cell_value("No", "yes_no")
    assert cell2 == "Нет"
    assert norm2 == "нет"


def test_strict_normalize_tag_must_match_options():
    cfg = {"options": [{"label": "Email", "color": "#000"}]}
    cell, norm, rejection = strict_normalize_cell_value("email", "tag", column_config=cfg)
    assert cell == "Email"
    assert rejection is None

    cell2, _, rejection2 = strict_normalize_cell_value("Invoice", "tag", column_config=cfg)
    assert cell2 == "N/A"
    assert rejection2 is not None


def test_validate_column_config_tag_requires_options():
    with pytest.raises(ValueError):
        validate_column_config("tag", {"options": []})


def test_validate_column_type_rejects_unknown():
    with pytest.raises(ValueError):
        validate_column_type("unknown_type")


def test_finalize_extraction_dict_maps_answer_alias():
    out = finalize_extraction_dict(
        {"answer": "15.03.2024", "reasoning": "from contract"},
        column_type="date",
    )
    assert out["cell_value"] == "2024-03-15"
    assert out["column_type"] == "date"


def test_extraction_schema_factory_date():
    col = SimpleNamespace(column_type="date", column_config=None)
    schema = extraction_schema_for_column(col)
    assert schema.__name__ == "DateCellExtraction"


def test_typed_extraction_to_cell_model_enforces_date():
    col = SimpleNamespace(column_type="date", column_config=None, prompt="date?")
    model = typed_extraction_to_cell_model(
        {"cell_value": "01.02.2020", "reasoning": "found"},
        column=col,
    )
    assert model.cell_value == "2020-02-01"
    assert model.column_type == "date"
