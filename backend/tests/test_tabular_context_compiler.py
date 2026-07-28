from app.services.tabular_context_status import classify_tabular_context_outcome, merge_context_meta


def test_classify_no_recall():
    outcome = classify_tabular_context_outcome(
        meta={"status": "no_recall_docs"},
        context_text="",
        recall_docs_count=0,
    )
    assert outcome == "no_recall_docs"


def test_merge_meta_adds_compiler_version():
    meta = merge_context_meta({}, outcome="ok", escalation_used=True)
    assert meta["context_compiler_version"] == "tabular_context_compiler_v1"
    assert meta["escalation_used"] is True
