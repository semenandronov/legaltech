# Structured Table Chunking Contract (v1)

## Objective

Index tabular-dominant documents (bank statements, payment registers) with one
vector chunk per logical table row, preserving Docling's column structure without
sharding tables for RAG or splitting rows by character count.

## When this contract applies

`DocumentStructureClassifier` routes a document here when:

- `STRUCTURED_TABLE_INDEXING_ENABLED=true`, and
- Docling AST is dominated by `TableItem` segments with enough data rows, or
- `doc_type` is a known financial register type (`bank_statement`, etc.).

Otherwise the document uses `LegalChunkerV2` (macro/micro, contract v2.1).

## Chunk levels

| `chunk_level` | Meaning |
|---------------|---------|
| `preamble` | Non-table narrative blocks (header, account metadata) |
| `row` | One logical table row (one operation / ledger entry) |

## Required metadata

Every chunk must contain the base ingest fields (`doc_id`, `file_id`, `case_id`,
`source_file`, `chunk_id`, `chunk_index`, `char_start`, `char_end`) plus:

- `chunking_contract_version`: `"structured-table-v1"`
- `index_profile`: `"structured_table"`
- `preseg_strategy`: same as Docling pre-segmentation label
- `chunk_level`: `preamble` | `row`
- `page_start` / `page_end` (when known)

Row chunks additionally:

- `table_index`: 0-based index of `TableItem` in document order
- `row_index`: 0-based row within that table
- `global_row_index`: 0-based row across all tables in the file
- `row_columns`: JSON object `{column_name: cell_value}`
- `is_table_row`: `true`

## Retrieval

Hybrid search treats `row` like `micro` and `preamble` like `macro` so existing
pipelines work without a separate code path.

## Non-goals (v1)

- SQL aggregate store (`structured_document_rows`) — phase B
- Tabular Review `entity` materialization — phase C
