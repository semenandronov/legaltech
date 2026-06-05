"""Decide rollout stage from eval report KPIs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute canary rollout decision from eval report")
    parser.add_argument("--report", required=True, help="Path to eval report JSON")
    return parser.parse_args()


def decide(report: dict) -> dict:
    pass_rate = float(report.get("pass_rate", 0.0) or 0.0)
    fnr_entity = float(report.get("false_negative_rate_entity", 1.0) or 1.0)
    chunk_hit_rate = float(report.get("chunk_hit_rate_at_k", 0.0) or 0.0)
    boundary_break_rate = float(report.get("boundary_break_rate", 1.0) or 1.0)
    citation_span_accuracy = float(report.get("citation_span_accuracy", 0.0) or 0.0)
    clause_f1 = float(report.get("clause_f1", 0.0) or 0.0)
    clause_boundary_correct_rate = float(report.get("clause_boundary_correct_rate", 0.0) or 0.0)
    if (
        pass_rate < 0.8
        or fnr_entity > 0.10
        or chunk_hit_rate < 0.6
        or boundary_break_rate > 0.2
        or clause_f1 < 0.6
        or clause_boundary_correct_rate < 0.6
    ):
        return {"decision": "rollback", "target_traffic_percent": 0}
    if (
        pass_rate >= 0.9
        and fnr_entity <= 0.02
        and chunk_hit_rate >= 0.85
        and boundary_break_rate <= 0.08
        and citation_span_accuracy >= 0.85
        and clause_f1 >= 0.85
        and clause_boundary_correct_rate >= 0.85
    ):
        return {"decision": "promote", "target_traffic_percent": 100}
    if (
        pass_rate >= 0.85
        and fnr_entity <= 0.05
        and chunk_hit_rate >= 0.75
        and boundary_break_rate <= 0.12
        and citation_span_accuracy >= 0.75
        and clause_f1 >= 0.75
        and clause_boundary_correct_rate >= 0.75
    ):
        return {"decision": "promote", "target_traffic_percent": 50}
    return {"decision": "canary", "target_traffic_percent": 10}


def main() -> None:
    args = parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    result = decide(report)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
