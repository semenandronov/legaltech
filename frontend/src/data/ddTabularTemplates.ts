/**
 * Встроенные шаблоны Tabular Review для due diligence коммерческих договоров (РФ).
 * Три рабочих пресета: аренда, поставка, услуги/подряд.
 */
import type { ProposedColumn } from '../services/tabularReviewApi'

export type BuiltinTabularTemplate = {
  id: string
  name: string
  description: string
  category: 'due_diligence'
  tags: string[]
  /** Краткая правовая опора для UI */
  legalBasis?: string
  /** Для каких документов шаблон */
  documentHint?: string
  columns: ProposedColumn[]
  featured?: boolean
}

function fieldCol(
  fieldId: string,
  label: string,
  columnType: string,
  prompt: string,
): ProposedColumn {
  return {
    column_label: label,
    column_type: columnType,
    prompt,
    column_config: { field_id: fieldId, column_kind: 'fact' },
  }
}

const RISK_COLUMN: ProposedColumn = {
  column_label: 'Ключевые риски',
  column_type: 'text',
  prompt:
    'Перечисли ключевые риски этого договора для due diligence ' +
    '(ответственность, расторжение, неустойка, оплата, односторонний отказ). ' +
    'Краткий маркированный список со ссылкой на пункты, если они есть в тексте.',
  column_config: { column_kind: 'risk_analysis' },
}

const TERMINATION_COLUMN: ProposedColumn = {
  column_label: 'Расторжение / отказ',
  column_type: 'text',
  prompt:
    'Как можно расторгнуть договор или отказаться от исполнения? ' +
    'Укажи основания, сроки уведомления и последствия. Если не указано — «не указано».',
}

const LIABILITY_COLUMN: ProposedColumn = {
  column_label: 'Ответственность',
  column_type: 'text',
  prompt:
    'Какова ответственность сторон: неустойка, ограничение убытков, исключение упущенной выгоды? ' +
    'Кратко по пунктам. Если не указано — «не указано».',
}

export const DD_RF_TABULAR_TEMPLATES: BuiltinTabularTemplate[] = [
  {
    id: 'builtin-dd-lease-commercial',
    name: 'DD: коммерческая аренда',
    description:
      'Карточка договора аренды для due diligence: стороны, объект, плата, срок, выкуп, неустойка и риски.',
    legalBasis: 'гл. 34 ГК РФ',
    documentHint: 'Договоры аренды, доп. соглашения к аренде',
    category: 'due_diligence',
    tags: ['DD', 'аренда', 'lease'],
    featured: true,
    columns: [
      fieldCol('doc_number', 'Номер договора', 'text', 'Укажи номер этого договора / дополнительного соглашения.'),
      fieldCol('doc_date', 'Дата документа', 'date', 'Дата подписания или составления этого документа (YYYY-MM-DD).'),
      fieldCol('landlord', 'Арендодатель', 'text', 'Кто арендодатель? Укажи полное наименование и ИНН, если есть.'),
      fieldCol('tenant', 'Арендатор', 'text', 'Кто арендатор? Укажи полное наименование и ИНН, если есть.'),
      fieldCol('leased_object', 'Объект аренды', 'text', 'Что передаётся в аренду? Адрес / описание объекта.'),
      fieldCol('rent_amount', 'Арендная плата', 'currency', 'Ключевая сумма арендной платы с валютой и периодичностью, если указана.'),
      fieldCol('contract_term', 'Срок договора', 'text', 'Срок действия договора или даты начала и окончания.'),
      fieldCol('buyout_right', 'Право выкупа', 'yes_no', 'Предусмотрено ли право выкупа? Да / Нет.'),
      fieldCol('penalty', 'Неустойка', 'text', 'Условия неустойки / пени за просрочку оплаты или иные нарушения.'),
      TERMINATION_COLUMN,
      LIABILITY_COLUMN,
      fieldCol('governing_law', 'Применимое право', 'text', 'Применимое право и/или подсудность.'),
      RISK_COLUMN,
    ],
  },
  {
    id: 'builtin-dd-supply',
    name: 'DD: поставка',
    description:
      'Карточка договора поставки: стороны, товар, цена, сроки поставки, неустойка, расторжение и риски.',
    legalBasis: '§ 3 гл. 30 ГК РФ',
    documentHint: 'Договоры поставки, спецификации, доп. соглашения',
    category: 'due_diligence',
    tags: ['DD', 'поставка', 'supply'],
    featured: true,
    columns: [
      fieldCol('doc_number', 'Номер договора', 'text', 'Укажи номер этого договора / дополнительного соглашения.'),
      fieldCol('doc_date', 'Дата документа', 'date', 'Дата подписания или составления этого документа (YYYY-MM-DD).'),
      fieldCol('supplier', 'Поставщик', 'text', 'Кто поставщик? Укажи полное наименование и ИНН, если есть.'),
      fieldCol('buyer', 'Покупатель', 'text', 'Кто покупатель? Укажи полное наименование и ИНН, если есть.'),
      fieldCol('goods', 'Товар', 'text', 'Какой товар поставляется? Кратко по предмету / спецификации.'),
      fieldCol('price_total', 'Сумма / цена', 'currency', 'Ключевая цена или общая сумма по договору с валютой.'),
      fieldCol('delivery_term', 'Срок поставки', 'text', 'Срок или условия поставки (даты, Incoterms, график).'),
      fieldCol('penalty', 'Неустойка', 'text', 'Условия неустойки / пени за просрочку поставки или оплаты.'),
      TERMINATION_COLUMN,
      LIABILITY_COLUMN,
      fieldCol('governing_law', 'Применимое право', 'text', 'Применимое право и/или подсудность.'),
      RISK_COLUMN,
    ],
  },
  {
    id: 'builtin-dd-services-works',
    name: 'DD: услуги и подряд',
    description:
      'Карточка договора услуг или подряда: стороны, объём, цена, сроки/SLA, неустойка, расторжение и риски.',
    legalBasis: 'гл. 37, 39 ГК РФ',
    documentHint: 'Договоры оказания услуг, подряда, доп. соглашения',
    category: 'due_diligence',
    tags: ['DD', 'услуги', 'подряд', 'services'],
    featured: true,
    columns: [
      fieldCol('doc_number', 'Номер договора', 'text', 'Укажи номер этого договора / дополнительного соглашения.'),
      fieldCol('doc_date', 'Дата документа', 'date', 'Дата подписания или составления этого документа (YYYY-MM-DD).'),
      fieldCol('customer', 'Заказчик', 'text', 'Кто заказчик? Укажи полное наименование и ИНН, если есть.'),
      fieldCol(
        'contractor',
        'Исполнитель / подрядчик',
        'text',
        'Кто исполнитель или подрядчик? Укажи полное наименование и ИНН, если есть.',
      ),
      fieldCol('scope', 'Объём услуг/работ', 'text', 'Какой объём услуг или работ? Кратко по предмету договора.'),
      fieldCol('price_total', 'Сумма / цена', 'currency', 'Ключевая цена или общая сумма по договору с валютой.'),
      fieldCol('sla_or_deadline', 'Срок выполнения / SLA', 'text', 'Срок выполнения работ/услуг или SLA.'),
      fieldCol('penalty', 'Неустойка', 'text', 'Условия неустойки / пени за просрочку или иные нарушения.'),
      TERMINATION_COLUMN,
      LIABILITY_COLUMN,
      fieldCol('governing_law', 'Применимое право', 'text', 'Применимое право и/или подсудность.'),
      RISK_COLUMN,
    ],
  },
]
