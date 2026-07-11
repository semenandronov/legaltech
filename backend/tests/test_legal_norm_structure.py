"""Тесты AST нарезки по пунктам и усиленных cross-ref."""
from __future__ import annotations

from app.services.legal_norm_cross_ref import (
    is_clause_level_norm_key,
    make_norm_node_key,
    parse_article_from_norm_key,
    parse_cross_references_from_text,
)
from app.services.legal_norm_structure import (
    expand_article_to_clause_pieces,
    extract_chapters_from_parent_path,
    make_chapter_node_key,
    make_law_node_key,
    normalize_article_text_for_clause_split,
    split_article_into_clauses,
)


ARTICLE_61_SNIPPET = """
Статья 61. Обжалование определений по обособленным спорам
1. Определения арбитражного суда по обособленным спорам могут быть обжалованы.
2. В порядке, установленном пунктом 2 статьи 61.3 настоящего Федерального закона, применяются нормы.
3. См. также пункте 2 настоящей статьи и ст. 61.1 настоящего Федерального закона.
"""


def test_split_article_into_clauses_basic():
    pieces = split_article_into_clauses(ARTICLE_61_SNIPPET)
    refs = [p.clause_ref for p in pieces]
    assert "" in refs
    assert "1" in refs
    assert "2" in refs
    assert "3" in refs


ARTICLE_33_GARANT_SNIPPET = (
    "Статья 33. Подсудность дел о банкротстве 1 . Дела о банкротстве юридических лиц и граждан, "
    "в том числе индивидуальных предпринимателей, рассматривает арбитражный суд по месту нахождения "
    "должника - юридического лица или по месту жительства гражданина. 2. Заявление о признании "
    "должника банкротом принимается арбитражным судом, если требования к должнику - юридическому лицу "
    "в совокупности составляют не менее чем два миллиона рублей, к должнику-гражданину - не менее чем "
    "пятьсот тысяч рублей и указанные требования не исполнены в течение трех месяцев с даты, когда они "
    "должны были быть исполнены, если иное не предусмотрено настоящим Федеральным законом.\n"
    "3. Дело о банкротстве не может быть передано на рассмотрение в третейский суд."
)


def test_normalize_garant_spaced_clause_dot():
    out = normalize_article_text_for_clause_split("банкротстве 1 . Дела")
    assert "1 ." not in out
    assert "1. Дела" in out or "1.\nДела" in out or "\n1. Дела" in out


def test_split_article_33_garant_inline_clauses():
    pieces = split_article_into_clauses(ARTICLE_33_GARANT_SNIPPET)
    refs = [p.clause_ref for p in pieces]
    assert refs.count("1") == 1
    assert refs.count("2") == 1
    assert refs.count("3") == 1
    by_ref = {p.clause_ref: p.text for p in pieces}
    assert "два миллиона" in by_ref["2"]
    assert "третейский суд" in by_ref["3"]


def test_expand_article_always_clause_level():
    pieces = expand_article_to_clause_pieces(ARTICLE_61_SNIPPET, max_chars=12000)
    numbered = [p for p in pieces if p.clause_ref]
    assert len(numbered) == 3


def test_structure_node_keys():
    assert make_law_node_key("fz-127") == "fz-127::law"
    assert make_chapter_node_key("fz-127", "глава-iii.1") == "fz-127::chapter::глава-iii.1"


def test_extract_chapters_from_parent_path():
    chapters = extract_chapters_from_parent_path(
        ["Глава III.1. Оспаривание сделок", "Статья 61. Обжалование"]
    )
    assert len(chapters) == 1
    assert "глава" in chapters[0].chapter_ref.lower()


def test_cross_ref_clause_article_compound():
    refs = parse_cross_references_from_text(
        "установленном пунктом 2 статьи 61.3 настоящего Федерального закона",
        default_instrument_id="fz-127",
    )
    assert any(r.article_number == "61.3" and r.clause_ref == "2" for r in refs)


def test_cross_ref_same_article_clause():
    refs = parse_cross_references_from_text(
        "см. пункте 2 настоящей статьи",
        default_instrument_id="fz-127",
        source_article_number="61",
    )
    assert any(r.article_number == "61" and r.clause_ref == "2" for r in refs)


def test_cross_ref_same_law_article():
    refs = parse_cross_references_from_text(
        "согласно ст. 61.1 настоящего Федерального закона",
        default_instrument_id="fz-127",
    )
    assert any(r.article_number == "61.1" for r in refs)


ARTICLE_53_CLAUSE_1 = (
    "1. Решение арбитражного суда о признании должника - юридического лица банкротом "
    "и об открытии конкурсного производства принимается в случаях установления признаков "
    "банкротства должника - юридического лица, предусмотренных статьей 3 настоящего "
    "Федерального закона, при отсутствии оснований для оставления заявления."
)


def test_cross_ref_instrumental_case_article_53_to_3():
    refs = parse_cross_references_from_text(
        ARTICLE_53_CLAUSE_1,
        default_instrument_id="fz-127",
        source_article_number="53",
        source_clause_ref="1",
    )
    hit = [r for r in refs if r.article_number == "3"]
    assert hit, f"expected ref to art. 3, got {refs}"
    assert hit[0].edge_type == "FORWARD_TO"
    assert hit[0].target_instrument_id == "fz-127"


def test_parse_article_from_norm_key():
    assert parse_article_from_norm_key("fz-127::art::3") == ("fz-127", "3")
    assert parse_article_from_norm_key("fz-127::art::61.3") == ("fz-127", "61.3")
    assert parse_article_from_norm_key("fz-127::art::61::clause::2") is None
    assert is_clause_level_norm_key(make_norm_node_key("fz-127", "61", clause_ref="2"))
    assert not is_clause_level_norm_key(make_norm_node_key("fz-127", "61"))
