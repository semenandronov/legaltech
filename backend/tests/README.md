# Tests for LangChain Agents

Этот каталог содержит тесты для мультиагентной системы LangChain.

## Структура тестов

- `test_agents_components.py` - Тесты базовых компонентов (State, Tools, Prompts, Supervisor)
- `test_graph.py` - Тесты создания и структуры графа
- `test_nodes.py` - Тесты отдельных узлов графа
- `test_coordinator.py` - Тесты AgentCoordinator
- `test_integration.py` - Интеграционные тесты с существующими сервисами
- `test_api_endpoints.py` - Тесты API endpoints
- `test_error_handling.py` - Тесты обработки ошибок
- `test_performance.py` - Тесты производительности
- `test_e2e.py` - End-to-end тесты

## Запуск тестов

```bash
# Установить pytest если еще не установлен
pip install pytest pytest-asyncio

# Запустить все тесты
pytest backend/tests/

# Запустить конкретный файл
pytest backend/tests/test_agents_components.py

# Запустить с подробным выводом
pytest backend/tests/ -v

# Запустить с покрытием кода
pytest backend/tests/ --cov=app.services.langchain_agents
```

## Примечания

- Некоторые тесты требуют реальных сервисов (БД, RAG, LLM) для полного выполнения
- Структурные тесты проверяют корректность структуры без выполнения
- Для полного E2E тестирования нужны тестовые данные и настроенное окружение
