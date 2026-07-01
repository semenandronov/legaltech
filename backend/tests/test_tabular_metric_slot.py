from app.services.chat.tabular_metric_slot import resolve_sql_metric_dimension


def test_sum_stems():
    assert resolve_sql_metric_dimension("итого по обороту") == "sum"
    assert resolve_sql_metric_dimension("на какую сумму транзакций") == "sum"


def test_count_stems():
    assert resolve_sql_metric_dimension("сколько операций в мае") == "count"
    assert resolve_sql_metric_dimension("количество платежей") == "count"


def test_inherit_without_metric_cue():
    assert resolve_sql_metric_dimension("в мае 2026") == "inherit"
    assert resolve_sql_metric_dimension("") == "inherit"
