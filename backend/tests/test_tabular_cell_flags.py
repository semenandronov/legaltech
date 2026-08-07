"""Unit tests for multi-color cell flags and auto rules."""

import pytest

from app.services.tabular_cell_flags import (
    normalize_user_flag,
    parse_flag_rules,
    resolve_auto_user_flag,
)


def test_normalize_user_flag():
    assert normalize_user_flag("Red") == "red"
    assert normalize_user_flag("clear") is None
    assert normalize_user_flag(None) is None
    with pytest.raises(ValueError):
        normalize_user_flag("purple")


def test_parse_and_resolve_flag_rules():
    config = {
        "flag_rules": [
            {"match": {"operator": "is_yes"}, "flag": "red"},
            {"match": {"operator": "contains", "value": "риск"}, "flag": "orange"},
            {"match": {"operator": "is_no"}, "flag": "green"},
        ]
    }
    rules = parse_flag_rules(config)
    assert len(rules) == 3
    assert resolve_auto_user_flag(config, cell_value="Да") == "red"
    assert resolve_auto_user_flag(config, cell_value="высокий риск") == "orange"
    assert resolve_auto_user_flag(config, cell_value="Нет") == "green"
    assert resolve_auto_user_flag(config, cell_value="обычный текст") is None


def test_flag_rules_require_value():
    with pytest.raises(ValueError, match="value is required"):
        parse_flag_rules(
            {"flag_rules": [{"match": {"operator": "equals"}, "flag": "yellow"}]}
        )
