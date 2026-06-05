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

## Case Context Pipeline (Secretary → Recall → Rerank)

Enabled when `CASE_ASSISTANT_CONTEXT_PIPELINE_ENABLED=true` (default).

| Stage | Node / module | Env knobs |
|-------|----------------|-----------|
| 1 Secretary | `extract_retrieval_task` / `retrieval_router.py` + `file_summary_index.py` | `CASE_ASSISTANT_FILE_SUMMARY_INDEX_*` (hybrid step 1), `CASE_ASSISTANT_LLM_ROUTER_FALLBACK_ENABLED`, `CASE_ASSISTANT_ROUTER_HEURISTIC_*`, `CASE_ASSISTANT_CATALOG_CACHE_*`, `CASE_ASSISTANT_LLM_ROUTER_ENABLED`, `CASE_ASSISTANT_ROUTER_MODEL` |
| 2 Recall | `rag_retrieval` + `run_hybrid_recall` | `CASE_ASSISTANT_RECALL_K` (legacy 100 when adaptive off) |
| 3 Rerank | `rerank_context` + `RerankerService` | `CASE_ASSISTANT_RERANK_ENABLED`, `RERANKER_MODEL_NAME=BAAI/bge-reranker-v2-m3`, `CASE_ASSISTANT_FINAL_K` |

### Adaptive execution tiers (case chat)

Enabled when `CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED=true` (default). Policy resolves `execution_tier` in `budget_profile` before the graph runs.

| Tier | Typical trigger | `recall_k` | Rerank | `final_k` |
|------|-----------------|------------|--------|-----------|
| `no_retrieval` | greeting / thanks | 0 | off | 0 |
| `clarify` | empty / too short / explicit «уточни» markers | 0 | off | 0 |
| `instant` | fact lookup, fast single doc | `CASE_ASSISTANT_INSTANT_RECALL_K` (16) | off | 6 |
| `standard` | one doc / short analysis | `CASE_ASSISTANT_STANDARD_RECALL_K` (35) | on | 10 |
| `deep` | synthesis, contradiction | 100 | on | 15 |
| `mixed` | `legal_research=true` | 100 | on | 15 |

**Graph path (normal mode):** `mode_router` → `sync_execution_tier` → (`clarify_response` \| `generate_response` \| `extract_retrieval_task` → parallel RAG) → `rerank_context` → `grade_retrieval` → (`rewrite_search_query` loop \| `rag_quality_gate`) → `generate_response`.

**Env knobs:**

- `CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED` — rollback to fixed `recall_k=100` for all tiers
- `CASE_ASSISTANT_INSTANT_RECALL_K`, `CASE_ASSISTANT_STANDARD_RECALL_K`
- `CASE_ASSISTANT_STANDARD_MAX_RETRIEVAL_ROUNDS`, `CASE_ASSISTANT_DEEP_MAX_RETRIEVAL_ROUNDS`
- `CASE_ASSISTANT_TIER_LLM_ENABLED`, `CASE_ASSISTANT_TIER_CLASSIFIER_MODEL` — optional structured tier classifier before graph
- `CASE_ASSISTANT_STREAM_CASE_CHAT` — token streaming for in-case chat (no editor document)
- `ASSISTANT_ASYNC_PERSIST_ENABLED` (default `true`) — commit assistant message after SSE `finish`, not before connection close
- `ASSISTANT_ASYNC_PERSIST_MAX_RETRIES` — background DB retries (default `2`)
- `GLOBAL_ASSISTANT_STREAM_GRAPH_PROGRESS` (default `true`) — SSE status during global LangGraph retrieval before LLM generation

**Langfuse fields:** `execution_tier`, `recall_k`, `rerank_enabled`, `retrieval_round`, `escalated_from` (on tier escalation after weak instant recall).

**Scope router:** single call in `extract_retrieval_task_node` only (no API pre-route duplicate).

**Scope priority:** `attached_file_ids` → active `document_id` → **heuristic catalog** (if conf ≥ threshold) → **file summary hybrid** (vector+FTS+RRF+dynamic K) → **lite fallback** (only on summary miss) → full case.

**File summary index:** table `case_file_summaries`; upsert on ingest (`file_processor_bg`); lazy backfill via `ensure_case_summaries_indexed`; script `scripts/backfill_file_summary_index.py`.

**BM25:** `schedule_bm25_prewarm` on GET case + start of `assistant_chat_v2`; hybrid search uses in-memory index when ready (`CASE_BM25_SYNC_ON_HYBRID_SEARCH`, default true).

**Langfuse trace fields:** `scope_mode`, `scoped_files_count`, `recall_k`, `final_k`, `recall_docs`, `rerank_docs`, `rerank_model` (in trace `extra` and `context_pipeline_meta` after rerank).

### Детальная Langfuse-трассировка (case assistant)

Включена по умолчанию: `CASE_ASSISTANT_LANGFUSE_DETAILED=true` (отключить: `false`).

Иерархия nested spans под trace запроса:

| Span | Содержание |
|------|------------|
| `case_assistant.pipeline` | recall / rerank / assemble (узлы `rag_retrieval`, `rerank_context`) |
| `case_assistant.router` | `extract_retrieval_task` (scope_mode, file_ids, confidence) |
| `case_assistant.file_summary_scope` | step-1 отбор файлов (embed + dense + FTS + RRF) |
| `case_assistant.hybrid_recall` | вызов `retrieve_context` hybrid |
| `case_assistant.macro_micro_funnel` | macro → micro → scoped_micro → docling |
| `case_assistant.hybrid.macro` / `.micro` / `.scoped_micro` / `.docling_*` | уровни чанков |
| `case_assistant.hybrid_search.dense` / `.fts` / `.anchor` / `.bm25_fallback` / `.rrf` | внутри одного hybrid_search |
| `case_assistant.rerank` | cross-encoder (или `rerank_skipped` с reason) |
| `case_assistant.assemble_context` | prompt context + citations |

События `step_started` / `step_completed` дублируют ключевые метрики для экспорта JSON.

### Пошаговая трассировка пайплайна (case + global)

Включена по умолчанию: `ASSISTANT_PIPELINE_LANGFUSE_DETAILED=true` (или legacy `CASE_ASSISTANT_LANGFUSE_DETAILED=true`; отключить: `false`).

Требует `LANGFUSE_ENABLED=true`. Имена span: `assistant.{case|global}.{step}`.

| Группа | Span | Содержание |
|--------|------|------------|
| HTTP (case) | `assistant.case.http.case_doc_count` | probe `num_documents` |
| HTTP (case) | `assistant.case.http.infer_task_and_depth` | эвристика task/depth |
| HTTP (case) | `assistant.case.http.tier_classifier_llm` | LLM execution tier |
| HTTP (case) | `assistant.case.http.budget_profile` | budget profile |
| Orchestrator | `assistant.case.orchestrator.prepare_session` | session + user msg |
| Orchestrator | `assistant.case.orchestrator.build_session_context` | thread + resolver |
| Orchestrator | `assistant.case.orchestrator.route_to_handler` | LangGraph stream |
| Graph prep | `assistant.case.graph_prepare.*` | compile, checkpoint, hydrate |
| Session context | `assistant.case.session_context.*` | load_turns, semantic_search, resolver_llm |
| Persist | `assistant.case.persist.assistant_message` | sync/async save |
| HTTP (global) | `assistant.global.http.*` | session, transcript, files |
| Global | `assistant.global.session_context.build` | recap / resolver |
| Global | `assistant.global.langgraph.run` | graph stream |
| Global | `assistant.global.generation.stream` | LLM tokens |
| Global | `assistant.global.persist.assistant_message` | save |

Trace case создаётся до HTTP prep (убирает «слепую зону» до SSE).

**Rollback:** set `CASE_ASSISTANT_CONTEXT_PIPELINE_ENABLED=false` — graph uses legacy `rag_retrieval` (multi_stage on deep only).

### Golden manual QA (5 scenarios, ~40 files)

1. Один договор по контрагенту — без скрепки → ответ из правильного `file_id`.
2. Два файла — сравнение неустойки — скрепка 2 → scope `attached`.
3. «Обзор дела» — 40 файлов → `full_case` или широкий scope.
4. «п. 6.2» — anchor/hybrid path сохраняет hit по пункту.
5. Fast fact «какая сумма» — passport сужает до 1–6 файлов.

## CI Regression Checks
- `pytest backend/tests/test_entity_fact_pipeline.py`
- `pytest backend/tests/test_conversation_policy_contracts.py`
- `pytest backend/tests/test_case_retrieval_router.py`
- `pytest backend/tests/test_reranker_service.py`
- `pytest backend/tests/test_rerank_context_node.py`
- `pytest backend/tests/test_conversation_policy_pipeline_budget.py`
- `pytest backend/tests/test_tier_graph_nodes.py`
- `pytest backend/tests/test_execution_tier_classifier.py`
- `pytest backend/tests/test_langfuse_eval_runner.py`
- `python3 -m py_compile backend/app/services/chat/orchestrator.py backend/app/services/chat/entity_fact_pipeline.py`

## Incident Response
1. Set traffic to 0% for new pipeline (feature flag rollback).
2. Re-run offline eval suite and compare:
   - `false_negative_rate_entity`
   - `entity_recall@k`
   - `token_cost_per_fact_answer`.
3. Re-enable traffic only after strict-mode contract checks pass.
