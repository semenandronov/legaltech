import { useState } from 'react'
import { X } from 'lucide-react'
import { operationsApi } from '@/services/operationsApi'
import { downloadBlob } from '@/utils/fileDownload'
import { toast } from 'sonner'

interface OperationsExportDialogProps {
  open: boolean
  onClose: () => void
  caseId: string
  caseTitle: string
  fileId: string
  /** Transaction IDs currently visible after UI filters (WYSIWYG). */
  transactionIds: string[]
  totalInStatement: number
}

export function OperationsExportDialog({
  open,
  onClose,
  caseId,
  caseTitle,
  fileId,
  transactionIds,
  totalInStatement,
}: OperationsExportDialogProps) {
  const [format, setFormat] = useState<'excel' | 'csv'>('excel')
  const [isExporting, setIsExporting] = useState(false)

  if (!open) return null

  const filteredCount = transactionIds.length
  const isFiltered = filteredCount !== totalInStatement

  const handleExport = async () => {
    if (!fileId?.trim()) {
      toast.error('Сначала выберите выписку')
      return
    }
    if (filteredCount === 0) {
      toast.error('Нет операций для экспорта по текущим фильтрам')
      return
    }
    setIsExporting(true)
    try {
      const blob = await operationsApi.exportTransactions(caseId, {
        fileId,
        format,
        transactionIds,
      })
      const ext = format === 'excel' ? 'xlsx' : 'csv'
      const suffix = isFiltered ? `_фильтр_${filteredCount}` : ''
      downloadBlob(blob, `${caseTitle || 'operations'}${suffix}.${ext}`)
      toast.success(
        isFiltered
          ? `Скачано ${filteredCount} операций (с учётом фильтров)`
          : `Скачано ${filteredCount} операций`,
      )
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
          {isFiltered ? (
            <>
              Будут выгружены <strong>{filteredCount}</strong> операций с учётом текущих фильтров
              {totalInStatement > 0 ? <> (из {totalInStatement} в выписке)</> : null}.
            </>
          ) : (
            <>Будут выгружены все операции выбранной выписки ({filteredCount}).</>
          )}
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
            onClick={() => {
              void handleExport()
            }}
            disabled={isExporting || filteredCount === 0}
            className="px-4 py-2 text-sm rounded-lg bg-gray-900 text-white disabled:opacity-50"
          >
            {isExporting ? 'Экспорт…' : 'Скачать'}
          </button>
        </div>
      </div>
    </div>
  )
}
