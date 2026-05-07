"""Offline evaluation runner with optional Langfuse score reporting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
import json
import logging
from pathlib import Path

from app.services.llm_factory import create_legal_llm
from app.services.observability.langfuse_service import create_trace_context, end_trace, record_score

logger = logging.getLogger(__name__)


@dataclass
class EvalCaseResult:
    case_id: str
    relevance: float
    completeness: float
    groundedness: float
    passed_gate: bool
    response_preview: str
    chunk_hit: float
    boundary_break: float
    citation_span_accuracy: float
    clause_precision: float
    clause_recall: float
    clause_f1: float
    clause_boundary_correct: bool


def _score_simple(reference: str, response: str) -> float:
    ref = (reference or "").strip().lower()
    out = (response or "").strip().lower()
    if not ref:
        return 0.0
    overlap = 0
    total = 0
    for token in ref.split():
        if len(token) < 4:
            continue
        total += 1
        if token in out:
            overlap += 1
    if total == 0:
        return 0.0
    return max(0.0, min(1.0, overlap / total))


def _clause_metrics(expected_ids: Any, retrieved_ids: Any) -> tuple[float, float, float, bool]:
    expected = {str(x).strip() for x in (expected_ids or []) if str(x).strip()}
    retrieved = {str(x).strip() for x in (retrieved_ids or []) if str(x).strip()}
    if not expected:
        return 0.0, 0.0, 0.0, False
    tp = len(expected & retrieved)
    precision = tp / len(retrieved) if retrieved else 0.0
    recall = tp / len(expected) if expected else 0.0
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    boundary_ok = recall >= 0.95
    return precision, recall, f1, boundary_ok


async def run_offline_eval(dataset_path: str, baseline_min: float = 0.65) -> Dict[str, Any]:
    dataset = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    if not isinstance(dataset, list):
        raise ValueError("Dataset must be a JSON array")

    llm = create_legal_llm(use_rate_limiting=False)
    results: List[EvalCaseResult] = []
    passed = 0
    entity_cases = 0
    entity_false_negative = 0
    token_cost_samples: List[float] = []
    chunk_hits: List[float] = []
    boundary_breaks: List[float] = []
    citation_span_accuracies: List[float] = []
    clause_precisions: List[float] = []
    clause_recalls: List[float] = []
    clause_f1s: List[float] = []
    clause_boundary_correct_cases = 0

    for idx, item in enumerate(dataset):
        question = str(item.get("question", "")).strip()
        reference = str(item.get("reference", "")).strip()
        case_id = str(item.get("id", f"eval-{idx+1}"))
        eval_type = str(item.get("eval_type", "")).strip().lower()
        if not question:
            continue

        trace_ctx = create_trace_context(
            name="offline_eval_case",
            trace_id=f"offline-eval-{case_id}",
            metadata={"dataset_case_id": case_id},
            input_payload={"question": question},
        )
        try:
            response = await llm.ainvoke(question)
            text = response.content if hasattr(response, "content") else str(response)
            relevance = _score_simple(reference, text)
            completeness = min(1.0, len(text) / max(200.0, len(reference) or 1.0))
            groundedness = relevance
            avg_score = (relevance + completeness + groundedness) / 3.0
            gate = avg_score >= baseline_min
            if eval_type == "entity":
                entity_cases += 1
                if reference and reference.lower() not in text.lower() and ("не найден" in text.lower() or "отсутств" in text.lower()):
                    entity_false_negative += 1
            token_cost_samples.append(float(item.get("token_cost", 0.0) or 0.0))
            chunk_hit = float(item.get("chunk_hit", 0.0) or 0.0)
            boundary_break = float(item.get("boundary_break", 0.0) or 0.0)
            citation_span_accuracy = float(item.get("citation_span_accuracy", 0.0) or 0.0)
            clause_precision, clause_recall, clause_f1, clause_boundary_correct = _clause_metrics(
                item.get("expected_clause_ids"),
                item.get("retrieved_clause_ids"),
            )
            chunk_hits.append(chunk_hit)
            boundary_breaks.append(boundary_break)
            citation_span_accuracies.append(citation_span_accuracy)
            clause_precisions.append(clause_precision)
            clause_recalls.append(clause_recall)
            clause_f1s.append(clause_f1)
            if clause_boundary_correct:
                clause_boundary_correct_cases += 1
            if gate:
                passed += 1

            result = EvalCaseResult(
                case_id=case_id,
                relevance=round(relevance, 4),
                completeness=round(completeness, 4),
                groundedness=round(groundedness, 4),
                passed_gate=gate,
                response_preview=text[:500],
                chunk_hit=round(chunk_hit, 4),
                boundary_break=round(boundary_break, 4),
                citation_span_accuracy=round(citation_span_accuracy, 4),
                clause_precision=round(clause_precision, 4),
                clause_recall=round(clause_recall, 4),
                clause_f1=round(clause_f1, 4),
                clause_boundary_correct=clause_boundary_correct,
            )
            results.append(result)

            record_score(trace_id=trace_ctx.trace_id, name="eval_relevance", value=result.relevance)
            record_score(trace_id=trace_ctx.trace_id, name="eval_completeness", value=result.completeness)
            record_score(trace_id=trace_ctx.trace_id, name="eval_groundedness", value=result.groundedness)
            record_score(trace_id=trace_ctx.trace_id, name="eval_chunk_hit", value=result.chunk_hit)
            record_score(trace_id=trace_ctx.trace_id, name="eval_boundary_break", value=result.boundary_break)
            record_score(trace_id=trace_ctx.trace_id, name="eval_citation_span_accuracy", value=result.citation_span_accuracy)
            record_score(trace_id=trace_ctx.trace_id, name="eval_clause_precision", value=result.clause_precision)
            record_score(trace_id=trace_ctx.trace_id, name="eval_clause_recall", value=result.clause_recall)
            record_score(trace_id=trace_ctx.trace_id, name="eval_clause_f1", value=result.clause_f1)
            end_trace(
                trace_ctx,
                status="success",
                output_payload={
                    "avg_score": avg_score,
                    "passed_gate": gate,
                    "chunk_hit": result.chunk_hit,
                    "boundary_break": result.boundary_break,
                    "citation_span_accuracy": result.citation_span_accuracy,
                    "clause_precision": result.clause_precision,
                    "clause_recall": result.clause_recall,
                    "clause_f1": result.clause_f1,
                    "clause_boundary_correct": result.clause_boundary_correct,
                },
            )
        except Exception as exc:
            logger.error("Offline eval failed for case %s: %s", case_id, exc, exc_info=True)
            end_trace(trace_ctx, status="error", error=str(exc))

    total = len(results)
    pass_rate = (passed / total) if total else 0.0
    false_negative_rate_entity = (entity_false_negative / entity_cases) if entity_cases else 0.0
    avg_token_cost = (sum(token_cost_samples) / len(token_cost_samples)) if token_cost_samples else 0.0
    chunk_hit_rate_at_k = (sum(chunk_hits) / len(chunk_hits)) if chunk_hits else 0.0
    boundary_break_rate = (sum(boundary_breaks) / len(boundary_breaks)) if boundary_breaks else 0.0
    citation_span_accuracy = (sum(citation_span_accuracies) / len(citation_span_accuracies)) if citation_span_accuracies else 0.0
    cross_chunk_stitch_success = max(0.0, min(1.0, 1.0 - boundary_break_rate))
    chunk_dedup_rate = float(dataset[0].get("chunk_dedup_rate", 0.0) or 0.0) if dataset else 0.0
    clause_precision_avg = (sum(clause_precisions) / len(clause_precisions)) if clause_precisions else 0.0
    clause_recall_avg = (sum(clause_recalls) / len(clause_recalls)) if clause_recalls else 0.0
    clause_f1_avg = (sum(clause_f1s) / len(clause_f1s)) if clause_f1s else 0.0
    clause_boundary_correct_rate = (clause_boundary_correct_cases / total) if total else 0.0
    canary_ready = pass_rate >= 0.85 and false_negative_rate_entity <= 0.05
    rollback_required = pass_rate < 0.8 or false_negative_rate_entity > 0.1
    return {
        "total": total,
        "passed": passed,
        "pass_rate": round(pass_rate, 4),
        "baseline_min": baseline_min,
        "entity_cases": entity_cases,
        "entity_false_negative": entity_false_negative,
        "false_negative_rate_entity": round(false_negative_rate_entity, 4),
        "avg_token_cost": round(avg_token_cost, 4),
        "chunk_hit_rate_at_k": round(chunk_hit_rate_at_k, 4),
        "boundary_break_rate": round(boundary_break_rate, 4),
        "citation_span_accuracy": round(citation_span_accuracy, 4),
        "cross_chunk_stitch_success": round(cross_chunk_stitch_success, 4),
        "chunk_dedup_rate": round(chunk_dedup_rate, 4),
        "clause_precision": round(clause_precision_avg, 4),
        "clause_recall": round(clause_recall_avg, 4),
        "clause_f1": round(clause_f1_avg, 4),
        "clause_boundary_correct_rate": round(clause_boundary_correct_rate, 4),
        "canary_ready": canary_ready,
        "rollback_required": rollback_required,
        "results": [r.__dict__ for r in results],
        "release_risk": pass_rate < 0.8,
    }
