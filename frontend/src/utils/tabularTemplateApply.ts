import { tabularReviewApi } from '../services/tabularReviewApi'
import type { BuiltinTabularTemplate } from '../data/bankruptcyTabularTemplates'
import { BANKRUPTCY_RF_TABULAR_TEMPLATES } from '../data/bankruptcyTabularTemplates'

export type TabularTemplateCatalogItem = {
  id: string
  name: string
  description?: string
  category?: string
  tags?: string[]
  featured?: boolean
  source: 'builtin' | 'api'
  columnsCount: number
}

export function listBuiltinBankruptcyTemplates(): BuiltinTabularTemplate[] {
  return BANKRUPTCY_RF_TABULAR_TEMPLATES
}

export async function fetchBankruptcyTemplateCatalog(): Promise<TabularTemplateCatalogItem[]> {
  const builtin: TabularTemplateCatalogItem[] = BANKRUPTCY_RF_TABULAR_TEMPLATES.map((t) => ({
    id: t.id,
    name: t.name,
    description: t.description,
    category: t.category,
    tags: t.tags,
    featured: t.featured,
    source: 'builtin' as const,
    columnsCount: t.columns.length,
  }))

  try {
    const apiTemplates = await tabularReviewApi.getTemplates({ category: 'bankruptcy_rf' })
    const fromApi: TabularTemplateCatalogItem[] = (apiTemplates || []).map((t) => ({
      id: t.id,
      name: t.name,
      description: t.description,
      category: t.category,
      tags: t.tags,
      featured: t.is_featured,
      source: 'api' as const,
      columnsCount: Array.isArray(t.columns) ? t.columns.length : 0,
    }))
    const apiNames = new Set(fromApi.map((t) => t.name.toLowerCase()))
    const merged = [
      ...fromApi,
      ...builtin.filter((b) => !apiNames.has(b.name.toLowerCase())),
    ]
    return merged.sort((a, b) => Number(Boolean(b.featured)) - Number(Boolean(a.featured)))
  } catch {
    return builtin
  }
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
