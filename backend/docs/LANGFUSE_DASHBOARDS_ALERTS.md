# Langfuse Dashboards and Alerts

## Core Dashboards

## 1) Request Health
- P50/P95 `request_completed.latency_ms` by `mode`
- Error rate from `request_completed.status=error` and `tool_call_failed`
- SLA warning rate (`sla_warning`) over time

## 2) Tool Performance
- P50/P95 tool latency from `tool_call_completed.latency_ms` by `tool_name`
- Slow tool count (`sla_warning.sla_type=tool_latency`)
- Tool success/failure ratio by `tool_name`

## 3) Quality Trend
- `answer_groundedness` average by day/release
- `citation_coverage` average and low-tail (<0.4)
- `response_usefulness` average and low-tail (<0.5)
- `quality_gate` blocked rate by gate type

## 4) Completeness and Coverage
- Share of traces missing required events
- Share of traces with empty metadata in key events
- Share of traces missing required scores

## Recommended Alerts

## Alert A: Request Latency Regression
- Condition: P95 request latency > 60s for 10m
- Filter: `assistant_type=case_assistant`
- Action: notify on-call and include top `mode`

## Alert B: Tool Latency Regression
- Condition: tool P95 latency > 30s for 10m
- Filter: `tool_name`
- Action: include top offenders by count and max latency

## Alert C: Quality Drop
- Condition: rolling avg of `response_usefulness` < 0.6 for 30m
- Action: attach top 10 low-scored trace IDs

## Alert D: Observability Blind Spots
- Condition: >5% traces missing required metadata/events in 30m
- Action: notify platform owner; block release if persistent

## Suggested Tags/Filters
- `assistant_type=case_assistant`
- `mode=react_agent|react_agent_deep|react_agent_garant|draft|editor`
- `prompt_profile_id`
- `environment=development|staging|production`
- `release`
