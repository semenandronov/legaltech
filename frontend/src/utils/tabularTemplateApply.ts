import { tabularReviewApi } from '../services/tabularReviewApi'
import type { BuiltinTabularTemplate } from '../data/ddTabularTemplates'
import { DD_RF_TABULAR_TEMPLATES } from '../data/ddTabularTemplates'

export type { BuiltinTabularTemplate }

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

export function listBuiltinDdTemplates(): BuiltinTabularTemplate[] {
  return DD_RF_TABULAR_TEMPLATES
}

/** @deprecated Use listBuiltinDdTemplates */
export function listBuiltinBankruptcyTemplates(): BuiltinTabularTemplate[] {
  return listBuiltinDdTemplates()
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

/** Каталог для хаба дела: три встроенных DD-пресета. */
export async function fetchDdTemplateCatalog(): Promise<TabularTemplateCatalogItem[]> {
  return DD_RF_TABULAR_TEMPLATES.map(mapBuiltinToCatalogItem)
}

/** @deprecated Use fetchDdTemplateCatalog */
export async function fetchBankruptcyTemplateCatalog(): Promise<TabularTemplateCatalogItem[]> {
  return fetchDdTemplateCatalog()
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
  const builtin = DD_RF_TABULAR_TEMPLATES.find((t) => t.id === templateId)
  if (!builtin) {
    throw new Error('Шаблон не найден')
  }
  await tabularReviewApi.addColumnsBulk(reviewId, builtin.columns)
}

export function getBuiltinTemplateById(templateId: string): BuiltinTabularTemplate | undefined {
  return DD_RF_TABULAR_TEMPLATES.find((t) => t.id === templateId)
}
