import type { TabularColumn } from '@/services/tabularReviewApi'

export interface TabularColumnSavePayload {
  column_label: string
  column_type: TabularColumn['column_type']
  prompt: string
  column_config?: TabularColumn['column_config']
}
