import { tabularReviewApi } from '../services/tabularReviewApi'
import type { BuiltinTabularTemplate } from '../data/bankruptcyTabularTemplates'
import { BANKRUPTCY_RF_TABULAR_TEMPLATES } from '../data/bankruptcyTabularTemplates'

export type TabularTemplateCatalogItem = {
  id: string
  name: string
  description?: string
  category?: string
  tags?: string[]
  legalBasis?: string
  documentHint?: string
  columnLabels?: string[]
  featured?: boolean
  source: 'builtin' | 'api'
  columnsCount: number
}

export function listBuiltinBankruptcyTemplates(): BuiltinTabularTemplate[] {
  return BANKRUPTCY_RF_TABULAR_TEMPLATES
}

function mapBuiltinToCatalogItem(t: BuiltinTabularTemplate): TabularTemplateCatalogItem {
  return {
    id: t.id,
    name: t.name,
    description: t.description,
    category: t.category,
    tags: t.tags,
    legalBasis: t.legalBasis,
    documentHint: t.documentHint,
    columnLabels: t.columns.map((c) => c.column_label),
    featured: t.featured,
    source: 'builtin',
    columnsCount: t.columns.length,
  }
}

/** Каталог для хаба дела: только три встроенных пресета банкротства. */
export async function fetchBankruptcyTemplateCatalog(): Promise<TabularTemplateCatalogItem[]> {
  return BANKRUPTCY_RF_TABULAR_TEMPLATES.map(mapBuiltinToCatalogItem)
}

export async function applyTabularTemplateToReview(
  reviewId: string,
  templateId: string,
  source: 'builtin' | 'api',
): Promise<void> {
  if (source === 'api') {
    await tabularReviewApi.applyTemplate(reviewId, templateId)
    return
  }
  const builtin = BANKRUPTCY_RF_TABULAR_TEMPLATES.find((t) => t.id === templateId)
  if (!builtin) {
    throw new Error('Шаблон не найден')
  }
  await tabularReviewApi.addColumnsBulk(reviewId, builtin.columns)
}

export function getBuiltinTemplateById(templateId: string): BuiltinTabularTemplate | undefined {
  return BANKRUPTCY_RF_TABULAR_TEMPLATES.find((t) => t.id === templateId)
}
