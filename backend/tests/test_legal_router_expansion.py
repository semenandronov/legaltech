"""Детерминированный legal_router: instrument routing без захардкоженных статей."""

from app.services.chat.legal_router import MAX_ROUTE_QUERIES, route_legal_corpus_query


def test_route_bankruptcy_relative_and_sale_instruments_only():
    q = (
        "Можно ли оспорить сделку: должник продал земельный участок брату "
        "за месяц до банкротства?"
    )
    route = route_legal_corpus_query(q)
    assert "fz-127" in route.instrument_ids
    assert "plenum-63" in route.instrument_ids
    assert route.queries[0] == q
    assert "статья 19" not in " ".join(route.queries).lower()


def test_route_preferential_adds_plenum_not_article_queries():
    q = "Предпочтительная сделка в банкротстве с одним кредитором — какие сроки?"
    route = route_legal_corpus_query(q)
    assert "fz-127" in route.instrument_ids
    assert "plenum-63" in route.instrument_ids
    assert all("61.3" not in x for x in route.queries)


def test_route_subsidiary_no_10_4_query():
    q = "Субсидиарная ответственность руководителя при банкротстве юрлица"
    route = route_legal_corpus_query(q)
    assert "fz-127" in route.instrument_ids
    joined = " ".join(route.queries).lower()
    assert "10.4" not in joined
    assert route.queries[0] == q


def test_route_unknown_no_expansion_queries_beyond_original():
    q = "Как оформить отпуск по ТК РФ?"
    route = route_legal_corpus_query(q)
    assert route.instrument_ids == ["unknown"]
    assert route.queries == [q]


def test_route_respects_max_queries():
    q = (
        "Статья 19 и статья 61.2 127-ФЗ: брат кредитора, предпочтительная сделка, "
        "субсидиарная ответственность, продажа недвижимости должником в банкротстве"
    )
    route = route_legal_corpus_query(q)
    assert len(route.queries) <= MAX_ROUTE_QUERIES


def test_route_relative_deal_without_bankruptcy_word():
    q = "Должник продал участок брату за копейки"
    route = route_legal_corpus_query(q)
    assert "fz-127" in route.instrument_ids
    assert route.queries[0] == q


def test_route_relative_alone_no_bankruptcy():
    q = "Права брата на наследство"
    route = route_legal_corpus_query(q)
    assert route.instrument_ids == ["unknown"]


def test_route_article_61_implies_bankruptcy_without_plenum():
    route = route_legal_corpus_query("о чем статья 61")
    assert "fz-127" in route.instrument_ids
    assert "plenum-63" not in route.instrument_ids


def test_resolve_legal_corpus_route_legal_research_flag():
    from app.services.chat.legal_router import resolve_legal_corpus_route

    route = resolve_legal_corpus_route("статья 19", legal_research=True)
    assert "fz-127" in route.instrument_ids
