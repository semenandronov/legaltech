# Руководство по тестированию улучшений чата

## Что было реализовано

1. **Reasoning Streaming** - показ процесса "мышления" ИИ
2. **Workflow Templates** - готовые сценарии работы
3. **Smart Suggestions** - умные подсказки на основе контекста
4. **Enhanced Citations** - кликабельные ссылки с координатами
5. **Split View** - документ и чат рядом (компонент готов)

## Инструкции по тестированию

### 1. Reasoning Streaming (Показ процесса мышления)

**Как проверить:**
1. Запустите backend и frontend
2. Откройте страницу чата для любого дела
3. Задайте сложный вопрос, например:
   - "Проанализируй все договоры в деле"
   - "Какие риски есть в документах?"
   - "Найди противоречия между документами"
4. Во время генерации ответа проверьте:
   - В консоли браузера должны появляться события типа `reasoning`
   - Сообщения должны содержать поле `reasoningSteps` с фазами:
     - `understanding` - анализ запроса
     - `planning` - создание плана
     - `executing` - выполнение анализа
     - `delivering` - формирование ответа

**Где смотреть:**
- DevTools → Network → SSE события
- Console → логи с типом "reasoning"
- State сообщений в React DevTools

**Ожидаемый результат:**
В структуре сообщения должны быть `reasoningSteps` с массивом объектов:
```javascript
{
  phase: "understanding",
  step: 1,
  totalSteps: 4,
  content: "Анализирую запрос..."
}
```

### 2. Workflow Templates (Готовые сценарии)

**Как проверить:**

**Backend:**
```bash
# Проверить endpoint
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/cases/{case_id}/workflow-templates
```

**Frontend:**
1. На странице чата добавьте компонент `WorkflowTemplateSelector`
2. Должны отображаться шаблоны:
   - Due Diligence
   - Анализ договора
   - Подготовка к судебному процессу
   - Анализ сущностей
   - Оценка рисков
3. При клике на шаблон должен запускаться workflow

**Ожидаемый результат:**
- Endpoint возвращает массив шаблонов
- Каждый шаблон содержит: id, name, description, steps, estimated_time
- Шаги с `requires_approval: true` останавливают выполнение для одобрения

### 3. Smart Suggestions (Умные подсказки)

**Как проверить:**

**Backend:**
```bash
# Получить подсказки для дела
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8000/api/cases/{case_id}/suggestions?limit=5"
```

**Frontend:**
1. Добавьте компонент `SmartSuggestions` на страницу чата
2. Компонент должен загрузить подсказки при монтировании
3. Подсказки должны быть релевантны типу дела и документам

**Ожидаемый результат:**
- Endpoint возвращает массив подсказок (до 5)
- Каждая подсказка содержит: id, text, type, confidence
- Типы: 'question', 'action', 'analysis'
- При клике на подсказку она используется как запрос

**Пример использования:**
```tsx
<SmartSuggestions
  caseId={caseId}
  onSuggestionClick={(suggestion) => {
    // Использовать suggestion как запрос
    sendMessage(suggestion)
  }}
/>
```

### 4. Enhanced Citations (Кликабельные ссылки)

**Как проверить:**
1. Задайте вопрос, требующий ответа с источниками
2. В ответе должны быть ссылки вида [1], [2], [3]
3. При наведении/клике на ссылку должна показываться карточка с:
   - Именем файла
   - Номером страницы
   - Позицией (char_start - char_end)
   - Цитатой из документа
   - Контекстом до/после

**Ожидаемый результат:**
- Ссылки кликабельны
- Карточка показывает полную информацию
- При клике можно открыть документ (если интегрировано)

**Проверка данных:**
В `SourceInfo` должны быть поля:
- `char_start`, `char_end` - координаты
- `quote` - точная цитата
- `context_before`, `context_after` - контекст

### 5. Split View Layout (Документ и чат рядом)

**Как проверить:**
Компонент `SplitViewLayout` готов, но требует интеграции в `AssistantChatPage`.

**Пример интеграции:**
```tsx
import { SplitViewLayout } from '@/components/Chat/SplitViewLayout'
import DocumentViewer from '@/components/Documents/DocumentViewer'

// В AssistantChatPage:
<SplitViewLayout
  leftPanel={<AssistantUIChat caseId={caseId} />}
  rightPanel={
    <DocumentViewer
      document={selectedDocument}
      caseId={caseId}
    />
  }
  defaultSizes={[60, 40]}
/>
```

**Ожидаемый результат:**
- Две панели рядом
- Возможность изменения размера панелей
- Разделитель с ручкой для ресайза

### 6. Document Highlighter (Подсветка цитат)

**Как проверить:**
Компонент `DocumentHighlighter` готов к использованию.

**Пример использования:**
```tsx
import { DocumentHighlighter } from '@/components/Documents/DocumentHighlighter'

<DocumentHighlighter
  text={documentText}
  highlights={[
    {
      char_start: 100,
      char_end: 200,
      color: '#fef08a',
      id: 'citation-1'
    }
  ]}
/>
```

**Ожидаемый результат:**
- Текст подсвечивается по указанным координатам
- Поддержка множественных подсветок
- Настраиваемый цвет

## Комплексное тестирование

### Сценарий 1: Полный workflow с reasoning

1. Откройте дело с документами
2. Задайте сложный вопрос
3. Наблюдайте reasoning steps в консоли
4. Получите ответ с citations
5. Кликните на citation
6. Проверьте отображение координат и цитаты

### Сценарий 2: Workflow template

1. Откройте WorkflowTemplateSelector
2. Выберите "Due Diligence"
3. Запустите workflow
4. На шагах с `requires_approval: true` должно запрашиваться одобрение
5. После одобрения продолжается выполнение

### Сценарий 3: Smart Suggestions

1. Откройте дело
2. Подождите загрузки suggestions
3. Кликните на подсказку
4. Проверьте, что она используется как запрос

## Отладка

### Проверка backend логирования

```bash
# Смотрите логи reasoning
tail -f logs/app.log | grep -i reasoning

# Проверяйте события streaming
tail -f logs/app.log | grep -i "stream"
```

### Проверка frontend

1. Откройте DevTools → Network
2. Фильтр: EventSource или SSE
3. Проверьте события типа `reasoning`

### Проверка данных в БД

```sql
-- Проверка workflow templates (если сохранены в БД)
SELECT * FROM workflow_templates;

-- Проверка Store (если используется)
SELECT * FROM langgraph_store;
```

## Возможные проблемы

1. **Reasoning события не приходят:**
   - Проверьте, что backend использует `astream_events`
   - Проверьте логи на ошибки
   - Убедитесь, что `reasoning_steps` добавляются в state

2. **Workflow templates не загружаются:**
   - Проверьте endpoint `/api/cases/{case_id}/workflow-templates`
   - Проверьте авторизацию
   - Проверьте, что case_id корректный

3. **Suggestions пустые:**
   - Проверьте, что Store инициализирован
   - Проверьте логи suggestions_service
   - Попробуйте без контекста (базовые подсказки)

4. **Citations без координат:**
   - Убедитесь, что используется `generate_with_structured_citations`
   - Проверьте, что LLM возвращает структурированный ответ
   - Проверьте fallback на обычный метод

## Следующие шаги для полной интеграции

1. Интегрировать SplitViewLayout в AssistantChatPage
2. Добавить обработку клика по citation для открытия документа
3. Интегрировать DocumentHighlighter в DocumentViewer
4. Добавить UI для отображения reasoning steps (визуально)
5. Добавить обработку workflow approval в UI
6. Интегрировать SmartSuggestions на страницу чата

