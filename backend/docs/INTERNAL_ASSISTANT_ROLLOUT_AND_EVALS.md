# Internal Assistant Rollout and Evals

## Scope

This rollout applies only to the in-case internal assistant chat runtime:

- `backend/app/routes/assistant_chat_v2.py`
- `backend/app/services/chat/orchestrator.py`
- `backend/app/services/chat/case_assistant_graph_service.py`
- `backend/app/services/chat/conversation_policy_service.py`
- `backend/app/services/observability/langfuse_service.py`

Workflow pages and workflow runtime are intentionally out of scope.

## Rollout stages

1. **Stage 0 (local + CI)**
   - Run unit tests for strict routing and tool-gating contracts.
2. **Stage 1 (full cutover)**
   - Set `CASE_ASSISTANT_GRAPH_V2_ENABLED=true`
   - Ensure `/api/v2/assistant/chat` always executes strict router runtime.
   - Confirm there are no deep/canary route events in traces.

## Eval checklist

- **Routing correctness**
  - `draft_mode=true` always enters draft path and does not execute QA flow.
  - `legal_research=true` routes to mixed branch and can use legal corpus.
  - default mode routes to case-only extraction and never invokes legal corpus tool.
  - no hidden transition between modes.
- **Observability completeness**
  - trace tree has consistent parent links.
  - key events exist: `request_received`, `request_routed`, `llm_generation`, `response_saved`, `request_completed`.
  - event payloads include non-empty input/output/metadata where applicable.
- **User outcome quality**
  - citation coverage score trend does not degrade.
  - response usefulness score trend does not degrade.

## Acceptance matrix

- **Default (both toggles OFF)**: answer only by case documents.
- **КОДЕКС ON**: answer by case documents + legal corpus.
- **DRAFT ON**: generate draft document, no standard QA path.

## Rollback triggers

Rollback to previous commit if:

- mode contract is violated in traces (wrong execution_path for toggle combination);
- legal corpus is used while `legal_research=false`;
- empty final answers pass as successful responses.

