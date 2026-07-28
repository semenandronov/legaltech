from app.services.contract_cross_ref_resolve import (
    parse_contract_cross_references,
    resolve_ref_to_section_root_ids,
    ContractRefTarget,
)


def test_parse_section_ref():
    refs = parse_contract_cross_references("as set forth in Section 8.2 hereof")
    assert refs
    assert refs[0].anchor == "8.2"


def test_resolve_section_to_root():
    outline = [
        ("sr8", "8", "TERMINATION", "8. TERMINATION"),
    ]
    target = ContractRefTarget(kind="section", anchor="8.2", raw="Section 8.2")
    hits = resolve_ref_to_section_root_ids(target, outline)
    assert hits == ("sr8",)
