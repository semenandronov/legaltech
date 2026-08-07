import { describe, expect, it } from 'vitest'
import type { TabularCell, TabularColumn } from '@/services/tabularReviewApi'
import {
  formatTabularCellValue,
  getTabularCellAttention,
  isExplicitTabularNaValue,
  TABULAR_EMPTY_DISPLAY,
  TABULAR_NA_DISPLAY,
} from './tabularCellDisplay'

const textColumn = {
  id: 'c1',
  column_label: 'Поле',
  column_type: 'text',
} as TabularColumn

function cell(partial: Partial<TabularCell>): TabularCell {
  return {
    id: 'cell-1',
    review_id: 'r1',
    file_id: 'f1',
    column_id: 'c1',
    cell_value: '',
    status: 'completed',
    ...partial,
  } as TabularCell
}

describe('isExplicitTabularNaValue', () => {
  it('detects N/A variants including Russian «—»', () => {
    expect(isExplicitTabularNaValue('N/A')).toBe(true)
    expect(isExplicitTabularNaValue('—')).toBe(true)
    expect(isExplicitTabularNaValue('нет данных')).toBe(true)
    expect(isExplicitTabularNaValue('Н/Д')).toBe(true)
    expect(isExplicitTabularNaValue('')).toBe(false)
    expect(isExplicitTabularNaValue('-')).toBe(false)
    expect(isExplicitTabularNaValue('ООО Ромашка')).toBe(false)
  })
})

describe('formatTabularCellValue', () => {
  it('keeps прочерк (not found) distinct from empty hyphen', () => {
    expect(formatTabularCellValue(cell({ cell_value: 'N/A' }), textColumn)).toBe(
      TABULAR_NA_DISPLAY,
    )
    expect(formatTabularCellValue(cell({ cell_value: 'Не найдено' }), textColumn)).toBe(
      TABULAR_NA_DISPLAY,
    )
    expect(formatTabularCellValue(cell({ cell_value: '—' }), textColumn)).toBe(
      TABULAR_NA_DISPLAY,
    )
    expect(formatTabularCellValue(cell({ status: 'n_a', cell_value: '' }), textColumn)).toBe(
      TABULAR_NA_DISPLAY,
    )
    expect(formatTabularCellValue(undefined, textColumn)).toBe(TABULAR_EMPTY_DISPLAY)
    expect(formatTabularCellValue(cell({ cell_value: '' }), textColumn)).toBe(
      TABULAR_EMPTY_DISPLAY,
    )
    expect(formatTabularCellValue(cell({ cell_value: '-' }), textColumn)).toBe(
      TABULAR_EMPTY_DISPLAY,
    )
  })

  it('formats yes_no and dates without collapsing real values', () => {
    const yesNo = { ...textColumn, column_type: 'yes_no' } as TabularColumn
    expect(formatTabularCellValue(cell({ cell_value: 'Yes' }), yesNo)).toBe('Да')

    const dateCol = { ...textColumn, column_type: 'date' } as TabularColumn
    expect(formatTabularCellValue(cell({ cell_value: '2024-03-15' }), dateCol)).toBe(
      '15.03.2024',
    )
    expect(formatTabularCellValue(cell({ cell_value: 'N/A' }), dateCol)).toBe(TABULAR_NA_DISPLAY)
  })
})

describe('getTabularCellAttention', () => {
  it('flags conflict and low confidence, skips reviewed', () => {
    expect(getTabularCellAttention(cell({ status: 'conflict' }))).toBe('conflict')
    expect(
      getTabularCellAttention(cell({ status: 'completed', confidence_score: 0.4 })),
    ).toBe('low_confidence')
    expect(
      getTabularCellAttention(cell({ status: 'reviewed', confidence_score: 0.2 })),
    ).toBe('none')
    expect(
      getTabularCellAttention(cell({ status: 'completed', confidence_score: 0.95 })),
    ).toBe('none')
  })
})
