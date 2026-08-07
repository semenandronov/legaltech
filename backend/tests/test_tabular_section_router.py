from app.services.tabular_document_context import TabularFileContextPackage
from app.services.file_document_outline import OutlineSectionEntry
from app.services.tabular_section_router import route_column_to_sections


def _pkg() -> TabularFileContextPackage:
    return TabularFileContextPackage(
        file_id="f1",
        outline=(
            OutlineSectionEntry("sr1", "ПРЕДМЕТ ДОГОВОРА", "1", 0, 100, "1. ПРЕДМЕТ ДОГОВОРА"),
            OutlineSectionEntry(
                "sr2",
                "АРЕНДНАЯ ПЛАТА И ПОРЯДОК РАСЧЕТОВ",
                "3",
                200,
                400,
                "3. АРЕНДНАЯ ПЛАТА И ПОРЯДОК РАСЧЕТОВ",
            ),
            OutlineSectionEntry(
                "sr3",
                "ОТВЕТСТВЕННОСТЬ СТОРОН",
                "7",
                5000,
                6000,
                "7. ОТВЕТСТВЕННОСТЬ СТОРОН",
            ),
            OutlineSectionEntry(
                "sr4",
                "РАСТОРЖЕНИЕ ДОГОВОРА",
                "9",
                7000,
                8000,
                "9. РАСТОРЖЕНИЕ ДОГОВОРА",
            ),
            OutlineSectionEntry(
                "sr5",
                "СРОК ДЕЙСТВИЯ ДОГОВОРА",
                "2",
                120,
                180,
                "2. СРОК ДЕЙСТВИЯ ДОГОВОРА",
            ),
        ),
        passport_blurb="summary",
        definition_section_roots=(),
        index_fingerprint="v2.2:5:abc",
    )


def test_route_exact_clause(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_section_router.tabular_section_router_enabled",
        lambda: True,
    )
    plan = route_column_to_sections(
        file_context=_pkg(),
        semantic_query="пункт 1",
        lexical_terms=("1",),
        exact_query="1",
        column_type="verbatim",
    )
    assert plan.route_method == "exact_clause"
    assert "sr1" in plan.section_root_ids


def test_route_rent_to_payment_section(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_section_router.tabular_section_router_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.tabular_section_router.tabular_section_router_min_confidence",
        lambda: 0.55,
    )
    plan = route_column_to_sections(
        file_context=_pkg(),
        semantic_query="Каков размер арендной платы?",
        lexical_terms=("арендн", "плат"),
        exact_query="",
        column_type="text",
        column_label="Арендная плата",
    )
    assert plan.route_method == "lexical_overlap"
    assert "sr2" in plan.section_root_ids
    assert plan.confidence >= 0.55


def test_route_penalty_to_liability(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_section_router.tabular_section_router_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.tabular_section_router.tabular_section_router_min_confidence",
        lambda: 0.55,
    )
    plan = route_column_to_sections(
        file_context=_pkg(),
        semantic_query="Какая неустойка за просрочку?",
        lexical_terms=("неустойк",),
        exact_query="",
        column_type="text",
        column_label="Неустойка",
    )
    assert "sr3" in plan.section_root_ids


def test_route_termination(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_section_router.tabular_section_router_enabled",
        lambda: True,
    )
    plan = route_column_to_sections(
        file_context=_pkg(),
        semantic_query="Условия расторжения договора",
        lexical_terms=("расторжен",),
        exact_query="",
        column_type="text",
        column_label="Расторжение",
    )
    assert "sr4" in plan.section_root_ids


def test_route_disabled_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_section_router.tabular_section_router_enabled",
        lambda: False,
    )
    plan = route_column_to_sections(
        file_context=_pkg(),
        semantic_query="termination",
        lexical_terms=("termination",),
        exact_query="",
        column_type="text",
    )
    assert plan.route_method == "disabled"
    assert plan.section_root_ids == ()


def test_empty_outline_full_file(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_section_router.tabular_section_router_enabled",
        lambda: True,
    )
    empty = TabularFileContextPackage(
        file_id="f1",
        outline=(),
        passport_blurb="",
        definition_section_roots=(),
        index_fingerprint="x",
    )
    plan = route_column_to_sections(
        file_context=empty,
        semantic_query="аренда",
        lexical_terms=(),
        exact_query="",
        column_type="text",
    )
    assert plan.route_method == "full_file"
    assert plan.section_root_ids == ()
