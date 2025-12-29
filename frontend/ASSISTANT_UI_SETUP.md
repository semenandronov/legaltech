# Assistant UI Chat Setup

## Что было сделано

1. ✅ Установлен пакет `@assistant-ui/react`
2. ✅ Создан API endpoint `/api/chat` для streaming (SSE)
3. ✅ Создан компонент `AssistantUIChat` 
4. ✅ Создана страница `AssistantChatPage`
5. ✅ Интегрирован в роутинг (`/cases/:caseId/chat`)

## Использование

Чат доступен по адресу: `/cases/:caseId/chat`

Компонент автоматически:
- Подключается к API endpoint `/api/chat`
- Отправляет `case_id` в body запроса
- Использует JWT токен из localStorage
- Поддерживает streaming ответов (SSE)

## API Endpoint

**POST** `/api/chat`

**Request Body:**
```json
{
  "case_id": "string",
  "messages": [
    {
      "role": "user",
      "content": "Вопрос пользователя"
    }
  ]
}
```

**Response:** Server-Sent Events (SSE) stream
```
data: {"textDelta": "часть ответа"}
data: {"textDelta": "еще часть"}
data: {"textDelta": ""}  // Пустой textDelta = конец потока
```

## Компоненты

### AssistantUIChat
Основной компонент чата с assistant-ui:
- Использует `useChat` hook из `@assistant-ui/react`
- Автоматическая прокрутка
- Индикатор загрузки
- Обработка ошибок

### AssistantChatPage
Страница-обертка для чата:
- Интегрирована в MainLayout
- Получает `caseId` из URL параметров
- Передает в `AssistantUIChat`

## Настройка

### Изменение API endpoint
В `AssistantUIChat.tsx`:
```typescript
api: getApiUrl('/api/chat'),  // Изменить путь здесь
```

### Кастомизация стилей
Компонент использует Tailwind CSS классы. Можно изменить в `AssistantUIChat.tsx`.

## Troubleshooting

### Чат не отправляет сообщения
- Проверьте, что `caseId` передается корректно
- Проверьте JWT токен в localStorage
- Проверьте консоль браузера на ошибки

### Streaming не работает
- Проверьте, что endpoint возвращает `text/event-stream`
- Проверьте формат SSE (должен быть `data: {...}\n\n`)
- Проверьте CORS настройки

### Ошибки в консоли
- Убедитесь, что `@assistant-ui/react` установлен
- Проверьте версию React (требуется 18+)


