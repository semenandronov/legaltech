import { describe, expect, it } from 'vitest'
import {
  bankruptcyPeriodWindow,
  formatIsoDate,
  parseIsoDate,
  resolveActivePeriodRange,
} from './operationsBankruptcyPeriods'

describe('operationsBankruptcyPeriods', () => {
  it('builds one-month window ending on petition date', () => {
    const petition = parseIsoDate('2024-03-15')
    expect(petition).not.toBeNull()
    const window = bankruptcyPeriodWindow(petition!, '1m')
    expect(window.dateFrom).toBe('2024-02-15')
    expect(window.dateTo).toBe('2024-03-15')
  })

  it('resolves active period range only when both values exist', () => {
    expect(resolveActivePeriodRange('2024-03-15', '3y')).toEqual({
      dateFrom: '2021-03-15',
      dateTo: '2024-03-15',
    })
    expect(resolveActivePeriodRange(null, '1y')).toEqual({})
  })

  it('formats and parses ISO dates', () => {
    const date = new Date(2024, 0, 5)
    expect(formatIsoDate(date)).toBe('2024-01-05')
    expect(parseIsoDate('2024-01-05')?.getDate()).toBe(5)
  })
})
