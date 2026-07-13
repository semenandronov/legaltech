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
- `highlight_targets` (**нет**): для `chunk_level=row` (выписки/Excel) — упорядоченный список значений ячеек для DOM/HTML-подсветки. `quote` может оставаться в формате `Col: value`; поиск в таблице идёт по `highlight_targets` / якорной ячейке. При наличии `highlight_targets` поле `quote_anchor` **всегда** берётся из первой цели (даже если `original_text` — dump всего листа).
- `char_start`, `char_end` (**нет**): смещения в **склеенном** `original_text` как при индексации (`\n\n` между чанками, см. `DocumentProcessor.split_documents`).
- `chunk_id` (**нет**): стабильный id чанка (для трассировки/маппинга structured citations).
- `bbox` (**нет**): один bbox-регион (первый из отфильтрованного списка) для обратной совместимости. Формат: `{ x0, y0, x1, y1 }` в PDF user space.
- `bbox_regions` (**нет**): bbox-регионы, **пересекающиеся** с char-span цитаты (`char_start`/`char_end` + сужение по `quote_anchor`). Не весь RAG-чанк. Каждый элемент: `{ x0, y0, x1, y1 }` в PDF user space.
- `page_bbox` (**нет**): размеры страницы, `{ width, height }` (используется UI для нормализации/перевода координат).

## Инварианты

1. Порядок `citations[]` = порядок `[N]` в ответе и нумерация «Источник N» в `format_sources_for_prompt`.
2. При наличии `original_text` в БД и валидных `char_start`/`char_end`: для narrative/PDF чанков `quote_anchor == original_text[char_start:char_end]` (см. `build_retrieval_citations`). Для `chunk_level=row` с `highlight_targets` — якорь = значение ячейки, не dump листа.
3. Excel / `structured_table`: в промпт и SSE не попадают whole-sheet окна `original_text` (`within_file_source=original_*`) — только row-чанки (`tabular_citation_policy`).
4. Пост-обработка: `repair_citation_brackets` удаляет `[N]`, если `N` ∉ `1..len(citations)` (LangGraph + fast path).

## Feature flags

- `RAG_LANGGRAPH_STRUCTURED_CITATIONS_ENABLED` — второй LLM-проход `generate_with_structured_citations` в `generate_response_node` (режим `normal`, есть RAG-контекст). По умолчанию **выкл.** (latency/стоимость).

## PDF / bbox

### Источник координат и номера страницы (строгость)

- **Текстовые PDF (Docling AST):** `page`, `bbox`, `bbox_regions`, `page_bbox` — из Docling provenance (`dl_meta...prov...`).
- **Сканы (Yandex OCR):** один bbox на OCR-блок; `LegalChunkerV2` пишет в `dl_meta.doc_items[].prov[]` с `char_start`/`char_end` на блок. Micro-чанк получает только prov, чей char-span пересекается с чанком; citation SSE фильтрует по span цитаты.
- Порядок в `RAGService._extract_bbox_regions`: сначала `dl_meta` (с опциональным char-span фильтром), иначе `bbox_regions`/`bbox` на чанке.
- **Reindex:** документы, проиндексированные до prov `char_start`/`char_end`, отдают в citation не более одного bbox (legacy cap) до переиндексации.
- Если provenance/bbox нет — `bbox`/`bbox_regions`/`page_bbox` будут `null`; UI — `highlightPage` + text-layer по `quote_anchor`.

### Нормализация `page_no`

- Берём **минимальный** `page_no` по всем `prov` (чанк может пересекать страницы/области).
- Если минимум равен 0 — считаем, что это 0-based и нормализуем в 1.
- Если минимум \(\ge 1\) — считаем, что это 1-based и используем как есть.

## Оригинал файла (просмотр по цитате)

- Загрузка в дело (диск, Google Drive и т.д.) сохраняет байты в `UPLOAD_DIR/{case_id}/…` и `files.file_path`.
- Просмотр: `GET /api/cases/{case_id}/files/{file_id}/content` — единый путь `load_case_file_bytes` (диск → опционально `file_content` в БД).
- UI открывает viewer по `source_id` (= `file_id`), без ожидания списка файлов; каталог — только для уточнения типа/`legacy_fallback`.

## Ручной чеклист приёмки

1. **TXT** — ответ с `[1]`, клик открывает файл, подсветка по `quote_anchor`/offset.
2. **DOCX** — то же (HTML-превью / якорь).
3. **PDF** — при наличии bbox в metadata — оверлей; без bbox — страница + текстовый fallback, UX не ломается.
