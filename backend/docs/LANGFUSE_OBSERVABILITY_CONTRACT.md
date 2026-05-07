# Langfuse Observability Contract (Case Assistant)

## Scope
This contract applies to:
- `backend/app/services/chat/orchestrator.py`
- `backend/app/services/observability/langfuse_service.py`

## Required Trace Metadata
Every trace for case assistant must include:
- `feature`
- `route`
- `environment`
- `model_provider`
- `assistant_type`
- `mode`
- `case_id`
- `session_id` (when known)
- `prompt_profile_id` (or `legacy_default`)

## Required Events
Expected flow (minimum):
1. `request_received`
2. `request_routed`
3. `prompt_prepared`
4. `tool_call_started` (0..N)
5. `tool_call_completed` / `tool_call_failed` (0..N)
6. `llm_generation`
7. `response_saved`
8. `request_completed`

Additional events:
- `quality_gate`
- `sla_warning`

## Required Event Metadata Fields
All core events should carry:
- `step_name`
- `status` (`running|success|warning|blocked|error`)
- `assistant_type`
- `mode` (when applicable)
- `latency_ms` (when measurable)
- `error` (for failures)

For tool events:
- `tool_name`
- `tool_kind`
- `tool_input_preview_len`
- `tool_output_preview_len`
- `latency_ms`

## Payload Rules
- Use preview payloads only (`question`, `tool_input`, `tool_output`, `response_text`) with truncation.
- Maximum string size is constrained by service sanitization.
- Sensitive keys must be redacted (`token`, `secret`, `password`, `api_key`, `authorization`, `cookie`).

## Quality + Score Contract
Quality gate statuses in trace metadata:
- `scope_result`
- `citation_result`
- `confidence_result`

Required scores per trace:
- `answer_groundedness` (0..1)
- `citation_coverage` (0..1)
- `response_usefulness` (0..1)

Each score must include metadata:
- `assistant_type`
- `mode`
- `prompt_profile_id`
- `session_id`

## SLA Contract
Emit `sla_warning` when:
- total request latency > 60_000 ms
- route/tooling latency > 30_000 ms
- single tool latency > 30_000 ms

Each `sla_warning` includes:
- `sla_type`
- `threshold_ms`
- `actual_ms`
- `step_name`

## Completeness Definition
A trace is considered complete if:
- it has all required lifecycle events,
- no critical event has empty metadata,
- it contains phase latencies (`orchestration_ms`, `route_and_tooling_ms`, `persistence_ms`, `total_ms`),
- it has 3 required scores.
