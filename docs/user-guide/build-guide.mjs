#!/usr/bin/env node
/**
 * Build lawyer onboarding PDF with live UI screenshots.
 * Usage:
 *   LOGIN_EMAIL=... LOGIN_PASSWORD=... node docs/user-guide/build-guide.mjs
 */
import { chromium } from 'playwright'
import { mkdir, readFile, writeFile, access } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ASSETS = path.join(__dirname, 'assets')
const OUT_HTML = path.join(__dirname, 'guide.html')
const OUT_PDF = path.join(__dirname, '..', 'Legal-AI-Vault-instrukciya-yurist.pdf')

const BASE = process.env.GUIDE_BASE_URL || 'http://127.0.0.1:5173'
const API = process.env.GUIDE_API_URL || 'http://127.0.0.1:8000'
const EMAIL = process.env.LOGIN_EMAIL || ''
const PASSWORD = process.env.LOGIN_PASSWORD || ''
const SAMPLE_PDF =
  process.env.GUIDE_SAMPLE_PDF ||
  '/Users/semyon_andronov04/Downloads/funds_movement.pdf'

const BUILTIN_COLUMNS = [
  {
    column_label: 'Тип документа',
    column_type: 'text',
    prompt:
      'Определи тип и категорию этого юридического документа по содержанию и структуре (кратко, на русском).',
  },
  {
    column_label: 'Краткое содержание',
    column_type: 'text',
    prompt: 'Кратко опиши предмет и суть документа в 1–2 предложениях.',
  },
]

async function shot(page, name, opts = {}) {
  const file = path.join(ASSETS, `${name}.png`)
  await page.screenshot({ path: file, fullPage: false, ...opts })
  return `assets/${name}.png`
}

async function apiFetch(pathname, { method = 'GET', token, body, formData } = {}) {
  const headers = {}
  if (token) headers['X-Access-Token'] = token
  if (body && !formData) headers['Content-Type'] = 'application/json'
  const res = await fetch(`${API}${pathname}`, {
    method,
    headers,
    body: formData || (body ? JSON.stringify(body) : undefined),
  })
  const text = await res.text()
  let data
  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    data = { raw: text }
  }
  if (!res.ok) {
    throw new Error(`API ${method} ${pathname} → ${res.status}: ${text.slice(0, 300)}`)
  }
  return data
}

async function loginApi() {
  const data = await apiFetch('/api/auth/login', {
    method: 'POST',
    body: { email: EMAIL, password: PASSWORD },
  })
  if (!data.access_token) throw new Error('No access_token from login')
  return data.access_token
}

async function waitForFilesReady(token, caseId, maxMs = 180000) {
  const started = Date.now()
  while (Date.now() - started < maxMs) {
    const st = await apiFetch(`/api/cases/${caseId}/processing-status`, { token })
    const files = st.files || st.documents || []
    const list = Array.isArray(files) ? files : []
    const pending = list.filter(
      (f) =>
        ['pending', 'processing', 'uploading', 'indexing'].includes(
          String(f.status || f.processing_status || '').toLowerCase(),
        ),
    )
    if (list.length > 0 && pending.length === 0) return list
    if (list.length === 0 && st.all_ready) return list
    await new Promise((r) => setTimeout(r, 3000))
  }
  console.warn('Processing wait timeout — continuing with partial index')
  return []
}

async function ensureDemoCase(token) {
  const listRaw = await apiFetch('/api/cases/?skip=0&limit=10', { token })
  const cases = Array.isArray(listRaw) ? listRaw : listRaw.cases || []
  let caseId = cases[0]?.id
  if (!caseId) {
    const created = await apiFetch('/api/cases/', {
      method: 'POST',
      token,
      body: {
        title: 'Демо — А40-12345/2024 ООО Пример',
        description: 'Учебное дело для инструкции Legal AI Vault',
        case_type: 'other',
      },
    })
    caseId = created.id
    console.log('Created demo case:', caseId)
  }

  const files = await apiFetch(`/api/cases/${caseId}/files`, { token }).catch(() => ({ files: [] }))
  const hasFiles = (files.files || files.documents || []).length > 0

  if (!hasFiles) {
    try {
      await access(SAMPLE_PDF)
      const buf = await readFile(SAMPLE_PDF)
      const form = new FormData()
      form.append('files', new Blob([buf]), 'funds_movement.pdf')
      await apiFetch(`/api/cases/${caseId}/files`, {
        method: 'POST',
        token,
        formData: form,
      })
      console.log('Uploaded sample PDF')
      await waitForFilesReady(token, caseId)
    } catch (e) {
      console.warn('Sample PDF upload skipped:', e.message)
    }
  } else {
    console.log('Case already has files')
  }

  return caseId
}

async function ensureTabularReview(token, caseId) {
  const reviewsResp = await apiFetch(`/api/tabular-review/?case_id=${caseId}`, { token }).catch(() => ({
    reviews: [],
  }))
  let reviewId = reviewsResp?.reviews?.[0]?.id

  const fileList = await apiFetch(`/api/cases/${caseId}/files`, { token })
  const fileIds = (fileList.files || fileList.documents || []).map((f) => f.id).filter(Boolean)

  if (!reviewId) {
    const review = await apiFetch('/api/tabular-review/', {
      method: 'POST',
      token,
      body: {
        case_id: caseId,
        name: 'Обзор материалов дела',
        description: 'Демо-таблица для инструкции',
        selected_file_ids: fileIds.slice(0, 3),
      },
    })
    reviewId = review.id
    console.log('Created tabular review:', reviewId)
  }

  const table = await apiFetch(`/api/tabular-review/${reviewId}/table-data`, { token })
  const columns = table.columns || []
  if (columns.length === 0 && fileIds.length > 0) {
    await apiFetch(`/api/tabular-review/${reviewId}/columns/bulk`, {
      method: 'POST',
      token,
      body: { columns: BUILTIN_COLUMNS },
    })
  }

  const refreshed = await apiFetch(`/api/tabular-review/${reviewId}/table-data`, { token })
  const col = (refreshed.columns || [])[0]
  if (col?.id) {
    try {
      await apiFetch(`/api/tabular-review/${reviewId}/columns/${col.id}/run`, {
        method: 'POST',
        token,
        body: {},
      })
      console.log('Column extraction started, waiting…')
      for (let i = 0; i < 40; i++) {
        await new Promise((r) => setTimeout(r, 5000))
        const t = await apiFetch(`/api/tabular-review/${reviewId}/table-data`, { token })
        const rows = t.rows || []
        const filled = rows.some((r) =>
          Object.values(r.cells || {}).some(
            (c) => c?.cell_value && String(c.cell_value).trim() && c.status === 'completed',
          ),
        )
        if (filled) break
      }
    } catch (e) {
      console.warn('Column run:', e.message)
    }
  }

  return { reviewId, caseId }
}

async function captureScreenshots(browser, demo) {
  if (!EMAIL || !PASSWORD) {
    throw new Error('Set LOGIN_EMAIL and LOGIN_PASSWORD environment variables')
  }

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  })
  const page = await context.newPage()
  const images = {}
  const { caseId, reviewId } = demo

  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(600)
  images.login = await shot(page, '01-login')

  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Пароль').fill(PASSWORD)
  await page.getByRole('button', { name: /войти/i }).click()
  await page.waitForURL(/\/cases/, { timeout: 30000 })
  await page.waitForTimeout(1000)
  images.cases = await shot(page, '02-cases')

  const overviewUrl = `${BASE}/cases/${caseId}`
  await page.goto(overviewUrl, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  images.caseOverview = await shot(page, '03-case-overview')

  const docsSection = page.getByText(/документ|файл/i).first()
  if (await docsSection.count()) {
    await docsSection.scrollIntoViewIfNeeded().catch(() => {})
    await page.waitForTimeout(400)
  }
  images.upload = await shot(page, '04-upload')

  // Templates via hub on overview
  const tableCard = page.getByRole('button', { name: /^Таблица/i }).or(
    page.locator('button').filter({ hasText: /^Таблица/ }).first(),
  )
  if (await tableCard.count()) {
    await tableCard.click()
    await page.waitForTimeout(1200)
    const tplBtn = page.getByRole('button', { name: /шаблон|новая таблица/i }).first()
    if (await tplBtn.count()) {
      await tplBtn.click().catch(() => {})
    }
    await page.waitForTimeout(800)
    images.templates = await shot(page, '05-templates')
    await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(400)
  }

  if (reviewId) {
    await page.goto(`${BASE}/cases/${caseId}/tabular-review/${reviewId}`, {
      waitUntil: 'networkidle',
    })
    await page.waitForTimeout(2000)
    images.tabular = await shot(page, '06-tabular')

    const dataCell = page
      .locator('div[class*="cursor-pointer"], [data-citation-badge], button')
      .filter({ hasText: /.{4,}/ })
      .nth(3)
    await dataCell.click({ timeout: 8000 }).catch(async () => {
      await page.locator('div').filter({ hasText: /.{8,}/ }).nth(4).click({ timeout: 5000 }).catch(() => {})
    })
    await page.waitForTimeout(1800)
    if (await page.locator('.ws-side-panel, [class*="side-panel"]').count()) {
      images.tabularSource = await shot(page, '07-tabular-source')
    }

    const moreMenu = page.getByRole('button', { name: /ещё|more|действия/i }).first()
    if (await moreMenu.count()) {
      await moreMenu.click()
      await page.waitForTimeout(400)
    } else {
      await page.locator('button').filter({ has: page.locator('svg.lucide-ellipsis, svg.lucide-more-horizontal') }).first().click().catch(() => {})
      await page.waitForTimeout(400)
    }
    const exportItem = page.getByText(/^Экспорт$/).first()
    if (await exportItem.count()) {
      await exportItem.click()
      await page.waitForTimeout(900)
      images.export = await shot(page, '11-export')
      await page.keyboard.press('Escape').catch(() => {})
    } else {
      const exportBtn = page.getByRole('button', { name: /экспорт/i }).first()
      if (await exportBtn.count()) {
        await exportBtn.click()
        await page.waitForTimeout(900)
        images.export = await shot(page, '11-export')
        await page.keyboard.press('Escape').catch(() => {})
      }
    }

    const helpBtn = page.getByRole('button', { name: /справка|помощь|help/i }).first()
    if (!(await helpBtn.count())) {
      await page.locator('button').filter({ has: page.locator('svg') }).last().click().catch(() => {})
    }
    const menuHelp = page.getByText(/как пользоваться|справка/i).first()
    if (await menuHelp.count()) {
      await menuHelp.click().catch(() => {})
      await page.waitForTimeout(800)
      images.help = await shot(page, '12-help')
      await page.keyboard.press('Escape').catch(() => {})
    }
  }

  await page.goto(`${BASE}/cases/${caseId}/chat`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)

  const settingsBtn = page.getByRole('button', { name: /настройки/i }).first()
  if (await settingsBtn.count()) {
    await settingsBtn.click()
    await page.waitForTimeout(700)
    images.chatSettings = await shot(page, '09-assistant-settings')
    await page.keyboard.press('Escape').catch(() => {})
  }

  const input = page.locator('textarea').first()
  if (await input.count()) {
    await input.fill('Кратко опиши содержание загруженных документов в деле.')
    await page.getByRole('button', { name: /отправ|send|стрел/i }).last().click().catch(async () => {
      await page.keyboard.press('Enter')
    })
    for (let i = 0; i < 60; i++) {
      await page.waitForTimeout(2000)
      const cite = page.locator('.inline-citation-badge, [data-citation-id], .citation-badge').first()
      const assistantText = page.locator('.ws-chat-messages, [class*="message"]').filter({ hasText: /.{40,}/ })
      if ((await cite.count()) || (await assistantText.count() > 2)) break
    }
    images.chat = await shot(page, '08-assistant')
    const cite = page.locator('[data-citation-badge], .inline-citation-badge, .citation-badge, button[data-citation-id]').first()
    if (await cite.count()) {
      await cite.click()
      await page.waitForTimeout(1800)
      images.chatSource = await shot(page, '10-assistant-source')
    }
  } else {
    images.chat = await shot(page, '08-assistant')
  }

  await context.close()
  return images
}

async function loadExistingImages() {
  const { readdir } = await import('node:fs/promises')
  const files = await readdir(ASSETS)
  const map = {
    '01-login.png': 'login',
    '02-cases.png': 'cases',
    '03-case-overview.png': 'caseOverview',
    '04-upload.png': 'upload',
    '05-templates.png': 'templates',
    '06-tabular.png': 'tabular',
    '07-tabular-source.png': 'tabularSource',
    '08-assistant.png': 'chat',
    '09-assistant-settings.png': 'chatSettings',
    '10-assistant-source.png': 'chatSource',
    '11-export.png': 'export',
    '12-help.png': 'help',
  }
  const images = {}
  for (const f of files) {
    const key = map[f]
    if (key) images[key] = `assets/${f}`
  }
  return images
}

function buildHtml(images) {
  const img = (key, alt) =>
    images[key]
      ? `<figure class="shot"><img src="${images[key]}" alt="${alt}" /><figcaption>${alt}</figcaption></figure>`
      : ''

  return `<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>Legal AI Vault — инструкция для юристов</title>
  <style>
    @page { size: A4; margin: 18mm 16mm 20mm 16mm; }
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      font-size: 10.5pt;
      line-height: 1.55;
      color: #1a1a1a;
      margin: 0;
    }
    .cover {
      min-height: 90vh;
      display: flex;
      flex-direction: column;
      justify-content: center;
      padding: 48px 8px;
      page-break-after: always;
      border-bottom: 3px solid #111;
    }
    .cover h1 {
      font-family: Georgia, serif;
      font-size: 32pt;
      font-weight: 400;
      margin: 0 0 8px;
    }
    .cover .subtitle { font-size: 14pt; color: #444; margin-bottom: 32px; }
    .cover .tagline {
      font-size: 11pt;
      max-width: 520px;
      border-left: 3px solid #2563eb;
      padding-left: 16px;
      color: #333;
    }
    .meta { margin-top: 48px; font-size: 9pt; color: #666; }
    h2 {
      font-family: Georgia, serif;
      font-size: 17pt;
      font-weight: 400;
      margin: 28px 0 12px;
      padding-bottom: 6px;
      border-bottom: 1px solid #e5e5e5;
      page-break-after: avoid;
    }
    h3 { font-size: 11pt; font-weight: 600; margin: 18px 0 8px; }
    p { margin: 0 0 10px; }
    .page { page-break-after: always; padding-top: 4px; }
    .page:last-child { page-break-after: auto; }
    ul, ol { margin: 0 0 12px; padding-left: 20px; }
    li { margin-bottom: 5px; }
    table { width: 100%; border-collapse: collapse; margin: 12px 0 16px; font-size: 9.5pt; }
    th, td { border: 1px solid #ddd; padding: 8px 10px; text-align: left; vertical-align: top; }
    th { background: #f8f7f5; font-weight: 600; }
    .callout {
      background: #f8f7f5;
      border: 1px solid #e8e6e3;
      border-radius: 8px;
      padding: 12px 14px;
      margin: 14px 0;
    }
    .callout.warn { background: #fffbeb; border-color: #fcd34d; }
    .rule-box {
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      border-radius: 8px;
      padding: 14px 16px;
      margin: 14px 0;
      font-family: ui-monospace, monospace;
      font-size: 9.5pt;
      line-height: 1.7;
      white-space: pre-line;
    }
    .shot { margin: 14px 0 18px; page-break-inside: avoid; }
    .shot img { width: 100%; border: 1px solid #e5e5e5; border-radius: 8px; display: block; }
    .shot figcaption { font-size: 8.5pt; color: #666; margin-top: 6px; text-align: center; }
    .checklist li { list-style: none; margin-left: -20px; }
    .checklist li::before { content: "☐ "; }
    .memo {
      border: 2px solid #111;
      border-radius: 10px;
      padding: 16px 18px;
      margin-top: 16px;
      page-break-inside: avoid;
    }
    .footer-note { font-size: 8.5pt; color: #888; margin-top: 24px; padding-top: 12px; border-top: 1px solid #eee; }
  </style>
</head>
<body>
  <section class="cover">
    <h1>Legal AI Vault</h1>
    <p class="subtitle">Инструкция для юристов по банкротству юридических лиц</p>
    <p class="tagline">Массовый разбор документов в таблице, вопросы к файлам дела в чате,
    справочник 127‑ФЗ и судебная практика — с проверкой по источнику.</p>
    <p class="meta">Версия 1.0 · ${new Date().toLocaleDateString('ru-RU')}</p>
  </section>

  <section class="page">
    <h2>1. Зачем нужна платформа</h2>
    <p><strong>Legal AI Vault</strong> — рабочее место по конкретному делу. Вы загружаете PDF и DOCX,
    система индексирует их и помогает находить ответы <em>в ваших документах</em>.</p>
    <table>
      <tr><th>Обычный ИИ-чат</th><th>Legal AI Vault</th></tr>
      <tr><td>Не видит файлы дела</td><td>Работает с <strong>вашими документами</strong></td></tr>
      <tr><td>Нет сводной таблицы</td><td><strong>Таблица</strong>: один вопрос — ко всем PDF</td></tr>
      <tr><td>Нет проверки</td><td><strong>Цитата</strong> → фрагмент в документе</td></tr>
    </table>
    <div class="callout warn"><strong>Важно:</strong> ответы ИИ всегда проверяйте по источнику.</div>
    ${img('cases', 'Список дел')}
  </section>

  <section class="page">
    <h2>2. Вход и навигация</h2>
    <ol>
      <li>Откройте адрес сервиса (выдаёт администратор фирмы).</li>
      <li>Войдите по email и паролю.</li>
      <li>Выберите дело или создайте новое.</li>
    </ol>
    ${img('login', 'Страница входа')}
    <table>
      <tr><th>Раздел</th><th>Где</th><th>Для чего</th></tr>
      <tr><td>Дела</td><td>Боковое меню</td><td>Список проектов</td></tr>
      <tr><td>Дело</td><td>Клик по названию</td><td>Документы и старт</td></tr>
      <tr><td>Ассистент</td><td>Внутри дела</td><td>Чат по материалам</td></tr>
      <tr><td>Таблица</td><td>Внутри дела</td><td>Массовый опрос файлов</td></tr>
    </table>
  </section>

  <section class="page">
    <h2>3. С чего начать</h2>
    <ol>
      <li>Создайте дело (название как в КАД).</li>
      <li>Загрузите PDF/DOCX — договоры, акты, выписки.</li>
      <li>Дождитесь индексации (1–5 мин).</li>
      <li>Выберите инструмент — таблица или чат.</li>
    </ol>
    ${img('caseOverview', 'Страница дела')}
    ${img('upload', 'Документы в деле')}
  </section>

  <section class="page">
    <h2>4. Когда что использовать</h2>
    <div class="rule-box">Много документов  →  <strong>ТАБЛИЦА</strong>
Один вопрос          →  <strong>АССИСТЕНТ</strong>
Суммы по выписке     →  <strong>АССИСТЕНТ</strong> (платежи, период)
127‑ФЗ               →  Ассистент + <strong>Справочник</strong>
Практика судов       →  Ассистент + <strong>Суд. практика</strong></div>
  </section>

  <section class="page">
    <h2>5. Таблица</h2>
    <ol>
      <li>Дело → <strong>Таблица</strong> → выберите <strong>шаблон</strong>.</li>
      <li>Отметьте документы → <strong>▶</strong> у колонки.</li>
      <li><strong>Клик по ячейке</strong> — документ и цитата справа.</li>
      <li><strong>Экспорт</strong> в Excel при необходимости.</li>
    </ol>
    ${img('templates', 'Шаблоны таблицы для банкротства')}
    ${img('tabular', 'Заполненная таблица')}
    ${img('tabularSource', 'Проверка по источнику')}
    ${img('export', 'Экспорт таблицы')}
    ${img('help', 'Справка по таблице')}
  </section>

  <section class="page">
    <h2>6. Ассистент (чат)</h2>
    <ol>
      <li>Задайте конкретный вопрос по делу.</li>
      <li>Включите <strong>Справочник</strong> или <strong>Суд. практика</strong> при необходимости.</li>
      <li>Кликните <strong>цитату</strong> в ответе.</li>
    </ol>
    ${img('chatSettings', 'Настройки: Справочник и Суд. практика')}
    ${img('chat', 'Ответ ассистента')}
    ${img('chatSource', 'Документ по цитате')}
  </section>

  <section class="page">
    <h2>7. Выписки</h2>
    <p>Загрузите выписку и спрашивайте про <strong>суммы и периоды</strong>:</p>
    <ul>
      <li>«Все платежи на [контрагент] за 2023 год»</li>
      <li>«Общая сумма исходящих переводов»</li>
    </ul>
    <p>Шаблон таблицы: <strong>Платежи и расчёты</strong>.</p>
  </section>

  <section class="page">
    <h2>8. Сценарий на 30 минут</h2>
    <ul class="checklist">
      <li>Создать дело, загрузить материалы</li>
      <li>Таблица → «Обзор документов дела» → ▶</li>
      <li>Проверить 3 ячейки по источнику</li>
      <li>Чат: вопрос по документам</li>
      <li>Экспорт в Excel</li>
    </ul>
    <div class="memo">
      <h3>Памятка</h3>
      <p><strong>Таблица</strong> — много файлов. <strong>Чат</strong> — один вопрос.
      <strong>Выписка</strong> — суммы. <strong>Всегда</strong> — клик по цитате.</p>
    </div>
    <p class="footer-note">Legal AI Vault · Доступ выдаёт администратор фирмы.</p>
  </section>
</body>
</html>`
}

async function main() {
  await mkdir(ASSETS, { recursive: true })

  let demo = {
    caseId: process.env.GUIDE_CASE_ID || '',
    reviewId: process.env.GUIDE_REVIEW_ID || '',
  }

  if (!process.env.SKIP_SETUP) {
    const token = await loginApi()
    const caseId = await ensureDemoCase(token)
    demo = await ensureTabularReview(token, caseId)
    console.log('Demo ready:', demo)
  } else if (!demo.caseId) {
    const token = await loginApi()
    const listRaw = await apiFetch('/api/cases/?skip=0&limit=5', { token })
    const cases = Array.isArray(listRaw) ? listRaw : listRaw.cases || []
    demo.caseId = cases[0]?.id || ''
    const reviewsResp = await apiFetch(`/api/tabular-review/?case_id=${demo.caseId}`, { token }).catch(() => ({
      reviews: [],
    }))
    demo.reviewId = reviewsResp.reviews?.[0]?.id || ''
  }

  const browser = await chromium.launch({
    headless: true,
    channel: process.env.PW_CHANNEL || 'chrome',
  })

  let images = {}
  if (process.env.SKIP_CAPTURE) {
    images = await loadExistingImages()
    console.log('Loaded assets:', Object.keys(images).join(', '))
  } else {
    try {
      images = await captureScreenshots(browser, demo)
      console.log('Screenshots:', Object.keys(images).join(', '))
    } catch (err) {
      console.warn('Capture error:', err.message)
      images = await loadExistingImages()
    }
  }

  const html = buildHtml(images)
  await writeFile(OUT_HTML, html, 'utf8')

  const page = await browser.newPage()
  await page.goto(`file://${OUT_HTML}`, { waitUntil: 'networkidle' })
  await page.pdf({
    path: OUT_PDF,
    format: 'A4',
    printBackground: true,
    margin: { top: '0', right: '0', bottom: '0', left: '0' },
  })
  await browser.close()

  console.log('PDF:', OUT_PDF)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
