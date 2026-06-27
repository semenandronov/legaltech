import { useEffect, useState } from 'react'
import { Check, FileText, Loader2, Search, X } from 'lucide-react'

export interface CaseFileItem {
  id: string
  filename: string
  file_type: string
}

export interface CaseFilePickerModalProps {
  isOpen: boolean
  files: CaseFileItem[]
  loading: boolean
  initialSelectedIds: string[]
  onApply: (ids: string[]) => void
  onClose: () => void
}

export function CaseFilePickerModal({
  isOpen,
  files,
  loading,
  initialSelectedIds,
  onApply,
  onClose,
}: CaseFilePickerModalProps) {
  const [search, setSearch] = useState('')
  const [tempSelected, setTempSelected] = useState<string[]>(initialSelectedIds)

  useEffect(() => {
    if (isOpen) {
      setTempSelected(initialSelectedIds)
      setSearch('')
    }
  }, [isOpen, initialSelectedIds])

  if (!isOpen) return null

  const filtered = files.filter((f) =>
    f.filename.toLowerCase().includes(search.toLowerCase()),
  )

  const toggle = (id: string) => {
    setTempSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center ws-modal-overlay"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="ws-modal flex flex-col"
        style={{ width: '480px', maxHeight: '580px' }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="ws-side-panel-header">
          <div>
            <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
              Документы дела
            </h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
              Выберите документы для анализа в этом чате
            </p>
          </div>
          <button type="button" onClick={onClose} className="ws-input-mic-btn" aria-label="Закрыть">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-4 py-2.5 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <div
            className="flex items-center gap-2 px-3 py-2 rounded-lg"
            style={{ backgroundColor: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            <Search className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Поиск по названию..."
              className="flex-1 text-sm outline-none bg-transparent"
              style={{ color: 'var(--color-text-primary)' }}
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-2">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-5 h-5 animate-spin" style={{ color: 'var(--color-text-muted)' }} />
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-12">
              <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                {files.length === 0 ? 'Нет документов в деле' : 'Ничего не найдено'}
              </p>
            </div>
          ) : (
            filtered.map((file) => {
              const isSelected = tempSelected.includes(file.id)
              return (
                <button
                  key={file.id}
                  type="button"
                  onClick={() => toggle(file.id)}
                  className={`ws-dropdown-item rounded-lg mx-1${isSelected ? ' ws-dropdown-item--selected' : ''}`}
                  style={{ borderBottom: 'none', marginBottom: '2px' }}
                >
                  <span
                    className="w-4 h-4 rounded border flex items-center justify-center flex-shrink-0"
                    style={{
                      borderColor: isSelected ? 'var(--color-link)' : 'var(--color-border-strong)',
                      backgroundColor: isSelected ? 'var(--color-link)' : 'transparent',
                    }}
                  >
                    {isSelected && <Check className="w-2.5 h-2.5 text-white" />}
                  </span>
                  <FileText
                    className="w-4 h-4 flex-shrink-0"
                    style={{ color: isSelected ? 'var(--color-link)' : 'var(--color-text-muted)' }}
                  />
                  <span
                    className="flex-1 text-sm truncate"
                    style={{ color: isSelected ? 'var(--color-text-primary)' : 'var(--color-text-secondary)' }}
                  >
                    {file.filename}
                  </span>
                  <span className="text-xs flex-shrink-0 uppercase" style={{ color: 'var(--color-text-muted)' }}>
                    {file.file_type}
                  </span>
                </button>
              )
            })
          )}
        </div>

        <div
          className="flex items-center justify-between px-5 py-3 border-t"
          style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
        >
          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            {tempSelected.length > 0 ? `Выбрано: ${tempSelected.length}` : 'Не выбрано'}
          </span>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose} className="ws-btn ws-btn-secondary">
              Отмена
            </button>
            <button
              type="button"
              onClick={() => onApply(tempSelected)}
              className="ws-btn ws-btn-primary"
            >
              {tempSelected.length > 0 ? `Применить (${tempSelected.length})` : 'Применить'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
