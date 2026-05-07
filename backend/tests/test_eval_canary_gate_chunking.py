from scripts.eval_canary_gate import decide


def test_decide_rollback_on_chunk_quality_drop():
    report = {
        "pass_rate": 0.91,
        "false_negative_rate_entity": 0.01,
        "chunk_hit_rate_at_k": 0.55,
        "boundary_break_rate": 0.05,
        "citation_span_accuracy": 0.9,
        "clause_f1": 0.9,
        "clause_boundary_correct_rate": 0.9,
    }
    decision = decide(report)
    assert decision["decision"] == "rollback"
    assert decision["target_traffic_percent"] == 0


def test_decide_promote_to_100_with_strong_chunk_metrics():
    report = {
        "pass_rate": 0.94,
        "false_negative_rate_entity": 0.01,
        "chunk_hit_rate_at_k": 0.9,
        "boundary_break_rate": 0.05,
        "citation_span_accuracy": 0.88,
        "clause_f1": 0.9,
        "clause_boundary_correct_rate": 0.9,
    }
    decision = decide(report)
    assert decision["decision"] == "promote"
    assert decision["target_traffic_percent"] == 100
