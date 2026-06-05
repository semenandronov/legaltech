from __future__ import annotations

from app.services.chat.court_practice_planner import build_court_practice_search_queries


def test_planner_includes_original_question():
    q = "когда привлекают к субсидиарной ответственности контролирующих лиц"
    out = build_court_practice_search_queries(q)
    assert out
    assert out[-1] == q or q in out


def test_planner_expands_subsidiary_markers():
    q = "субсидиарная ответственность контролирующее лицо"
    out = build_court_practice_search_queries(q)
    joined = " ".join(out).lower()
    assert "61.11" in joined or "61.10" in joined or "пункт 4" in joined


def test_planner_promotes_case_number_as_first_query():
    q = "дело А70-15411/2015 что решил суд"
    out = build_court_practice_search_queries(q)
    assert out[0] in ("А70-15411/2015", "А70-15411/2015".upper())

