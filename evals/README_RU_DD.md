# RU DD eval packs (фаза 6)

Контракт качества для tabular due diligence по российским договорам.

| Pack | Назначение | Seed сейчас |
|------|------------|-------------|
| `ru_lease/` | коммерческая аренда / ДС | 1 doc из SS-KOB (`ds1_arenda`) |
| `ru_supply/` | поставка | 1 synthetic mini-contract |
| `ru_services/` | услуги/подряд | 1 synthetic mini-contract |
| `ru_ss_kob/` | mixed regression | уже есть (5×8) |

## Метрики (в run JSON)

- `accuracy` — cell match vs gold
- `schema_hit_rate` — доля ячеек с `extraction_method=contract_facts`
- `forced_na_rate`
- `gold_in_merged_context` (recall слоя) — в full smoke

## Как гонять

Schema-only (без LLM/RAG, для CI):

```bash
cd backend
python -m pytest -q tests/test_ru_dd_schema_eval.py
```

Full tabular smoke (нужны DB + embeddings + LLM):

```bash
cd backend
python scripts/ru_dd_schema_tabular_smoke.py --pack lease
python scripts/ru_dd_schema_tabular_smoke.py --pack supply
python scripts/ru_dd_schema_tabular_smoke.py --pack services
```

## Как расширять

1. Положить OCR/text в `raw_text/` (или указать `text_path` на существующий файл).
2. Добавить документ в `gold.json` + ответы по `field_id`.
3. Цель: 20–30 договоров × ~10–15 колонок на pack.
