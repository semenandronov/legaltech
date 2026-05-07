# Legal Chunking Rollout

## Stages

1. `10%` canary
2. `50%` partial rollout
3. `100%` full rollout

Traffic split is controlled by `LEGAL_CHUNKING_TRAFFIC_PERCENT`.

## Promotion Rules

Source: `backend/scripts/eval_canary_gate.py`

- Promote to `100%`:
  - `pass_rate >= 0.9`
  - `false_negative_rate_entity <= 0.02`
  - `chunk_hit_rate_at_k >= 0.85`
  - `boundary_break_rate <= 0.08`
  - `citation_span_accuracy >= 0.85`

- Promote to `50%`:
  - `pass_rate >= 0.85`
  - `false_negative_rate_entity <= 0.05`
  - `chunk_hit_rate_at_k >= 0.75`
  - `boundary_break_rate <= 0.12`
  - `citation_span_accuracy >= 0.75`

- Rollback:
  - `pass_rate < 0.8` OR
  - `false_negative_rate_entity > 0.10` OR
  - `chunk_hit_rate_at_k < 0.6` OR
  - `boundary_break_rate > 0.2`

## Operational Checklist

1. Run offline eval:
   - `python3 backend/scripts/run_langfuse_evals.py --dataset backend/evals/legal_chunking_eval_dataset.json --output backend/eval-report.json`
2. Get decision:
   - `python3 backend/scripts/eval_canary_gate.py --report backend/eval-report.json`
3. Update env var `LEGAL_CHUNKING_TRAFFIC_PERCENT` according to decision.
4. Monitor retrieval funnel events and citation quality in Langfuse.
