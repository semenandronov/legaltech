# План реализации UX/UI для e-discovery согласно гайду

## Текущее состояние фронтенда

**Существующие компоненты:**
- `ChatWindow.tsx` - чат на отдельной странице (неправильно!)
- `AnalysisPage.tsx` - анализ на отдельной странице с табами
- `CaseSidebar.tsx` - простой список файлов
- Нет 3-panel layout
- Нет интеграции чата с просмотром документов
- Нет color coding для confidence
- Нет keyboard shortcuts
- Нет batch actions

**Проблемы:**
1. Чат в отдельной вкладке (должен быть ВСЕГДА видно справа!)
2. Нет единого рабочего пространства (3 панели)
3. Нет просмотра документов с highlighting сущностей
4. Нет фильтров по privilege/relevance/confidence
5. Нет batch actions
6. Нет keyboard shortcuts

## Целевая архитектура (согласно гайду)

```
┌─────────────────────────────────────────────────────────────┐
│ 🔙 [Matter: Альфа-Бета] | 🔍 Search | 📊 | ⚙️            │
├──────────────────────────┬──────────────────┬──────────────┤
│ 📋 DOCUMENTS (30%)       │ 📄 VIEWER (50%)  │ 💬 CHAT (20%)│
│ List + Filters           │ Main Panel       │ Sidebar      │
└──────────────────────────┴──────────────────┴──────────────┘
```

## Этап 1: Создание главной страницы с 3-panel layout

**Новые файлы:**
- `frontend/src/pages/CaseWorkspacePage.tsx` - главная страница работы с делом
- `frontend/src/components/Workspace/DocumentsPanel.tsx` - левая панель (30%)
- `frontend/src/components/Workspace/DocumentViewer.tsx` - центральная панель (50%)
- `frontend/src/components/Workspace/ChatPanel.tsx` - правая панель (20%, collapsible)
- `frontend/src/components/Workspace/WorkspaceLayout.tsx` - layout компонент

**Изменения:**

1. **Создать `CaseWorkspacePage.tsx`**:
   - Главная страница для работы с делом
   - Интегрирует все 3 панели
   - Управляет состоянием (выбранный документ, фильтры, чат)
   - Route: `/cases/:caseId/workspace`

2. **Создать `WorkspaceLayout.tsx`**:
   - CSS Grid layout: `grid-template-columns: 30% 50% 20%`
   - Responsive: на мобильных переходит в tabs
   - Поддержка collapse правой панели (чат)
   - Поддержка swap layout (left/right preference)

3. **Обновить routing в `App.tsx`**:
   - Добавить route `/cases/:caseId/workspace`
   - Сделать это главной страницей для работы с делом

## Этап 2: Левая панель - DocumentsPanel

**Новые файлы:**
- `frontend/src/components/Workspace/DocumentsPanel.tsx`
- `frontend/src/components/Workspace/DocumentFilters.tsx`
- `frontend/src/components/Workspace/DocumentListItem.tsx`
- `frontend/src/components/Workspace/OverviewCard.tsx` (collapsible)

**Функциональность:**

1. **Overview Card (collapsible)**:
   - Total, Relevant, Privileged, Not relevant
   - Processing time
   - Download Audit Log PDF

2. **Search Bar**:
   - Глобальный поиск по документам
   - Автокомплит с suggestions
   - Debounced input

3. **Sticky Filters**:
   - Type: [Контракт ▼] [Письмо] [Отчет]
   - Privilege: [Все] [Привилегирован] [Не привилегирован]
   - Relevance: Slider 0-100%
   - Confidence: [>95%] [80-95%] [<80%]
   - Status: [New] [Reviewed] [Flagged]
   - [✨ Clear All] [💾 Save as View]

4. **Documents List**:
   - Color-coded items (🟢 GREEN >90%, 🟡 YELLOW 60-90%, 🔴 RED <60%, 🔒 PURPLE privileged)
   - Иконки статуса: ⭐ Reviewed, 🔒 Withheld, ❌ Rejected, ✅ Confirmed
   - Показывать: filename, relevance %, confidence %, type, date
   - Click → открывает в центре
   - [☑ Select All] [☑ Select Visible]

5. **Batch Actions**:
   - [✅ Confirm All]
   - [❌ Reject All]
   - [🔒 Withhold All]
   - [🚀 Auto-Review]
   - [📤 Export Selected]

## Этап 3: Центральная панель - DocumentViewer

**Новые файлы:**
- `frontend/src/components/Workspace/DocumentViewer.tsx`
- `frontend/src/components/Workspace/DocumentHeader.tsx`
- `frontend/src/components/Workspace/AIAnalysisPanel.tsx` (sticky)
- `frontend/src/components/Workspace/EntityHighlighter.tsx`
- `frontend/src/components/Workspace/PDFViewer.tsx`

**Функциональность:**

1. **Document Header**: ← [DOC042 : Letter] | 🔍 Find | ⚙️

2. **Document Content**:
   - PDF viewer (react-pdf)
   - Text viewer с highlighting сущностей:
     - [Иван Петров] = Blue (PERSON)
     - [АО Бета] = Green (ORGANIZATION)
     - [15 января 2024] = Orange (DATE)
     - [5,000,000 руб] = Red (AMOUNT)

3. **AI Analysis Panel (sticky)**:
   - Тип, Релевантность, Привилегия с reasoning
   - Entities: PERSON, ORG, DATE, AMOUNT
   - Related Docs
   - Actions: [✅ Confirm] [❌ Reject] [🔒 Withhold] [➡️ Next] [⬅️ Previous]

4. **Navigation**: [← DOC042 →] - предыдущий/следующий документ

## Этап 4: Правая панель - ChatPanel (ВСЕГДА видно!)

**Новые файлы:**
- `frontend/src/components/Workspace/ChatPanel.tsx` (refactor ChatWindow)
- `frontend/src/components/Workspace/ChatMessage.tsx`
- `frontend/src/components/Workspace/QuickActions.tsx`
- `frontend/src/components/Workspace/ConfidenceBadge.tsx`

**Функциональность:**

1. **Chat Header**: 🤖 E-Discovery Assistant

2. **Quick Start**: [Classify All] [Find Privilege] [Timeline] [Statistics]

3. **Chat Messages**:
   - Confidence badge: 94% ✅ / 60% ⚠️ / 30% ❌
   - Citation links: "DOC042" кликабелен → открывает в центре
   - Document snippets с preview
   - Batch actions: [🔒 Withhold эти 28] [📋 Экспорт]
   - Charts для статистики

4. **Input Area**:
   - Автокомплит команд
   - Quick buttons: [Classify] [Privilege] [Timeline] [Stats]
   - Drag & drop PDF

## Этап 5: Color Coding System

**Новые файлы:**
- `frontend/src/styles/colors.css`
- `frontend/src/utils/colorCoding.ts`

**Цвета:**
```css
--color-safe: #10b981;      /* GREEN (>90%) */
--color-info: #3b82f6;      /* BLUE */
--color-caution: #f59e0b;   /* YELLOW (60-90%) */
--color-critical: #ef4444;  /* RED (<60%) */
--color-privileged: #a855f7; /* PURPLE */
```

## Этап 6: Keyboard Shortcuts (CRITICAL!)

**Новые файлы:**
- `frontend/src/hooks/useKeyboardShortcuts.ts`

**Shortcuts:**
```
→ / End = Next document
← / Home = Previous
y / a = Confirm
n = Reject
w = Withhold
: = Command palette
/ = Quick search
```

## Этап 7: Batch Actions

**Новые файлы:**
- `frontend/src/components/Workspace/BatchActionsBar.tsx`
- `frontend/src/hooks/useBatchSelection.ts`

**API endpoint (новый):**
- `POST /api/analysis/{case_id}/batch-action`

## Этап 8: Export & Compliance

**Новые файлы:**
- `frontend/src/components/Workspace/ExportModal.tsx`
- `frontend/src/components/Workspace/AuditLogViewer.tsx`

**Форматы:**
- REL format (для суда)
- PDF report (with bates nums)
- CSV, JSON, EDRM XML
- Audit log (REQUIRED!)

**API endpoints (новые):**
- `POST /api/analysis/{case_id}/export`
- `GET /api/analysis/{case_id}/audit-log`

## Этап 9: State Management

**Новые файлы:**
- `frontend/src/stores/workspaceStore.ts` (Zustand)
- `frontend/src/stores/documentStore.ts`
- `frontend/src/stores/chatStore.ts`

## Этап 10: API Integration

**Обновить `frontend/src/services/api.ts`:**

Новые функции:
- `getAnalysisReport()` - отчет с категоризацией
- `getClassifications()` - классификации
- `getEntities()` - сущности
- `getPrivilegeChecks()` - проверки привилегий
- `batchAction()` - batch actions
- `exportAnalysis()` - экспорт
- `getAuditLog()` - audit log

WebSocket для realtime updates.

## Этап 11: Mobile Version (iPad)

**Новые файлы:**
- `frontend/src/components/Workspace/MobileWorkspace.tsx`

**Layout для iPad:**
- 3 TABS: Documents List | Document Viewer | AI Chat
- Responsive breakpoints

## Приоритизация

**Week 1 (MVP):**
1. Этап 1: 3-panel layout
2. Этап 2: DocumentsPanel (базовая)
3. Этап 3: DocumentViewer (базовая)
4. Этап 4: ChatPanel (refactor)

**Week 2:**
5. Этап 5: Color Coding
6. Этап 6: Keyboard Shortcuts
7. Этап 7: Batch Actions
8. Этап 9: State Management

**Week 3:**
9. Этап 8: Export & Compliance
10. Этап 10: API Integration
11. Этап 11: Mobile Version
12. Advanced Features

## Технический стек

- TailwindCSS + shadcn/ui
- Zustand (state)
- TanStack Query (async)
- Socket.io (realtime)
- react-pdf (PDF viewer)
- React Flow (timeline)

## Критичные моменты

1. Чат ВСЕГДА видно - не в отдельной вкладке!
2. Keyboard first - работа без мыши
3. Batch actions - выделить 50 → одна кнопка
4. Color coding - мгновенное понимание
5. Confidence scores - всегда показывать
6. Export compliance - REL + audit log
7. Explanation always - почему AI решило
