# Skill Format Documentation

## Обзор

Документация по формату навыков (skills) для агентов в системе. Навыки позволяют стандартизировать создание и управление агентами.

## Компоненты

### 1. Skill Registry (`skill_registry.py`)

Реестр навыков для регистрации и управления.

```python
from app.services.langchain_agents.skill_registry import get_skill_registry, SkillStatus

registry = get_skill_registry()

# Регистрация навыка
metadata = registry.register(
    name="compliance_check",
    description="Проверка соответствия требованиям",
    version="1.0.0",
    author="system",
    status=SkillStatus.ACTIVE,
    tags=["compliance", "legal"],
    dependencies=["document_classifier"],
    agent_type="analysis",
    tools=["retrieve_documents", "web_research"]
)

# Поиск навыков
results = registry.search(query="compliance", tags=["legal"])
```

### 2. Skill Template (`skill_template.py`)

Шаблон для создания навыков.

```python
from app.services.langchain_agents.skill_template import SkillTemplate, SkillTemplateBuilder

# Использование builder
template = (SkillTemplateBuilder()
    .with_name("compliance_check")
    .with_description("Проверка соответствия требованиям")
    .with_agent_type("analysis")
    .with_system_prompt("You are a compliance checker...")
    .with_tools("retrieve_documents", "web_research")
    .build())
```

### 3. Skill Creator (`skill_creator.py`)

Генератор кода для навыков из шаблонов.

```python
from app.services.langchain_agents.skill_creator import SkillCreator

creator = SkillCreator()
result = creator.create_skill(
    template,
    generate_code=True,
    register=True
)
```

### 4. CLI Utility (`scripts/create_skill.py`)

Интерактивное создание навыков через CLI.

```bash
# Интерактивное создание
python backend/scripts/create_skill.py

# Создание из JSON
python backend/scripts/create_skill.py --template skill.json
```

## Формат Skill Template

JSON формат для шаблона навыка:

```json
{
    "name": "compliance_check",
    "description": "Проверка соответствия требованиям",
    "version": "1.0.0",
    "author": "system",
    "status": "active",
    "tags": ["compliance", "legal"],
    "dependencies": ["document_classifier"],
    "agent_type": "analysis",
    "tools": ["retrieve_documents", "web_research"],
    "system_prompt": "You are a compliance checker...",
    "prompt_template": "",
    "node_function_template": "...",
    "agent_factory_config": {},
    "metadata": {}
}
```

## Статусы навыков

- `active` - Активный навык
- `experimental` - Экспериментальный
- `deprecated` - Устаревший
- `disabled` - Отключен

## Интеграция с существующими агентами

Существующие агенты могут быть стандартизированы через SkillTemplate для единообразия и управления через реестр.

