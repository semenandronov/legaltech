"use client"

import { useMemo } from 'react'
import type { TabularColumn, TabularRow } from '@/services/tabularReviewApi'
import type { OperationTransaction } from '@/services/operationsApi'
import { formatAmount } from '@/utils/operationsTableModel'

interface OperationsTableProps {
  columns: TabularColumn[]
  rows: TabularRow[]
  loading?: boolean
  selectedRowId?: string | null
  onRowClick?: (transaction: OperationTransaction) => void
  emptyMessage?: string
}

function getTransaction(row: TabularRow): OperationTransaction | null {
  const extended = row as TabularRow & { _transaction?: OperationTransaction }
  return extended._transaction ?? null
}

export function OperationsTable({
  columns,
  rows,
  loading = false,
  selectedRowId,
  onRowClick,
  emptyMessage = 'Нет операций по выбранным фильтрам.',
}: OperationsTableProps) {
  const displayColumns = useMemo(
    () => [...columns].sort((a, b) => a.order_index - b.order_index),
    [columns],
  )

  return (
    <div className="ws-tabular-table-wrap min-h-0 flex-1 flex flex-col overflow-hidden">
      <div className="ws-tabular-table-inner flex-1 overflow-auto">
        <table className="w-full border-collapse text-sm" style={{ minWidth: 720 }}>
          <thead className="sticky top-0 z-10 bg-white border-b border-gray-200">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 w-12">№</th>
              {displayColumns.map((column) => (
                <th
                  key={column.id}
                  className="px-3 py-2 text-left text-xs font-semibold text-gray-500 whitespace-nowrap"
                >
                  {column.column_label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={displayColumns.length + 1} className="px-3 py-16 text-center text-gray-500">
                  Загрузка операций…
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={displayColumns.length + 1} className="px-3 py-16 text-center text-gray-500">
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              rows.map((row, index) => {
                const tx = getTransaction(row)
                const isSelected = selectedRowId === row.file_id
                return (
                  <tr
                    key={row.file_id}
                    className={`border-b border-gray-100 cursor-pointer transition-colors ${
                      isSelected ? 'bg-indigo-50/80' : 'hover:bg-gray-50'
                    }`}
                    onClick={() => {
                      if (tx) onRowClick?.(tx)
                    }}
                  >
                    <td className="px-3 py-2 text-gray-400 tabular-nums">{index + 1}</td>
                    {displayColumns.map((column) => {
                      const raw = row.cells[column.id]?.cell_value
                      let display = raw == null || raw === '' ? '—' : String(raw)
                      if (column.id === 'op_amount' && tx?.amount_rub != null) {
                        display = formatAmount(tx.amount_rub)
                      }
                      return (
                        <td
                          key={column.id}
                          className={`px-3 py-2 align-top ${
                            column.id === 'op_description' ? 'max-w-md' : 'whitespace-nowrap'
                          }`}
                          style={{ color: 'var(--color-text-primary, #111827)' }}
                        >
                          <span className={column.id === 'op_description' ? 'line-clamp-2' : undefined}>
                            {display}
                          </span>
                        </td>
                      )
                    })}
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
