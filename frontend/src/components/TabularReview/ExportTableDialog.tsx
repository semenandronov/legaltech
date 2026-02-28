import { useState } from 'react'
import { X } from 'lucide-react'
import { tabularReviewApi } from '../../services/tabularReviewApi'
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
  const [includeContext, setIncludeContext] = useState(true)
  const [isExporting, setIsExporting] = useState(false)

  if (!open) return null

  const handleExport = async () => {
    setIsExporting(true)
    try {
      let blob: Blob
      let filename: string

      if (format === 'excel') {
        blob = await tabularReviewApi.exportToExcel(reviewId)
        filename = `${reviewName}.xlsx`
      } else if (format === 'word') {
        blob = await tabularReviewApi.exportToWord(reviewId)
        filename = `${reviewName}.docx`
      } else {
        blob = await tabularReviewApi.exportToCSV(reviewId)
        filename = `${reviewName}.csv`
      }

      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)

      toast.success('Экспорт завершён')
      onClose()
    } catch (err) {
      console.error('Export failed:', err)
      toast.error('Ошибка при экспорте')
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />

      {/* Dialog */}
      <div
        className="relative bg-white rounded-xl shadow-xl"
        style={{ width: 520, padding: '24px' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold" style={{ color: '#111827' }}>
            Export
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded-md hover:bg-gray-100 transition-colors"
          >
            <X className="w-4 h-4" style={{ color: '#6B7280' }} />
          </button>
        </div>

        <hr style={{ borderColor: '#E5E7EB', marginBottom: '20px' }} />

        {/* Extension */}
        <div className="mb-6">
          <p className="text-sm mb-3" style={{ color: '#6B7280' }}>
            Extension
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

        {/* Export Options */}
        <div className="mb-5">
          <p className="text-sm mb-3" style={{ color: '#6B7280' }}>
            Export Options
          </p>
          <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <span className="text-sm" style={{ color: '#111827' }}>
                Include question for each column
              </span>
              <Toggle checked={includeQuestion} onChange={setIncludeQuestion} />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm" style={{ color: '#111827' }}>
                Include{' '}
                <strong>"Additional Context"</strong>{' '}
                for each column
              </span>
              <Toggle checked={includeContext} onChange={setIncludeContext} />
            </div>
          </div>
        </div>

        <hr style={{ borderColor: '#E5E7EB', marginBottom: '20px' }} />

        {/* Additional Options */}
        <div className="mb-6">
          <p className="text-sm mb-3" style={{ color: '#6B7280' }}>
            Additional Options
          </p>
          <div className="flex items-center justify-between opacity-40">
            <span className="text-sm" style={{ color: '#111827' }}>
              Download files from the table as a zip
            </span>
            <Toggle checked={false} onChange={() => {}} />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg transition-colors hover:bg-gray-100"
            style={{ color: '#374151' }}
          >
            Cancel
          </button>
          <button
            onClick={handleExport}
            disabled={isExporting}
            className="px-4 py-2 text-sm font-medium text-white rounded-lg transition-colors disabled:opacity-60"
            style={{ backgroundColor: '#111827' }}
            onMouseEnter={(e) => { if (!isExporting) (e.currentTarget as HTMLElement).style.backgroundColor = '#374151' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = '#111827' }}
          >
            {isExporting ? 'Exporting...' : 'Export'}
          </button>
        </div>
      </div>
    </div>
  )
}
