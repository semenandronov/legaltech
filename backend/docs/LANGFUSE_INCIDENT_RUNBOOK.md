# Langfuse Incident Runbook (Case Assistant)

## Goal
Find root cause of bad response or high latency in 5-10 minutes using one trace.

## Step 1: Locate a Trace
- Filter by time window, `assistant_type=case_assistant`, and user/session if available.
- Open the latest problematic trace.

## Step 2: Validate Trace Completeness
Check event sequence:
- `request_received`
- `request_routed`
- `prompt_prepared`
- `tool_call_started/completed` (if tool path)
- `llm_generation`
- `response_saved`
- `request_completed`

If events/metadata are missing, classify incident as observability gap first.

## Step 3: Identify Slow Phase
From `request_completed.metadata` read:
- `orchestration_ms`
- `route_and_tooling_ms`
- `persistence_ms`
- `total_ms`

Interpretation:
- high `route_and_tooling_ms`: tools/retrieval/model loop is bottleneck
- high `orchestration_ms`: routing/session/gates overhead
- high `persistence_ms`: database save contention

## Step 4: Drill Into Tools
- For each `tool_call_completed`, inspect:
  - `tool_name`
  - `latency_ms`
  - `tool_input_preview_len`
  - `tool_output_preview_len`
- If `sla_warning` exists, prioritize that tool first.

## Step 5: Assess Quality
- Read `quality_gate` events (scope/citation/confidence)
- Check scores:
  - `answer_groundedness`
  - `citation_coverage`
  - `response_usefulness`

Quick triage:
- low groundedness + low citation coverage -> retrieval/citation issues
- good citations + low usefulness -> synthesis/prompt routing issue

## Step 6: Decide Action
- Tool bottleneck: optimize retrieval strategy / reduce context / cache
- Quality gate blocked: tune prompt profile and gate thresholds
- Missing metadata: fix event contract immediately
- Recurrent issue: add alert and regression test case

## Post-Incident Notes Template
- Trace ID:
- Session ID:
- Mode / prompt profile:
- Slowest phase:
- Slowest tool:
- Gate outcomes:
- Scores:
- Root cause:
- Applied fix:
- Follow-up task:
