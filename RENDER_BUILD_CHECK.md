# Проверка сборки на Render

## Проблема: 404 на всех страницах

Если все страницы возвращают 404, это может означать:

1. **Проблема со сборкой** - страницы не собрались правильно
2. **Проблема с роутингом** - Next.js не видит страницы
3. **Проблема с конфигурацией** - что-то не так с настройками

## Что проверить на Render:

### 1. Проверьте логи сборки (Build Logs)

1. Откройте ваш сервис на Render
2. Перейдите в раздел **"Logs"**
3. Найдите логи сборки (build logs) - они должны быть в начале
4. Проверьте, нет ли ошибок при сборке страниц

**Ищите строки типа:**
```
✓ Compiled successfully
✓ Linting and checking validity of types
✓ Collecting page data
✓ Generating static pages
```

**Если есть ошибки** - исправьте их.

### 2. Проверьте, что все страницы собрались

В логах сборки должны быть строки:
```
Route (app)                              Size     First Load JS
┌ ○ /                                    ... kB   ... kB
├ ○ /login                               ... kB   ... kB
├ ○ /register                            ... kB   ... kB
├ ○ /dashboard                           ... kB   ... kB
├ ○ /dashboard/summarize                 ... kB   ... kB
├ ○ /dashboard/ediscovery                ... kB   ... kB
├ ○ /dashboard/timeline                  ... kB   ... kB
├ ○ /dashboard/chat                      ... kB   ... kB
└ ○ /dashboard/tabular                   ... kB   ... kB
```

Если какой-то страницы нет в списке - значит она не собралась.

### 3. Проверьте переменные окружения

Убедитесь, что установлены:
- `DATABASE_URL`
- `NEXTAUTH_URL` = `https://legaltech-ynit.onrender.com`
- `NEXTAUTH_SECRET`

### 4. Попробуйте тестовую страницу

После деплоя попробуйте открыть:
- `https://legaltech-ynit.onrender.com/test`

Если эта страница работает, значит роутинг работает, но проблема в других страницах.

### 5. Очистите кэш и пересоберите

1. На Render откройте Settings
2. Нажмите "Clear build cache"
3. Перезапустите сервис (Manual Deploy)

## Если ничего не помогает:

Проверьте, что в логах нет ошибок типа:
- "Cannot find module"
- "Error: Page not found"
- "Failed to compile"

И отправьте полные логи сборки для анализа.

