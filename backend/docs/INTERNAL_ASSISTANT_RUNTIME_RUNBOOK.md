# Internal Assistant Runtime Runbook

## Scope
This runbook defines production hardening rules for the in-case assistant runtime.

## Runtime Contract
- Router is strict-mode only with fixed priority:
  - `DRAFT=true` -> drafting path only.
  - `legal_research=true` (КОДЕКС) -> mixed path (case docs + legal corpus).
  - default -> case-only fast extraction path.
- Hidden fallback transitions between modes are forbidden.
- Default mode must never call legal corpus tools.
- Empty final answer is always blocked (`answer_generation_failed`).

## Operational Checks
1. Confirm singleton services are active:
   - `DocumentProcessor`
   - `RAGService`
2. Confirm no request-time sparse cold build in hot path:
   - repeated `BM25 index not found ... building index` in chat requests is not allowed.
3. Confirm traces include:
   - `coverage_status`
   - `negative_answer_allowed`
   - `retrieval_k`
   - `retrieved_chunks_count`
4. Confirm routing contract fields exist in each request trace:
   - `task_family`
   - `route_confidence`
   - `route_reason`
   - `fallback_reason` (when fallback triggered)
5. Confirm strict mode traces contain:
   - `execution_path` in `{draft_path,mixed_path,fast_path}`
   - `task_type`
   - `route_reason`
   - `fallback_reason` (only on blocked requests)

## CI Regression Checks
- `pytest backend/tests/test_entity_fact_pipeline.py`
- `pytest backend/tests/test_conversation_policy_contracts.py`
- `pytest backend/tests/test_langfuse_eval_runner.py`
- `python3 -m py_compile backend/app/services/chat/orchestrator.py backend/app/services/chat/entity_fact_pipeline.py`

## Incident Response
1. Set traffic to 0% for new pipeline (feature flag rollback).
2. Re-run offline eval suite and compare:
   - `false_negative_rate_entity`
   - `entity_recall@k`
   - `token_cost_per_fact_answer`.
3. Re-enable traffic only after strict-mode contract checks pass.
