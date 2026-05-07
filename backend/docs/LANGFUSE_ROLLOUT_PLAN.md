# Langfuse Rollout Checklist

## Stage 1: Development
- Set `LANGFUSE_ENABLED=true` with dev project keys.
- Keep `LANGFUSE_SAMPLE_RATE=0.2`.
- Verify traces for:
  - `/api/v2/assistant/chat`
  - workflow execution path
  - LLM factory creation events

## Stage 2: Staging
- Increase sample rate to `0.5`.
- Validate prompt fallback by forcing one missing prompt.
- Run offline eval job:
  - `python -m backend.scripts.run_langfuse_evals --dataset <dataset.json> --baseline-min 0.65`
- Review pass rate and release risk flag.

## Stage 3: Production
- Enable `LANGFUSE_ENABLED=true` with production keys.
- Start with `LANGFUSE_SAMPLE_RATE=0.2` for 24h.
- Increase to `1.0` after stability check.
- Monitor:
  - error rate by route
  - avg latency by model/provider
  - token/cost drift

## Runtime Safety
- If Langfuse is unavailable, service continues in no-op mode.
- Prompt retrieval always falls back to local in-code prompt text.
