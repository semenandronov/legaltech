# Tabular Context Engineering

Production contract for tabular review retrieval → context → extract (`tabular_context_compiler_v1`).

## Pipeline stages

1. **DCP** — `TabularFileContextPackage` (outline + definitions roots + passport), persisted at ingest in `File.processing_progress.document_outline_v1`.
2. **Section router** — maps column rewrite plan → `section_root_id` list (hybrid on section labels + exact clause).
3. **Hybrid recall** — scoped `file_id` + optional `section_root_id` metadata filter; fallback full file if empty pool.
4. **Lexical channel** — independent literal recall + merge (unchanged).
5. **Rerank + section expand** — `context_resolution` (unchanged).
6. **Cross-ref enrich** — `contract_cross_ref_resolve` + macro fetch (optional).
7. **Coverage gate + escalation** — second retrieval round (`deepen_in_files` budget bump) without second extract.
8. **Extract** — `navigation_block` in prompt (not mixed into citation `rag_context`).

## Failure taxonomy (`context_outcome`)

- `empty_query` | `no_recall_docs` | `empty_context` | `weak_coverage` | `escalated` | `front_matter_hit` | `extract_na` | `ok`

## Feature flags (env)

| Flag | Default | Purpose |
|------|---------|---------|
| `TABULAR_CONTEXT_COMPILER_ENABLED` | true | Unified compiler vs legacy retrieve path |
| `TABULAR_DCP_ENABLED` | false | File context packages on column run |
| `TABULAR_SECTION_ROUTER_ENABLED` | false | Section-scoped recall |
| `TABULAR_RETRIEVAL_ESCALATION_ENABLED` | false | Second retrieval round |
| `TABULAR_CROSS_REF_FOLLOW_ENABLED` | false | Pull referenced sections |
| `TABULAR_MAX_RETRIEVAL_ROUNDS` | 2 | Escalation cap |
| `TABULAR_CROSS_REF_MAX_CHARS` | 2500 | Cross-ref budget |
| `TABULAR_SECOND_EXTRACT_ON_WEAK` | false | Do not enable routine second extract |

## Eval

`python3 backend/scripts/tabular_context_recall_eval.py --case-id … --spec evals/….json`

Metrics: `recall_pool_hit`, `prompt_hit`, `escalation_used` per cell (retrieval-only, no extract LLM).

## Rollout

1. Canary: enable `TABULAR_DCP_ENABLED` + `TABULAR_SECTION_ROUTER_ENABLED` on internal case.
2. Beta: add `TABULAR_RETRIEVAL_ESCALATION_ENABLED`.
3. Default on after RU 15 + SHAK 10 green and MAUD context-recall KPI recorded.
