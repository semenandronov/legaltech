# Шаблоны Draft

Системные шаблоны банкротства: **docxtpl** (`.docx` + `{{ variable }}`).

## Структура

| Файл | Назначение |
|------|------------|
| `manifest.json` | id, engine, file, variables[], intent_keywords |
| `sources/*.txt` | Исходный текст шаблонов с `{{ переменными }}` |
| `*.docx` | Word-шаблоны для docxtpl |
| `bankruptcy_field_catalog.py` | Вопросы для LLM (Field description) |

## Сборка DOCX из sources

```bash
cd backend
pip install docxtpl jinja2
python3 scripts/build_bankruptcy_docxtpl_templates.py
```

## Индексация

```bash
cd backend
python3 -m scripts.index_draft_templates
```

## Добавить новый шаблон

1. Добавьте `sources/my_template.txt` с `{{ variable }}`.
2. Запустите build-скрипт или положите `.docx` вручную.
3. Добавьте запись в `manifest.json` с `engine: "docxtpl"` и `variables: [...]`.
4. Добавьте описания переменных в `app/services/bankruptcy_field_catalog.py`.
5. Проиндексируйте.

## Как работает fill

1. Автоподбор шаблона по `intent_keywords`.
2. LLM (structured output) заполняет JSON по переменным из каталога.
3. docxtpl рендерит `.docx` → HTML в редактор.
