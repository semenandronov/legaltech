import { useEffect, useState } from 'react'
import {
  Check,
  ChevronRight,
  FileText,
  FolderOpen,
  Loader2,
  Search,
  X,
} from 'lucide-react'
import { getCaseFiles, getCasesList, type CaseListItem, type UploadedFile } from '@/services/api'

export interface CaseDocumentPickerModalProps {
  onClose: () => void
  onConfirm: (files: UploadedFile[], caseName: string) => void
  alreadySelectedIds: Set<string>
}

export function CaseDocumentPickerModal({
  onClose,
  onConfirm,
  alreadySelectedIds,
}: CaseDocumentPickerModalProps) {
  const [step, setStep] = useState<'cases' | 'files'>('cases')
  const [cases, setCases] = useState<CaseListItem[]>([])
  const [loadingCases, setLoadingCases] = useState(true)
  const [selectedCase, setSelectedCase] = useState<CaseListItem | null>(null)
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [loadingFiles, setLoadingFiles] = useState(false)
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set(alreadySelectedIds))
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    getCasesList(0, 100)
      .then((res) => setCases(res.cases ?? []))
      .catch(() => {})
      .finally(() => setLoadingCases(false))
  }, [])

  const handleSelectCase = async (caseItem: CaseListItem) => {
    setSelectedCase(caseItem)
    setStep('files')
    setLoadingFiles(true)
    try {
      const res = await getCaseFiles(caseItem.id)
      setFiles(res.files ?? [])
    } catch {
      setFiles([])
    } finally {
      setLoadingFiles(false)
    }
  }

  const toggleFile = (id: string) => {
    setCheckedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleConfirm = () => {
    const selected = files.filter((f) => checkedIds.has(f.id))
    onConfirm(selected, selectedCase?.title ?? '')
    onClose()
  }

  const filteredCases = cases.filter((c) =>
    (c.title ?? '').toLowerCase().includes(searchQuery.toLowerCase()),
  )
  const filteredFiles = files.filter((f) =>
    f.filename.toLowerCase().includes(searchQuery.toLowerCase()),
  )
  const newlySelected = files.filter((f) => checkedIds.has(f.id) && !alreadySelectedIds.has(f.id))

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center ws-modal-overlay"
      onClick={onClose}
    >
      <div
        className="ws-modal flex flex-col"
        style={{ width: '520px', maxHeight: '600px' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ws-side-panel-header">
          <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-text-muted)' }}>
            <button
              type="button"
              onClick={step === 'files' ? () => { setStep('cases'); setSearchQuery('') } : onClose}
              className="hover:text-[var(--color-text-primary)] transition-colors font-medium"
            >
              {step === 'files' ? '← Назад' : 'Дела'}
            </button>
            {step === 'files' && selectedCase && (
              <>
                <ChevronRight className="w-3.5 h-3.5" />
                <span className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
                  {selectedCase.title ?? 'Без названия'}
                </span>
              </>
            )}
          </div>
          <button type="button" onClick={onClose} className="ws-input-mic-btn" aria-label="Закрыть">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-4 py-2.5 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <div
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg"
            style={{ backgroundColor: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            <Search className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
            <input
              autoFocus
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={step === 'cases' ? 'Поиск по делам...' : 'Поиск по файлам...'}
              className="flex-1 bg-transparent outline-none text-sm"
              style={{ color: 'var(--color-text-primary)' }}
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {step === 'cases' ? (
            loadingCases ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-5 h-5 animate-spin" style={{ color: 'var(--color-text-muted)' }} />
              </div>
            ) : filteredCases.length === 0 ? (
              <div className="flex items-center justify-center py-12 text-sm" style={{ color: 'var(--color-text-muted)' }}>
                {searchQuery ? 'Ничего не найдено' : 'Нет дел'}
              </div>
            ) : (
              filteredCases.map((caseItem) => (
                <button
                  key={caseItem.id}
                  type="button"
                  onClick={() => { setSearchQuery(''); void handleSelectCase(caseItem) }}
                  className="ws-dropdown-item justify-between"
                >
                  <div className="flex items-center gap-3">
                    <FolderOpen className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                    <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                      {caseItem.title ?? 'Без названия'}
                    </span>
                  </div>
                  <ChevronRight className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--color-border-strong)' }} />
                </button>
              ))
            )
          ) : loadingFiles ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-5 h-5 animate-spin" style={{ color: 'var(--color-text-muted)' }} />
            </div>
          ) : filteredFiles.length === 0 ? (
            <div className="flex items-center justify-center py-12 text-sm" style={{ color: 'var(--color-text-muted)' }}>
              {searchQuery ? 'Ничего не найдено' : 'В деле нет файлов'}
            </div>
          ) : (
            filteredFiles.map((file) => (
              <button
                key={file.id}
                type="button"
                onClick={() => toggleFile(file.id)}
                className="ws-dropdown-item"
              >
                <div
                  className="w-4 h-4 rounded flex items-center justify-center flex-shrink-0"
                  style={{
                    border: checkedIds.has(file.id)
                      ? '1px solid var(--color-link)'
                      : '1px solid var(--color-border-strong)',
                    backgroundColor: checkedIds.has(file.id) ? 'var(--color-link)' : 'transparent',
                  }}
                >
                  {checkedIds.has(file.id) && <Check className="w-2.5 h-2.5" style={{ color: 'white' }} />}
                </div>
                <FileText className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                <span className="flex-1 text-sm truncate" style={{ color: 'var(--color-text-primary)' }}>
                  {file.filename}
                </span>
                {file.size != null && (
                  <span className="text-xs flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
                    {Math.round(file.size / 1024)}kb
                  </span>
                )}
              </button>
            ))
          )}
        </div>

        {step === 'files' && (
          <div
            className="flex items-center justify-between px-5 py-3 border-t"
            style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
          >
            <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
              {newlySelected.length > 0 ? `Выбрано: ${newlySelected.length}` : 'Выберите файлы'}
            </span>
            <button
              type="button"
              onClick={handleConfirm}
              disabled={newlySelected.length === 0}
              className="ws-btn ws-btn-primary"
            >
              Добавить
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
