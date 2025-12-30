# План интеграции AI Elements в проект

## Обзор

AI Elements от Vercel предоставляет готовые React-компоненты для визуализации:
- **Conversation** - беседы и сообщения
- **Reasoning** - цепочки рассуждений агентов
- **Tool** - вызовы инструментов (tool calls)
- **Response** - ответы и результаты

## Текущее состояние

- ✅ shadcn/ui уже настроен в проекте
- ✅ Есть компонент `EnhancedAgentStepsView` для визуализации шагов агентов
- ✅ Используется Tailwind CSS с CSS Variables
- ✅ Есть компоненты для чата (`AssistantUIChat`)

## План интеграции

### Вариант 1: Установка через CLI (рекомендуется для новых компонентов)

```bash
# Установить только нужные компоненты без перезаписи существующих
npx ai-elements@latest add reasoning
npx ai-elements@latest add tool
npx ai-elements@latest add response
```

### Вариант 2: Ручная интеграция (для кастомизации)

Создать адаптированные компоненты на основе паттернов AI Elements:
- `ReasoningView` - для отображения рассуждений агентов
- `ToolCallView` - для отображения вызовов инструментов
- `AgentResponseView` - для отображения результатов

## Компоненты AI Elements

### 1. Reasoning Component
**Назначение:** Отображение цепочки рассуждений агента

**Особенности:**
- Коллапсируемые секции
- Подсветка синтаксиса для кода
- Анимации при появлении новых рассуждений
- Интеграция с shadcn/ui компонентами (Accordion, Card)

**Использование:**
```tsx
<Reasoning>
  <ReasoningStep>
    Анализирую документ для извлечения временной шкалы...
  </ReasoningStep>
</Reasoning>
```

### 2. Tool Component
**Назначение:** Отображение вызовов инструментов (tool calls)

**Особенности:**
- Показ входных параметров
- Показ результатов выполнения
- Статусы выполнения (pending, running, completed, error)
- Форматирование JSON

**Использование:**
```tsx
<Tool name="extract_timeline" status="completed">
  <ToolInput>{inputData}</ToolInput>
  <ToolOutput>{outputData}</ToolOutput>
</Tool>
```

### 3. Response Component
**Назначение:** Отображение ответов и результатов

**Особенности:**
- Форматирование Markdown
- Подсветка кода
- Цитаты и источники
- Интерактивные элементы

**Использование:**
```tsx
<Response>
  <ResponseContent>
    {markdownContent}
  </ResponseContent>
  <ResponseSources sources={sources} />
</Response>
```

### 4. Conversation Component
**Назначение:** Управление беседой и сообщениями

**Особенности:**
- Структурированные сообщения
- Интеграция с Reasoning, Tool, Response
- Автоскролл
- История сообщений

## Интеграция с существующим кодом

### Текущая структура:
```
AssistantUIChat.tsx
  └── EnhancedAgentStepsView.tsx
      ├── Reasoning (встроено)
      ├── Tool Calls (встроено)
      └── Results (встроено)
```

### После интеграции AI Elements:
```
AssistantUIChat.tsx
  ├── Conversation (AI Elements)
  │   ├── Message (AI Elements)
  │   │   ├── Reasoning (AI Elements)
  │   │   ├── Tool (AI Elements)
  │   │   └── Response (AI Elements)
  └── EnhancedAgentStepsView.tsx (обновлен для использования AI Elements)
```

## Преимущества использования AI Elements

1. **Готовые компоненты** - не нужно писать с нуля
2. **Интеграция с shadcn/ui** - единый стиль
3. **Доступность** - компоненты соответствуют стандартам a11y
4. **Кастомизация** - можно изменять исходный код
5. **Активное развитие** - поддержка от Vercel

## Шаги реализации

1. ✅ Изучить структуру AI Elements
2. ⏳ Установить необходимые компоненты
3. ⏳ Адаптировать под текущую структуру данных
4. ⏳ Интегрировать с `EnhancedAgentStepsView`
5. ⏳ Обновить `AssistantUIChat` для использования новых компонентов
6. ⏳ Протестировать визуализацию цепочки действий

## Примеры использования

### Отображение рассуждений агента:
```tsx
import { Reasoning, ReasoningStep } from "@/components/ai-elements/reasoning"

<Reasoning>
  {agentSteps.map(step => (
    <ReasoningStep key={step.step_id} status={step.status}>
      {step.reasoning}
    </ReasoningStep>
  ))}
</Reasoning>
```

### Отображение вызовов инструментов:
```tsx
import { Tool, ToolInput, ToolOutput } from "@/components/ai-elements/tool"

<Tool name={toolCall.name} status={toolCall.status}>
  <ToolInput>{JSON.stringify(toolCall.input, null, 2)}</ToolInput>
  <ToolOutput>{JSON.stringify(toolCall.output, null, 2)}</ToolOutput>
</Tool>
```

## Ссылки

- [AI Elements GitHub](https://github.com/vercel/ai-elements)
- [Vercel Blog: Introducing AI Elements](https://vercel.com/blog/introducing-ai-elements)
- [shadcn/ui Documentation](https://ui.shadcn.com/)

