# Citation contract v1 (SSE + LangGraph state)

Единый payload цитат для case-assistant: LangGraph `rag_retrieval_node`, fast-path в `orchestrator`, опционально structured citations.

## Поля (совместимость `Citation` в `app/services/chat/events.py`)

- `citation_id` (**да**): стабильный id цитаты для UI (дедуп/клики). Генерируется из `chunk_id` либо из `(source_id, page, char_start, char_end)`.
- `source_id` (**да**): UUID файла в деле (`file_id` из метаданных чанка).
- `file_name` (**да**): `source_file` / имя файла.
- `source_type` (**да**): `document` / `legal_reference` / …
- `page` (**нет**): **1-based** номер страницы. **Строго** берётся из Docling provenance `dl_meta.doc_items[].prov[].page_no` как минимум по всем prov; 0 нормализуется в 1. Если provenance нет — `null` (UI не должен “угадывать” страницу).
- `quote` (**нет**): короткий превью-текст (чанк).
- `quote_anchor` (**нет**): якорь для поиска/подсветки в `File.original_text` (в идеале `original_text[char_start:char_end]` при валидных offsets).
- `char_start`, `char_end` (**нет**): смещения в **склеенном** `original_text` как при индексации (`\n\n` между чанками, см. `DocumentProcessor.split_documents`).
- `chunk_id` (**нет**): стабильный id чанка (для трассировки/маппинга structured citations).
- `bbox` (**нет**): один bbox-регион (первый) для обратной совместимости. Формат: `{ x0, y0, x1, y1 }` в PDF user space.
- `bbox_regions` (**нет**): список bbox-регионов (если чанк покрывает несколько фрагментов). Каждый элемент: `{ x0, y0, x1, y1 }` в PDF user space.
- `page_bbox` (**нет**): размеры страницы, `{ width, height }` (используется UI для нормализации/перевода координат).

## Инварианты

1. Порядок `citations[]` = порядок `[N]` в ответе и нумерация «Источник N» в `format_sources_for_prompt`.
2. При наличии `original_text` в БД и валидных `char_start`/`char_end`: `quote_anchor == original_text[char_start:char_end]` (см. `build_retrieval_citations`).
3. Пост-обработка: `repair_citation_brackets` удаляет `[N]`, если `N` ∉ `1..len(citations)` (LangGraph + fast path).

## Feature flags

- `RAG_LANGGRAPH_STRUCTURED_CITATIONS_ENABLED` — второй LLM-проход `generate_with_structured_citations` в `generate_response_node` (режим `normal`, есть RAG-контекст). По умолчанию **выкл.** (latency/стоимость).

## PDF / bbox

### Источник координат и номера страницы (строгость)

- `page`, `bbox`, `bbox_regions`, `page_bbox` **нельзя** брать из “угадывания”/других метаданных: только из Docling provenance (`dl_meta...prov...`).
- Если в метаданных чанка после Docling нет provenance (или bbox) — `bbox`/`bbox_regions`/`page_bbox` будут `null`; UI должен работать через `highlightPage` + text-layer поиск по `quote_anchor` (см. `DocumentPreviewSheet` → `PDFViewer`).

### Нормализация `page_no`

- Берём **минимальный** `page_no` по всем `prov` (чанк может пересекать страницы/области).
- Если минимум равен 0 — считаем, что это 0-based и нормализуем в 1.
- Если минимум \(\ge 1\) — считаем, что это 1-based и используем как есть.

## Ручной чеклист приёмки

1. **TXT** — ответ с `[1]`, клик открывает файл, подсветка по `quote_anchor`/offset.
2. **DOCX** — то же (HTML-превью / якорь).
3. **PDF** — при наличии bbox в metadata — оверлей; без bbox — страница + текстовый fallback, UX не ломается.
