"""Детерминированный legal_router: multi-query expansion для 127-ФЗ."""

from app.services.chat.legal_router import MAX_ROUTE_QUERIES, route_legal_corpus_query


def test_route_bankruptcy_relative_and_sale_adds_st19_and_61_2_queries():
    q = (
        "Можно ли оспорить сделку: должник продал земельный участок брату "
        "за месяц до банкротства?"
    )
    route = route_legal_corpus_query(q)
    assert "fz-127" in route.instrument_ids
    joined = " ".join(route.queries).lower()
    assert "статья 19" in joined and "заинтересован" in joined
    assert "61.2" in joined and "подозрительн" in joined
    assert "расширение запросов" in route.rationale


def test_route_preferential_adds_61_3():
    q = "Предпочтительная сделка в банкротстве с одним кредитором — какие сроки?"
    route = route_legal_corpus_query(q)
    assert any("61.3" in x for x in route.queries)
    assert "предпочтительн" in " ".join(route.queries).lower()


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


def test_route_subsidiary_adds_10_4():
    q = "Субсидиарная ответственность руководителя при банкротстве юрлица"
    route = route_legal_corpus_query(q)
    assert any("10.4" in x for x in route.queries)


def test_route_relative_deal_without_bankruptcy_word():
    """Комбинация родственник+сделка без слова 'банкротство' → банкротный контекст."""
    q = "Должник продал участок брату за копейки"
    route = route_legal_corpus_query(q)
    assert "fz-127" in route.instrument_ids
    joined = " ".join(route.queries).lower()
    assert "статья 19" in joined and "заинтересован" in joined
    assert "61.2" in joined and "подозрительн" in joined


def test_route_relative_alone_no_bankruptcy():
    """Только родственник без сделки — не считаем банкротным."""
    q = "Права брата на наследство"
    route = route_legal_corpus_query(q)
    assert route.instrument_ids == ["unknown"]


def test_route_article_61_implies_bankruptcy():
    route = route_legal_corpus_query("о чем статья 61")
    assert "fz-127" in route.instrument_ids


def test_resolve_legal_corpus_route_legal_research_flag():
    from app.services.chat.legal_router import resolve_legal_corpus_route

    route = resolve_legal_corpus_route("статья 19", legal_research=True)
    assert "fz-127" in route.instrument_ids
