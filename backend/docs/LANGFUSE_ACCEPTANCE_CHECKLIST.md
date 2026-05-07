# Langfuse Acceptance Checklist (Case Assistant)

## Test Set (10 prompts)
- 3 overview prompts
- 3 specific factual prompts
- 2 legal research prompts
- 2 draft/editor prompts

## Pass Criteria
- 100% traces include required event lifecycle
- 0 traces with empty metadata on critical events
- 100% traces include phase latency fields
- 100% traces include 3 required scores
- each trace has enough data to identify root cause without external logs

## Manual Verification per Trace
- Check required events sequence
- Check `request_completed.metadata` has:
  - `orchestration_ms`
  - `route_and_tooling_ms`
  - `persistence_ms`
  - `total_ms`
  - gate outcomes
- Check tool events include `tool_name` and `latency_ms`
- Check scores are attached and non-null

## Regression Guard
- Repeat checklist in staging before each release touching:
  - routing
  - tools
  - prompt profiles
  - observability service
