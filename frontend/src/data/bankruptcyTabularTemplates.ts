/**
 * Встроенные шаблоны таблиц для практики банкротства в РФ.
 * Используются без записи в БД (addColumnsBulk после создания review).
 */
import type { ProposedColumn } from '../services/tabularReviewApi'

export type BuiltinTabularTemplate = {
  id: string
  name: string
  description: string
  category: 'bankruptcy_rf'
  tags: string[]
  columns: ProposedColumn[]
  featured?: boolean
}

export const BANKRUPTCY_RF_TABULAR_TEMPLATES: BuiltinTabularTemplate[] = [
  {
    id: 'builtin-bankruptcy-doc-overview',
    name: 'Обзор документов дела',
    description:
      'Базовый набор колонок: тип, дата, краткое содержание и дата подписания каждого документа.',
    category: 'bankruptcy_rf',
    tags: ['банкротство', 'обзор'],
    featured: true,
    columns: [
      {
        column_label: 'Тип документа',
        column_type: 'text',
        prompt: 'Определи тип и категорию этого юридического документа по содержанию и структуре (кратко, на русском).',
      },
      {
        column_label: 'Дата документа',
        column_type: 'date',
        prompt: 'Дата составления или подписания этого документа (не даты из приложений и ссылок на другие акты).',
      },
      {
        column_label: 'Краткое содержание',
        column_type: 'text',
        prompt: 'Кратко опиши предмет и суть документа в 1–2 предложениях.',
      },
      {
        column_label: 'Дата подписания',
        column_type: 'date',
        prompt: 'Дата подписания этого документа сторонами или уполномоченным лицом.',
      },
      {
        column_label: 'Стороны',
        column_type: 'text',
        prompt: 'Укажи основные стороны документа (должник, кредитор, суд, ФУ и т.п.).',
      },
    ],
  },
  {
    id: 'builtin-bankruptcy-court-acts',
    name: 'Судебные акты',
    description: 'Определения, решения и постановления в деле о банкротстве.',
    category: 'bankruptcy_rf',
    tags: ['суд', 'определение'],
    featured: true,
    columns: [
      {
        column_label: 'Тип судебного акта',
        column_type: 'text',
        prompt: 'Тип судебного акта (определение, решение, постановление и т.п.).',
      },
      {
        column_label: 'Дата акта',
        column_type: 'date',
        prompt: 'Дата вынесения судебного акта.',
      },
      {
        column_label: 'Суд',
        column_type: 'text',
        prompt: 'Наименование арбитражного суда, вынесшего акт.',
      },
      {
        column_label: 'Номер дела',
        column_type: 'text',
        prompt: 'Номер дела в арбитражном суде, указанный в документе.',
      },
      {
        column_label: 'Суть акта',
        column_type: 'text',
        prompt: 'Кратко: о чём судебный акт и какое процессуальное решение принято.',
      },
    ],
  },
  {
    id: 'builtin-bankruptcy-fu-consents',
    name: 'Согласия финансового управляющего',
    description: 'Согласия ФУ на сделки, отчёты и иные действия в процедуре.',
    category: 'bankruptcy_rf',
    tags: ['ФУ', 'согласие'],
    columns: [
      {
        column_label: 'Дата согласия',
        column_type: 'date',
        prompt: 'Дата подписания согласия финансового управляющего.',
      },
      {
        column_label: 'Предмет согласия',
        column_type: 'text',
        prompt: 'На что дано согласие ФУ (сделка, отчёт, действие и т.п.).',
      },
      {
        column_label: 'Финансовый управляющий',
        column_type: 'text',
        prompt: 'ФИО финансового управляющего, давшего согласие.',
      },
      {
        column_label: 'Сумма сделки',
        column_type: 'currency',
        prompt: 'Сумма сделки или обязательства, если указана в документе.',
      },
    ],
  },
  {
    id: 'builtin-bankruptcy-payments',
    name: 'Платежи и расчёты',
    description: 'Платёжные поручения и документы о движении денежных средств.',
    category: 'bankruptcy_rf',
    tags: ['платёж', 'расчёты'],
    columns: [
      {
        column_label: 'Дата платежа',
        column_type: 'date',
        prompt: 'Дата платежа или дата платёжного поручения.',
      },
      {
        column_label: 'Сумма',
        column_type: 'currency',
        prompt: 'Сумма платежа с указанием валюты.',
      },
      {
        column_label: 'Плательщик',
        column_type: 'text',
        prompt: 'Наименование плательщика.',
      },
      {
        column_label: 'Получатель',
        column_type: 'text',
        prompt: 'Наименование получателя платежа.',
      },
      {
        column_label: 'Назначение платежа',
        column_type: 'text',
        prompt: 'Назначение платежа или основание перевода.',
      },
    ],
  },
  {
    id: 'builtin-bankruptcy-plan-restructuring',
    name: 'План реструктуризации / меры',
    description: 'Документы по плану реструктуризации, плану продажи и связанным мерам.',
    category: 'bankruptcy_rf',
    tags: ['план', 'реструктуризация'],
    columns: [
      {
        column_label: 'Тип документа по плану',
        column_type: 'text',
        prompt: 'Роль документа в процедуре (план, возражения, согласие, отчёт и т.п.).',
      },
      {
        column_label: 'Дата документа',
        column_type: 'date',
        prompt: 'Дата документа, относящегося к плану или мерам.',
      },
      {
        column_label: 'Сторона / автор',
        column_type: 'text',
        prompt: 'Кто является стороной или автором документа (должник, кредитор, ФУ, комитет).',
      },
      {
        column_label: 'Позиция по плану',
        column_type: 'text',
        prompt: 'Кратко: согласие, возражение, предложение изменений или иная позиция по плану.',
      },
    ],
  },
  {
    id: 'builtin-bankruptcy-creditor-claims',
    name: 'Требования кредиторов',
    description: 'Заявления, реестр и документы по требованиям кредиторов.',
    category: 'bankruptcy_rf',
    tags: ['кредитор', 'требование'],
    columns: [
      {
        column_label: 'Кредитор',
        column_type: 'text',
        prompt: 'Наименование кредитора, заявившего требование.',
      },
      {
        column_label: 'Сумма требования',
        column_type: 'currency',
        prompt: 'Размер денежного требования с валютой, если указано.',
      },
      {
        column_label: 'Очередь',
        column_type: 'text',
        prompt: 'Очередь удовлетворения требования, если указана в документе.',
      },
      {
        column_label: 'Основание требования',
        column_type: 'text',
        prompt: 'Кратко: правовое и фактическое основание требования.',
      },
      {
        column_label: 'Дата заявления',
        column_type: 'date',
        prompt: 'Дата подачи заявления о включении в реестр или иного документа по требованию.',
      },
    ],
  },
]
