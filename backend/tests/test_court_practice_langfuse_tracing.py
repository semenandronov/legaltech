from __future__ import annotations

from app.services.court_practice_store import CourtPracticeHit
from app.services.observability.court_practice_langfuse_tracing import summarize_hits


def test_summarize_hits_groups_cases():
    hits = [
        CourtPracticeHit(
            chunk_id="c1",
            document_id="d1",
            case_number="А40-1/2024",
            court_name="ВС РФ",
            court_tier="vs_rf",
            judgment_date=None,
            chunk_index=0,
            chunk_text="t1",
            score=0.9,
        ),
        CourtPracticeHit(
            chunk_id="c2",
            document_id="d1",
            case_number="А40-1/2024",
            court_name="ВС РФ",
            court_tier="vs_rf",
            judgment_date=None,
            chunk_index=1,
            chunk_text="t2",
            score=0.8,
        ),
        CourtPracticeHit(
            chunk_id="c3",
            document_id="d2",
            case_number="А40-2/2024",
            court_name=None,
            court_tier="cassation",
            judgment_date=None,
            chunk_index=0,
            chunk_text="t3",
            score=0.7,
        ),
    ]
    s = summarize_hits(hits)
    assert s["hits_count"] == 3
    assert s["unique_cases"] == 2
    assert "А40-1/2024" in s["case_numbers"]
