#!/usr/bin/env node
/**
 * PDF-инструкция для юристов по банкротству — 10 страниц по заданной структуре.
 * Usage: node docs/user-guide/build-lawyer-pdf.mjs
 */
import { writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT_HTML = path.join(__dirname, 'guide.html')
const OUT_PDF = path.join(__dirname, '..', 'Legal-AI-Vault-instrukciya-yurist.pdf')

const DATE = new Date().toLocaleDateString('ru-RU', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
})

const SHOTS = {
  newCase: 'assets/02-user.png',
  caseHome: 'assets/03-user.png',
  chatAnswer: 'assets/05-user.png',
  chatToggles: 'assets/06-user.png',
  tableStart: 'assets/07-user.png',
  tableEmpty: 'assets/08-user.png',
  tableColumn: 'assets/09-user.png',
  tableFilled: 'assets/10-user.png',
  cellDetail: 'assets/11-user.png',
  cellVerify: 'assets/12-user.png',
}

function img(src, alt = '') {
  return `<figure class="shot"><img src="${src}" alt="${alt}" /></figure>`
}

function page(num, title, body, screenshot = '') {
  return `<section class="page">
    <div class="page-head">
      <span class="page-num">${num}</span>
      <h2>${title}</h2>
    </div>
    <div class="page-body">${body}</div>
    ${screenshot}
  </section>`
}

function buildHtml() {
  const pages = [
    page(
      '1',
      'Что это за платформа',
      `<p><strong>Legal AI Vault</strong> — сервис для работы с документами конкретного дела. Вы загружаете файлы (PDF, Word, сканы), а система помогает по ним искать ответы.</p>
      <p><strong>Кому подходит:</strong> юристам и арбитражным управляющим, которые ведут дела о банкротстве юридических лиц — когда нужно разобрать пачку материалов: судебные акты, требования кредиторов, договоры, выписки, отчёты ФУ.</p>
      <p><strong>Два рабочих режима внутри дела:</strong></p>
      <ul>
        <li><strong>Ассистент</strong> — вы задаёте вопрос текстом, система отвечает по загруженным документам.</li>
        <li><strong>Таблица</strong> — вы задаёте один вопрос сразу ко всем документам и получаете ответы в строках таблицы.</li>
      </ul>
      <p>В обоих режимах к ответу можно перейти к фрагменту в оригинальном файле — чтобы проверить, откуда взят вывод.</p>
      <div class="note">Ответы системы не являются юридической консультацией. Итоговую оценку даёт юрист.</div>`,
    ),

    page(
      '2',
      'Создание дела',
      `<p>Дело в системе — это отдельная «папка» под одно банкротное производство (или проект по нему).</p>
      <ol class="steps">
        <li>На экране <strong>Дела</strong> откройте карточку <strong>«Новое дело»</strong>.</li>
        <li>В поле названия введите удобное вам имя — например, <em>А40-12345/2025 ООО «Ромашка»</em>. Можно любое, главное — чтобы вы сами потом нашли нужное дело в списке.</li>
        <li>Добавьте файлы: перетащите в окно, нажмите <strong>«Выбрать файлы»</strong> (с компьютера) или <strong>«Из Google Drive»</strong>. На скриншоте загружается выписка <code>funds_movement.pdf</code> — так же можно добавить акты, требования, договоры.</li>
        <li>Нажмите <strong>«Создать дело»</strong>. Файлы из списка «Файлы к загрузке» уйдут на сервер вместе с созданием дела.</li>
      </ol>
      <p>Если сейчас файлов нет — дело можно создать пустым и загрузить документы позже (см. стр. 3).</p>`,
      img(SHOTS.newCase),
    ),

    page(
      '3',
      'Главная страница дела',
      `<p>После создания дела открывается его главная страница. Здесь три способа начать работу:</p>
      <ul>
        <li><strong>Ассистент</strong> — «Задайте вопросы по документам дела». Подходит, когда нужен ответ на один конкретный вопрос.</li>
        <li><strong>Таблица</strong> — «Один вопрос — ко всем документам дела». Подходит, когда файлов много и нужна сводка по каждому.</li>
        <li><strong>Новый запрос</strong> — выбор типа задачи и файлов в одном окне.</li>
      </ul>
      <p>Ниже — блок <strong>Файлы</strong>. Здесь видно, что уже загружено (на скриншоте — <code>funds_movement.pdf</code>). Кнопка <strong>«Загрузить»</strong> добавляет новые документы. Лишний файл можно убрать через меню «⋯» справа от названия файла.</p>
      <p>После загрузки подождите несколько минут — системе нужно время, чтобы обработать новые файлы. Потом можно задавать вопросы.</p>`,
      img(SHOTS.caseHome),
    ),

    page(
      '4',
      'Ассистент по делу',
      `<p>Откройте дело → <strong>Ассистент</strong>. Введите вопрос в поле внизу и нажмите стрелку отправки.</p>
      <p><strong>Пример с экрана:</strong> вопрос <em>«о чем документ»</em>. Система отвечает, что в деле есть справка о движении средств по счёту, указывает период, договор и перечень операций.</p>
      <p>В ответе стоят <strong>синие цифры</strong> (1, 2, 3…). Это ссылки на фрагменты в документах.</p>
      <p><strong>Нажмите на цифру</strong> — откроется исходный PDF, нужное место будет <strong>подсвечено</strong>. Так вы проверяете, действительно ли в документе написано то, на что ссылается ответ.</p>
      <p class="example">Другие типичные вопросы: «перечисли стороны по договору поставки», «какая сумма в требовании кредитора», «есть ли в выписке платежи на ООО …».</p>`,
      img(SHOTS.chatAnswer),
    ),

    page(
      '5',
      'Режимы: 127‑ФЗ и судебная практика',
      `<p>Под полем ввода — два переключателя:</p>
      <ul>
        <li><strong>Законодательство (127 фз)</strong> — ответ с опорой на Федеральный закон № 127‑ФЗ «О несостоятельности (банкротстве)».</li>
        <li><strong>Судебная практика</strong> — ответ с опорой на судебные акты из базы практики.</li>
      </ul>
      <p><strong>Важно:</strong> включить можно <strong>только один</strong> из этих режимов. Если включён 127‑ФЗ — кнопка «Судебная практика» неактивна, и наоборот.</p>
      <p>Если оба выключены — ассистент отвечает <strong>только по документам</strong>, загруженным в это дело.</p>
      <p class="example">С включённым 127‑ФЗ: «какой срок созыва первого собрания кредиторов по ст. 72?»<br/>
      С включённой практикой: «как суды оценивают существенность убытка при оспаривании сделки?»</p>`,
      img(SHOTS.chatToggles),
    ),

    page(
      '6',
      'Создание таблицы',
      `<p>На главной странице дела нажмите <strong>Таблица</strong>. Откроется окно <strong>«Таблицы по делу»</strong>.</p>
      <p><strong>Зачем нужна таблица.</strong> В банкротстве часто десятки и сотни файлов. Вручную в каждом искать дату акта, сумму требования или тип документа — долго. Таблица задаёт один вопрос ко всем выбранным файлам и складывает ответы в одну таблицу — как сводная ведомость.</p>
      <p><strong>Как создать:</strong></p>
      <ul>
        <li><strong>«Создать таблицу»</strong> — пустая таблица, колонки добавите сами.</li>
        <li><strong>«Готовые шаблоны»</strong> — набор колонок под банкротство (даты, акты, платежи и т.д.).</li>
      </ul>
      <p class="example">Шаблоны в системе: «Обзор документов дела», «Судебные акты», «Требования кредиторов», «Платежи и расчёты», «Согласия финансового управляющего», «План реструктуризации / меры».</p>`,
      img(SHOTS.tableStart),
    ),

    page(
      '7',
      'Таблица: что на экране',
      `<p>Открыта таблица (на скриншоте — <em>демонстрация</em>). В ней одна строка — файл <code>funds_movement.pdf</code>.</p>
      <ul>
        <li><strong>Строка</strong> = один документ из дела.</li>
        <li><strong>Колонка</strong> = вопрос к каждому документу (пока колонка только «Документ», остальные добавляются).</li>
      </ul>
      <p><strong>«+ Добавить колонки»</strong> — новый вопрос ко всем строкам (например: «Дата документа», «Сумма требования»).</p>
      <p><strong>«+ Добавить документы»</strong> — включить в таблицу другие файлы из дела.</p>
      <p><strong>Ассистент справа</strong> — вопросы уже по заполненной таблице. Система сама предлагает варианты, например: <em>«Какие документы без даты в таблице?»</em>, <em>«Покажи только договоры»</em>, <em>«Какие суммы требований самые крупные?»</em></p>`,
      img(SHOTS.tableEmpty),
    ),

    page(
      '8',
      'Колонки: как устроены',
      `<p>Логика таблицы:</p>
      <div class="rule">
        каждая <strong>строка</strong> — отдельный файл;<br/>
        каждая <strong>колонка</strong> — один и тот же вопрос ко всем файлам в строках
      </div>
      <p>На скриншоте добавлена колонка <strong>«Суть»</strong> — вопрос: кратко описать, о чём документ. Система обрабатывает файл (в ячейке видна полоска загрузки).</p>
      <p>Колонку можно задать вручную через <strong>«+»</strong> или взять из шаблона. Примеры колонок из шаблона «Требования кредиторов»: <em>Кредитор</em>, <em>Сумма требования</em>, <em>Основание требования</em>, <em>Дата заявления</em>.</p>
      <p>Из шаблона «Судебные акты»: <em>Тип судебного акта</em>, <em>Дата акта</em>, <em>Суд</em>, <em>Суть акта</em>.</p>`,
      img(SHOTS.tableColumn),
    ),

    page(
      '9',
      'Запуск заполнения колонки',
      `<p>Когда колонка создана, нажмите <strong>треугольник ▶</strong> в заголовке колонки. Система начнёт заполнять ячейки — по одной на каждый документ в таблице.</p>
      <p>Пока идёт работа — в ячейке анимация загрузки. Когда готово — появляется текст ответа.</p>
      <p><strong>Результат на скриншоте</strong> (колонка «Суть», файл <code>funds_movement.pdf</code>):</p>
      <p class="example">«Это справка о движении средств (выписка) по счёту … за период с 27.03.2026 по 27.06.2026, содержащая перечень операций по списанию средств с карты».</p>
      <p>Так же заполняются остальные колонки — каждая по своему вопросу, по каждому документу в таблице.</p>`,
      img(SHOTS.tableFilled),
    ),

    page(
      '10',
      'Проверка ячейки по источнику',
      `<p>Нажмите на <strong>заполненную ячейку</strong>. Откроется окно:</p>
      <ul>
        <li><strong>ОТВЕТ</strong> — что извлечено из документа;</li>
        <li><strong>ОБЪЯСНЕНИЕ</strong> — откуда взята информация (например: «из шапки документа на стр. 1»);</li>
        <li><strong>ЦИТАТА ИЗ ДОКУМЕНТА</strong> — дословный фрагмент;</li>
        <li><strong>ИСТОЧНИКИ</strong> — номера страниц (на скриншоте: стр. 1, стр. 11);</li>
        <li><strong>УВЕРЕННОСТЬ</strong> — насколько система уверена в ответе.</li>
      </ul>
      <p>Нажмите <strong>«Посмотреть в документе»</strong> или на номер источника — откроется PDF, фрагмент будет подсвечен. Сверьте ответ с оригиналом перед тем, как использовать его в заключении, таблице для суда или отчёте ФУ.</p>`,
      `<div class="shots-row">${img(SHOTS.cellDetail)}${img(SHOTS.cellVerify)}</div>`,
    ),
  ]

  return `<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>Legal AI Vault — инструкция для юриста</title>
  <style>
    @page { size: A4; margin: 14mm 13mm 16mm 13mm; }
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      font-size: 10pt;
      line-height: 1.55;
      color: #1c1917;
      margin: 0;
    }
    .page {
      page-break-after: always;
      min-height: 0;
      padding-top: 2px;
    }
    .page:last-child { page-break-after: auto; }
    .page-head {
      display: flex;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 12px;
      padding-bottom: 8px;
      border-bottom: 2px solid #1c1917;
    }
    .page-num {
      font-size: 22pt;
      font-family: Georgia, serif;
      font-weight: 400;
      color: #a8a29e;
      line-height: 1;
      min-width: 28px;
    }
    h2 {
      font-family: Georgia, serif;
      font-size: 16pt;
      font-weight: 400;
      margin: 0;
      flex: 1;
    }
    .page-body p { margin: 0 0 8px; }
    .page-body ul, .page-body ol { margin: 0 0 10px; padding-left: 18px; }
    .page-body li { margin-bottom: 5px; }

    .steps { counter-reset: s; list-style: none; padding: 0; margin: 0 0 10px; }
    .steps li {
      counter-increment: s;
      padding: 0 0 8px 32px;
      position: relative;
      margin-bottom: 2px;
    }
    .steps li::before {
      content: counter(s) ".";
      position: absolute;
      left: 0;
      font-weight: 600;
      color: #57534e;
    }

    .note {
      margin-top: 14px;
      padding: 10px 12px;
      background: #fffbeb;
      border: 1px solid #fde68a;
      border-radius: 8px;
      font-size: 9pt;
    }
    .rule {
      background: #f5f5f4;
      border-radius: 8px;
      padding: 12px 14px;
      margin: 10px 0 12px;
      font-size: 10.5pt;
      line-height: 1.7;
    }
    .example {
      background: #fafaf9;
      border-left: 3px solid #d6d3d1;
      padding: 8px 12px;
      margin: 8px 0 10px;
      font-size: 9.5pt;
      color: #44403c;
      line-height: 1.5;
    }
    code {
      font-size: 9pt;
      background: #f5f5f4;
      padding: 1px 5px;
      border-radius: 4px;
    }

    .shot { margin: 10px 0 0; page-break-inside: avoid; }
    .shot img {
      width: 100%;
      border: 1px solid #e7e5e4;
      border-radius: 8px;
      display: block;
    }
    .shots-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 8px;
    }
    .shots-row .shot { margin: 0; }
    .shots-row .shot img { border-radius: 6px; }

    .doc-footer {
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      text-align: center;
      font-size: 7pt;
      color: #c4c0bb;
      padding: 4px;
    }
  </style>
</head>
<body>
  ${pages.join('\n')}
  <p class="doc-footer">Legal AI Vault · ${DATE}</p>
</body>
</html>`
}

async function launchBrowser() {
  try {
    return await chromium.launch({ headless: true, channel: 'chrome' })
  } catch {
    return await chromium.launch({ headless: true })
  }
}

async function main() {
  const html = buildHtml()
  await writeFile(OUT_HTML, html, 'utf8')

  const browser = await launchBrowser()
  const page = await browser.newPage()
  await page.goto(`file://${OUT_HTML}`, { waitUntil: 'networkidle' })
  await page.pdf({
    path: OUT_PDF,
    format: 'A4',
    printBackground: true,
    margin: { top: '12mm', right: '12mm', bottom: '14mm', left: '12mm' },
  })
  await browser.close()

  console.log('PDF:', OUT_PDF)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
