# Исправление проблемы с RSC (React Server Components)

## Проблема:
Next.js пытается загрузить страницы как RSC с параметром `?_rsc=1qjny`, но получает 404.

## Причина:
В Next.js 15 все страницы по умолчанию являются Server Components, но наши страницы используют `"use client"`. Проблема может быть в том, что:
1. Страницы не собрались правильно
2. Next.js не видит их как клиентские компоненты
3. Проблема с роутингом в production

## Решение:

### 1. Убедитесь, что все страницы имеют "use client"
Все страницы в `app/(dashboard)/` должны начинаться с `"use client"`.

### 2. Проверьте сборку
На Render проверьте логи сборки - должны быть строки:
```
Route (app)                              Size     First Load JS
├ ○ /dashboard                           ... kB   ... kB
├ ○ /dashboard/summarize                 ... kB   ... kB
...
```

### 3. Если проблема сохраняется:
Попробуйте очистить кэш на Render:
1. Settings → Clear build cache
2. Manual Deploy

### 4. Альтернативное решение:
Если проблема не решается, можно попробовать добавить в `next.config.js`:
```js
experimental: {
  serverActions: {
    bodySizeLimit: '10mb',
  },
  // Отключить RSC для клиентских страниц
  serverComponentsExternalPackages: [],
}
```

Но это не рекомендуется, так как может вызвать другие проблемы.

## Проверка:
После исправления попробуйте открыть:
- `https://legaltech-ynit.onrender.com/dashboard`
- `https://legaltech-ynit.onrender.com/dashboard/summarize`

Ошибки `?_rsc=1qjny 404` должны исчезнуть.

