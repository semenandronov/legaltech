import { useState } from 'react'
import { X } from 'lucide-react'
import { operationsApi } from '@/services/operationsApi'
import type { OperationsListParams } from '@/services/operationsApi'
import { toast } from 'sonner'

interface OperationsExportDialogProps {
  open: boolean
  onClose: () => void
  caseId: string
  caseTitle: string
  listParams: OperationsListParams
}

export function OperationsExportDialog({
  open,
  onClose,
  caseId,
  caseTitle,
  listParams,
}: OperationsExportDialogProps) {
  const [format, setFormat] = useState<'excel' | 'csv'>('excel')
  const [isExporting, setIsExporting] = useState(false)

  if (!open) return null

  const handleExport = async () => {
    setIsExporting(true)
    try {
      const blob = await operationsApi.exportTransactions(caseId, {
        ...listParams,
        format,
      })
      const ext = format === 'excel' ? 'xlsx' : 'csv'
      const filename = `${caseTitle || 'operations'}.${ext}`
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
      toast.success('Файл скачан')
      onClose()
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Не удалось экспортировать'
      toast.error(message)
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[130] flex items-center justify-center p-4">
      <button type="button" className="absolute inset-0 bg-black/30" onClick={onClose} aria-label="Закрыть" />
      <div className="relative w-full max-w-md rounded-2xl bg-white shadow-xl border border-gray-100 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Экспорт операций</h2>
          <button type="button" onClick={onClose} className="p-1 rounded hover:bg-gray-100">
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="text-sm text-gray-600 mb-4">
          Будут выгружены все операции из выбранной выписки.
        </p>

        <div className="space-y-2 mb-6">
          {(['excel', 'csv'] as const).map((option) => (
            <label key={option} className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="radio"
                name="export-format"
                checked={format === option}
                onChange={() => setFormat(option)}
              />
              {option === 'excel' ? 'Excel (.xlsx)' : 'CSV (.csv)'}
            </label>
          ))}
        </div>

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm rounded-lg border border-gray-200">
            Отмена
          </button>
          <button
            type="button"
            onClick={handleExport}
            disabled={isExporting}
            className="px-4 py-2 text-sm rounded-lg bg-gray-900 text-white disabled:opacity-50"
          >
            {isExporting ? 'Экспорт…' : 'Скачать'}
          </button>
        </div>
      </div>
    </div>
  )
}
