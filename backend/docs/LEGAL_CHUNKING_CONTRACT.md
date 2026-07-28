# Legal Chunking Contract

## Objective

Define a stable contract for dual legal-aware chunking with two layers plus a
logical section root (contract version **v2.2**):

- `micro`: clause-level leaves for precise retrieval and PDF bbox.
- `macro`: size-window blocks inside a hard section (embedding / storage unit).
- `section_root_id`: identity of the hard legal section; LLM context expands here.

## Required Metadata

Every chunk stored in vector index must contain:

- `doc_id`
- `file_id`
- `case_id`
- `source_file`
- `chunk_id`
- `chunk_index`
- `chunk_level` (`macro` or `micro`)
- `chunk_profile` (`contracts`, `court_docs`, `regulations`)
- `char_start`
- `char_end`
- `section_title`
- `section_number`
- `parent_path`
- `clause_type`
- `cross_references`
- `macro_id`
- `parent_macro_id` (empty on macro; equals `macro_id` on micro)
- `section_root_id` (shared by all macros/micros inside one hard section)
- `chunking_contract_version` (`v2.2`)

## Optional metadata (indexing / retrieval extensions)

- `is_table_fragment` (`bool`): chunk comes from a sharded Docling `TableItem`.
- `embedding_text` (`str`): retrieval text = section label + `page_content`. Used for
  **dense embeddings and lexical search (BM25 / PG FTS)**. `page_content` stays clean
  for LLM prompts, citations, and bbox.
- `section_retrieval_label` (`str`): deterministic hard-section label written at index
  time (e.g. `1. ПРЕДМЕТ ДОГОВОРА`).
- `section_embedding_label` (`str`, optional): override label (e.g. short LLM blurb for
  the hard section); when set, wins over `section_title`.

### Section retrieval labels (production)

Each micro/macro gets a search prefix such as:

```text
[Контекст поиска]
Раздел документа: 1. ПРЕДМЕТ ДОГОВОРА

1.4. Заказчик гарантирует…
```

Formed by code from hard-section metadata (no LLM required). Optional enrichment:
one LLM blurb per `section_root_id` stored as `section_embedding_label` and reused for
all leaves in that section.


## Chunk Profiles

### contracts
- macro: size `1400`, overlap `180`
- micro: size `320`, overlap `40`

### court_docs
- macro: size `1200`, overlap `160`
- micro: size `260`, overlap `40`

### regulations
- macro: size `1100`, overlap `120`
- micro: size `240`, overlap `32`

## Rollout Flags

- `LEGAL_CHUNKING_DUAL_ENABLED`
- `LEGAL_CHUNKING_SHADOW_MODE`
- `LEGAL_CHUNKING_TRAFFIC_PERCENT`
- `LEGAL_CHUNKING_DEFAULT_PROFILE`
- `LEGAL_CHUNKING_BUDGET_MAX_TOTAL_CHUNKS`
- `CASE_ASSISTANT_PARENT_CONTEXT_ENABLED`
- `CASE_ASSISTANT_SECTION_CONTEXT_MAX_CHARS` (default `8000`)

## Retrieval Contract

1. Hybrid recall searches **micro** leaves only.
2. After rerank, expand each hit via `section_root_id`:
   - load **all** macros with that root;
   - stitch by `char_start` (drop overlap);
   - fit to `CASE_ASSISTANT_SECTION_CONTEXT_MAX_CHARS` (prefer section head +
     grounding micro window);
   - stamp `grounding_micro_*` from the winning leaf.
3. Legacy indexes without `section_root_id` fall back to `parent_macro_id` → one macro.
4. Tabular review: same expand for LLM context; PDF bbox uses **leaf** chunks only
   (never section/macro boxes). Better no highlight than a wrong parent box.
5. Funnel metrics: `retrieval_funnel` / context_resolution (`sections_resolved`).

## Macro size windows vs hard sections

**Hard boundaries** open a new `section_root_id` (and start a new size window):

1. OCR/layout `TITLE` / `HEADER`
2. Legal keywords: `Часть`, `Раздел`, `Глава`, `Параграф`, `§`, `Статья`, `Приложение`
3. Compact top-level numbered titles: `1. ПРЕДМЕТ ДОГОВОРА` (title-like), not long
   prose `1. Подрядчик обязуется…`

**Soft cues** update breadcrumbs only — **never** a new `section_root_id`:

1. Nested clauses: `1.1.`, `1.2.3.`, …
2. Long top-level numbered prose
3. Compact-looking `Пункт` / `Подпункт` only when title-like; otherwise soft

Size/overlap still splits a long hard section into multiple `macro` rows. Those rows
**share** `section_root_id`. LLM expand reconstitutes the section; embedding recall
still uses micro leaves inside each window.

## Parent–child invariants (index time)

- Every `micro` MUST have non-empty `parent_macro_id` equal to some `macro.macro_id`.
- Every `macro` / `micro` MUST have non-empty `section_root_id`.
- Every macro MUST produce ≥1 micro leaf.
- `section_title` / `section_number` / `parent_path` are breadcrumbs, not the expand key.

## Gate KPIs

- `chunk_hit_rate_at_k`
- `boundary_break_rate`
- `citation_span_accuracy`
- `cross_chunk_stitch_success`
- `chunk_dedup_rate`
