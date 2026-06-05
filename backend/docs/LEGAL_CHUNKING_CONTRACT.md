# Legal Chunking Contract

## Objective

Define a stable contract for dual legal-aware chunking with two layers:

- `macro`: section-level context blocks for broad retrieval.
- `micro`: clause-level blocks for precise grounding and citation.

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

## Optional metadata (indexing / retrieval extensions)

Not required for hybrid merge logic, but emitted by `LegalChunkerV2` / PGVector ingest:

- `is_table_fragment` (`bool`): chunk comes from a sharded Docling `TableItem` (row groups with repeated markdown header).
- `embedding_text` (`str`, optional): when `LEGAL_CHUNK_EMBED_PREFIX_ENABLED` is true, embeddings are computed from `[Контекст: parent_path > section] + page_content` while `page_content` stays the clean excerpt for LLM prompts.

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

## Retrieval Contract

- Hybrid retrieval runs both levels (`macro` and `micro`) and merges deduplicated candidates.
- Funnel metrics are emitted as observability events under `retrieval_funnel`.

## Gate KPIs

- `chunk_hit_rate_at_k`
- `boundary_break_rate`
- `citation_span_accuracy`
- `cross_chunk_stitch_success`
- `chunk_dedup_rate`
