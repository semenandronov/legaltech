from app.services.observability.case_assistant_timeline import (
    finalize_case_assistant_timeline,
    get_case_assistant_timeline,
    record_timeline_phase,
    reset_case_assistant_timeline,
    start_case_assistant_timeline,
)


def test_timeline_collects_phases():
    token = start_case_assistant_timeline()
    try:
        record_timeline_phase("assistant.case.http.router.data_plane", 1200, {"data_plane": "rag"})
        record_timeline_phase("case_assistant.document_scope_router", 400, {"scope_mode": "single_doc"})
        payload = finalize_case_assistant_timeline(wall_total_ms=2500, case_id="c1", data_plane="rag")
        assert payload["wall_total_ms"] == 2500
        assert payload["recorded_ms"] == 1600
        assert len(payload["phases"]) == 2
        assert payload["phases"][0]["name"] == "assistant.case.http.router.data_plane"
    finally:
        reset_case_assistant_timeline(token)
        assert get_case_assistant_timeline() is None
