import { useCallback, useEffect, useMemo, useState } from 'react'
import { X, Receipt, Plus, ChevronLeft, ChevronRight, Loader2, Search } from 'lucide-react'
import { toast } from 'sonner'
import type { OperationsAvailableFile, OperationsSessionSummary } from '@/services/operationsApi'

export type { OperationsSessionSummary } from '@/services/operationsApi'

type HubStep = 'list' | 'pick'

interface CaseOperationsHubModalProps {
  open: boolean
  onClose: () => void
  sessions: OperationsSessionSummary[]
  loadingSessions?: boolean
  files: OperationsAvailableFile[]
  loadingFiles?: boolean
  initialStep?: HubStep
  onOpenFile: (fileId: string) => void
}

function formatSessionDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', year: 'numeric' })
}

export function CaseOperationsHubModal({
  open,
  onClose,
  sessions,
  loadingSessions = false,
  files,
  loadingFiles = false,
  initialStep = 'list',
  onOpenFile,
}: CaseOperationsHubModalProps) {
  const [step, setStep] = useState<HubStep>(initialStep)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  const resetFlow = useCallback(() => {
    setStep(initialStep)
    setSelectedId(null)
    setSearch('')
  }, [initialStep])

  useEffect(() => {
    if (!open) {
      resetFlow()
      return
    }
    setStep(initialStep)
    setSelectedId(null)
    setSearch('')
  }, [open, initialStep, resetFlow])

  const filteredFiles = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return files
    return files.filter((file) => file.filename.toLowerCase().includes(q))
  }, [files, search])

  const handlePickConfirm = () => {
    if (!selectedId) {
      toast.error('Выберите выписку')
      return
    }
    onClose()
    onOpenFile(selectedId)
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center p-4">
      <button type="button" className="absolute inset-0 bg-black/30" onClick={onClose} aria-label="Закрыть" />
      <div className="relative w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden rounded-2xl bg-white shadow-xl border border-gray-100">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            {step === 'pick' && (
              <button
                type="button"
                onClick={() => setStep('list')}
                className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"
                aria-label="Назад"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
            )}
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-gray-900 truncate">
                {step === 'list' ? 'Выписки по делу' : 'Выберите выписку'}
              </h2>
              {step === 'list' && (
                <p className="text-xs text-gray-500 mt-0.5">
                  Операции из банковских выписок — как в PDF
                </p>
              )}
            </div>
          </div>
          <button type="button" onClick={onClose} className="p-1 rounded-lg hover:bg-gray-100 shrink-0">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {step === 'list' && (
            <>
              {loadingSessions ? (
                <div className="flex justify-center py-12">
                  <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
                </div>
              ) : sessions.length === 0 ? (
                <div className="text-center py-6">
                  <div className="w-12 h-12 rounded-xl mx-auto mb-4 flex items-center justify-center bg-gray-50">
                    <Receipt className="h-6 w-6 text-gray-400" />
                  </div>
                  <p className="text-sm font-medium text-gray-900 mb-1">
                    Выписок в этом деле пока нет
                  </p>
                  <p className="text-sm text-gray-500 mb-6 max-w-sm mx-auto">
                    Загрузите PDF-выписку в документы дела, дождитесь оцифровки и откройте реестр операций.
                  </p>
                  <button
                    type="button"
                    onClick={() => setStep('pick')}
                    disabled={loadingFiles || files.length === 0}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium bg-gray-900 text-white hover:bg-gray-800 disabled:opacity-40"
                  >
                    <Plus className="h-4 w-4" />
                    Открыть выписку
                  </button>
                  {files.length === 0 && !loadingFiles && (
                    <p className="text-xs text-gray-400 mt-4">Нет оцифрованных выписок</p>
                  )}
                </div>
              ) : (
                <>
                  <div className="mb-4">
                    <button
                      type="button"
                      onClick={() => setStep('pick')}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border border-gray-200 text-gray-800 hover:bg-gray-50"
                    >
                      <Plus className="h-3.5 w-3.5" />
                      Другая выписка
                    </button>
                  </div>
                  <ul className="space-y-2">
                    {sessions.map((session) => (
                      <li key={session.file_id}>
                        <button
                          type="button"
                          onClick={() => {
                            onClose()
                            onOpenFile(session.file_id)
                          }}
                          className="w-full flex items-center gap-3 px-4 py-3 rounded-xl border border-gray-200 hover:bg-gray-50 text-left transition-colors group"
                        >
                          <Receipt className="h-4 w-4 shrink-0 text-gray-400" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-gray-900 truncate">
                              {session.filename || 'Выписка'}
                            </p>
                            <p className="text-xs text-gray-500 mt-0.5">
                              {session.transaction_count != null
                                ? `${session.transaction_count} операций`
                                : 'Операции'}
                              {session.date_min && session.date_max
                                ? ` · ${session.date_min} — ${session.date_max}`
                                : ''}
                              {session.updated_at
                                ? ` · обновлено ${formatSessionDate(session.updated_at)}`
                                : ''}
                            </p>
                          </div>
                          <ChevronRight className="h-4 w-4 shrink-0 text-gray-300 group-hover:text-gray-500" />
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}

          {step === 'pick' && (
            <>
              <div className="mb-3">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Поиск выписки…"
                    className="w-full rounded-lg border border-gray-200 py-2 pl-9 pr-3 text-sm"
                  />
                </div>
              </div>

              <div className="max-h-[360px] overflow-y-auto -mx-1 px-1" role="radiogroup" aria-label="Выписки">
                {loadingFiles ? (
                  <div className="flex items-center justify-center py-12 text-gray-500 text-sm gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Загрузка выписок…
                  </div>
                ) : files.length === 0 ? (
                  <div className="py-12 text-center text-sm text-gray-500 px-4">
                    Нет оцифрованных выписок. Загрузите PDF-выписки в документы дела и дождитесь обработки.
                  </div>
                ) : filteredFiles.length === 0 ? (
                  <div className="py-12 text-center text-sm text-gray-500">Ничего не найдено</div>
                ) : (
                  filteredFiles.map((file) => {
                    const checked = selectedId === file.file_id
                    return (
                      <button
                        key={file.file_id}
                        type="button"
                        role="radio"
                        aria-checked={checked}
                        onClick={() => setSelectedId(file.file_id)}
                        className="w-full flex items-start gap-3 px-3 py-2.5 rounded-lg hover:bg-gray-50 text-left"
                      >
                        <span
                          className={`mt-0.5 h-4 w-4 rounded-full border flex items-center justify-center shrink-0 ${
                            checked ? 'border-gray-900' : 'border-gray-300'
                          }`}
                        >
                          {checked ? <span className="h-2 w-2 rounded-full bg-gray-900" /> : null}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium text-gray-900 truncate">{file.filename}</div>
                          <div className="text-xs text-gray-500 mt-0.5">
                            {file.transaction_count} операций
                            {file.date_min && file.date_max ? ` · ${file.date_min} — ${file.date_max}` : ''}
                          </div>
                        </div>
                      </button>
                    )
                  })
                )}
              </div>
            </>
          )}
        </div>

        {step === 'pick' && (
          <div className="flex items-center justify-between gap-3 px-5 py-4 border-t border-gray-100 bg-gray-50/80 shrink-0">
            <span className="text-xs text-gray-500">{selectedId ? '1 выписка' : 'Не выбрано'}</span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-sm rounded-lg border border-gray-200 hover:bg-white"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={handlePickConfirm}
                disabled={!selectedId}
                className="px-4 py-2 text-sm rounded-lg bg-gray-900 text-white hover:bg-gray-800 disabled:opacity-50"
              >
                Открыть
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
