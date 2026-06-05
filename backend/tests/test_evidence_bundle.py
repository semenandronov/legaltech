from __future__ import annotations

from app.services.chat.evidence_bundle import build_evidence_bundle, evidence_citations


def test_build_evidence_bundle_extracts_case_numbers():
    citations = [
        {
            "source_type": "court_practice",
            "file_name": "КАД",
            "quote_anchor": "Дело А40-12345/2023",
            "quote": "…",
        },
        {
            "source_type": "legal_corpus",
            "file_name": "ГК РФ",
            "quote_anchor": "",
            "quote": "…",
        },
    ]
    ev = build_evidence_bundle(citations=citations, retrieval_metadata={"tool": "court_practice"})
    assert isinstance(ev, dict)
    assert ev["citations"] == citations
    assert "retrieval_metadata" in ev
    assert "case_numbers" in ev
    assert "А40-12345/2023" in ev["case_numbers"]


def test_evidence_citations_reads_canonical_shape():
    evidence = {"citations": [{"a": 1}, {"b": 2}]}
    assert evidence_citations(evidence) == [{"a": 1}, {"b": 2}]


def test_evidence_citations_reads_legacy_list():
    evidence = [{"a": 1}, {"b": 2}, "nope"]
    assert evidence_citations(evidence) == [{"a": 1}, {"b": 2}]

