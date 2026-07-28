from app.services.tabular_document_context import TabularFileContextPackage
from app.services.file_document_outline import OutlineSectionEntry
from app.services.tabular_section_router import route_column_to_sections


def _pkg() -> TabularFileContextPackage:
    return TabularFileContextPackage(
        file_id="f1",
        outline=(
            OutlineSectionEntry("sr1", "SUBJECT", "1", 0, 100, "1. SUBJECT"),
            OutlineSectionEntry("sr2", "DEFINITIONS", "2", 200, 400, "2. DEFINITIONS"),
            OutlineSectionEntry("sr3", "TERMINATION", "8", 5000, 6000, "8. TERMINATION"),
        ),
        passport_blurb="summary",
        definition_section_roots=("sr2",),
        index_fingerprint="v2.2:3:abc",
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
