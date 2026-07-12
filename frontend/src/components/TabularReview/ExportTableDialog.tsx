import { useState } from 'react'
import { X } from 'lucide-react'
import { tabularReviewApi } from '../../services/tabularReviewApi'
import { downloadBlob } from '../../utils/fileDownload'
import { toast } from 'sonner'

interface ExportTableDialogProps {
  open: boolean
  onClose: () => void
  reviewId: string
  reviewName: string
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="relative inline-flex h-6 w-11 flex-shrink-0 rounded-full transition-colors duration-200 ease-in-out focus:outline-none"
      style={{ backgroundColor: checked ? '#111827' : '#D1D5DB' }}
    >
      <span
        className="inline-block h-5 w-5 rounded-full bg-white shadow transform transition-transform duration-200 ease-in-out"
        style={{
          marginTop: '2px',
          marginLeft: '2px',
          transform: checked ? 'translateX(20px)' : 'translateX(0)',
        }}
      />
    </button>
  )
}

export function ExportTableDialog({ open, onClose, reviewId, reviewName }: ExportTableDialogProps) {
  const [format, setFormat] = useState<'excel' | 'word' | 'csv'>('excel')
  const [includeQuestion, setIncludeQuestion] = useState(true)
  const [includeContext, setIncludeContext] = useState(false)
  const [isExporting, setIsExporting] = useState(false)

  if (!open) return null

  const handleExport = async () => {
    if (!reviewId?.trim()) {
      toast.error('Таблица не найдена')
      return
    }
    setIsExporting(true)
    try {
      const options = {
        includeQuestion,
        includeContext,
      }
      let blob: Blob
      let filename: string
      const baseName = reviewName || 'tabular_review'

      switch (format) {
        case 'excel':
          blob = await tabularReviewApi.exportToExcel(reviewId, options)
          filename = `${baseName}.xlsx`
          break
        case 'word':
          blob = await tabularReviewApi.exportToWord(reviewId, options)
          filename = `${baseName}.docx`
          break
        case 'csv':
          blob = await tabularReviewApi.exportToCSV(reviewId, options)
          filename = `${baseName}.csv`
          break
        default: {
          const _exhaustive: never = format
          throw new Error(`Неизвестный формат: ${_exhaustive}`)
        }
      }

      downloadBlob(blob, filename)
      toast.success('Экспорт завершён')
      onClose()
    } catch (err) {
      console.error('Export failed:', err)
      const message = err instanceof Error ? err.message : 'Ошибка при экспорте'
      toast.error(message)
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />

      <div
        className="relative bg-white rounded-xl shadow-xl"
        style={{ width: 520, padding: '24px' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold" style={{ color: '#111827' }}>
            Экспорт таблицы
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-md hover:bg-gray-100 transition-colors"
          >
            <X className="w-4 h-4" style={{ color: '#6B7280' }} />
          </button>
        </div>

        <hr style={{ borderColor: '#E5E7EB', marginBottom: '20px' }} />

        <div className="mb-6">
          <p className="text-sm mb-3" style={{ color: '#6B7280' }}>
            Формат
          </p>
          <div className="flex items-center gap-6">
            {(['excel', 'word', 'csv'] as const).map((f) => (
              <label key={f} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="format"
                  value={f}
                  checked={format === f}
                  onChange={() => setFormat(f)}
                  className="w-4 h-4 cursor-pointer accent-gray-900"
                />
                <span className="text-sm" style={{ color: '#111827' }}>
                  {f === 'excel' ? 'Excel' : f === 'word' ? 'Word' : 'CSV'}
                </span>
              </label>
            ))}
          </div>
        </div>

        <div className="mb-5">
          <p className="text-sm mb-3" style={{ color: '#6B7280' }}>
            Параметры
          </p>
          <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <span className="text-sm" style={{ color: '#111827' }}>
                Включить вопрос по каждой колонке
              </span>
              <Toggle checked={includeQuestion} onChange={setIncludeQuestion} />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm" style={{ color: '#111827' }}>
                Включить дополнительный контекст колонок
              </span>
              <Toggle checked={includeContext} onChange={setIncludeContext} />
            </div>
          </div>
        </div>

        <hr style={{ borderColor: '#E5E7EB', marginBottom: '20px' }} />

        <div className="flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg transition-colors hover:bg-gray-100"
            style={{ color: '#374151' }}
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={() => {
              void handleExport()
            }}
            disabled={isExporting}
            className="px-4 py-2 text-sm font-medium text-white rounded-lg transition-colors disabled:opacity-60"
            style={{ backgroundColor: '#111827' }}
          >
            {isExporting ? 'Экспорт…' : 'Скачать'}
          </button>
        </div>
      </div>
    </div>
  )
}
