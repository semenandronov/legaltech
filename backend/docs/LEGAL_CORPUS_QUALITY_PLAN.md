# План качественного справочника (без костылей)

## Принципы

1. **Один акт — один `instrument_id`** (`fz-127` для всех глав 127‑ФЗ).
2. **Связи из закона**, не из таблиц «тема → статьи»: граф отсылок + структура глав/статей.
3. **ИИ планирует статьи** под конкретный вопрос (`legal_retrieval_planner`); детерминированный слой — только акты и явные статьи из текста вопроса.
4. **Graph-first retrieval**: план → узлы графа → BFS 2–3 шага → hybrid/FTS как дополнение.
5. **Проверка полноты** по `required_articles` плана, не по захардкоженным пакетам.
6. **Инкрементальная загрузка по главам** + reconcile графа после каждой главы.

## Архитектура ответа

```
Вопрос
  → LLM-план (статьи, акты, запросы)
  → merge с детерминированным (только явные статьи из вопроса + instrument routing)
  → norm tree / graph cluster (паутина)
  → FTS по статьям плана
  → hybrid (если недостаточно)
  → gap-fill + iterative
  → sufficiency gate
  → ответ с цитатами
```

## Загрузка 127‑ФЗ по главам

### Формат: **PDF** (цифровой экспорт КонсультантПлюс) или **HTML**

**PDF pipeline** (`consultant_pdf_preprocess.py`):
1. PyMuPDF извлекает текст блоками (reading order)
2. Отрезается оглавление, колонтитулы, водяные знаки Консультанта
3. Docling пробует AST на исходном PDF
4. Если структура статей слабая — авто-retry на очищенный text extract

1. `instrument_id=fz-127` для каждой главы
2. Порядок: по главам закона (отсылки догоняются reconcile)
3. После каждой главы: graph sync + health check + reconcile
4. После всех глав — eval из `evals/legal_corpus_retrieval_eval_dataset.json`

| Переменная | По умолчанию | Назначение |
|------------|--------------|------------|
| `LEGAL_CORPUS_PDF_PREPROCESS_ENABLED` | true | PyMuPDF + очистка PDF |
| `LEGAL_CORPUS_PDF_TEXT_FIRST` | false | Только text extract, без Docling |

## Конфигурация

| Переменная | По умолчанию | Назначение |
|------------|--------------|------------|
| `LEGAL_NORM_GRAPH_MAX_HOPS` | 2 | Глубина обхода паутины |
| `LEGAL_NORM_GRAPH_CLUSTER_ENABLED` | true | Graph-first по статьям плана |
| `LEGAL_NORM_GRAPH_RECONCILE_ON_UPLOAD` | true | Reconcile после загрузки главы |
| `LEGAL_CORPUS_INDEX_GRAPH_VALIDATION_STRICT` | false | Сбой загрузки при пустом графе |

## Что сознательно не делаем

- Таблицы «субсидиарка → 61.11» в роутере.
- Расширение search queries захардкоженными статьями в `legal_router`.
- LightRAG / LLM-граф вместо `legal_norm_graph`.

## Дальнейшие шаги

- [ ] Eval gate в CI по `legal_corpus_retrieval_eval_dataset.json`
- [ ] Пленум ВС №53 в реестре `legal_instruments`
- [ ] Langfuse dashboard: `graph_cluster_docs`, `articles_missing`
- [ ] UI: статус health после загрузки главы
