import { FileText, Table2, BarChart3, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import type { NavigateFunction } from 'react-router-dom'
import type { WorkflowArtifactsPayload } from '../../workflow/workflowLiveHelpers'
import { artifactDisplayName } from '../../workflow/workflowLiveHelpers'

type ArtifactGroupKey = keyof WorkflowArtifactsPayload

export function WorkflowArtifactCards(props: {
  artifacts: WorkflowArtifactsPayload
  navigate: NavigateFunction
  /** Закодированный путь для query returnTo, например /cases/xxx/chat */
  returnChatPath: string
}) {
  const { artifacts, navigate, returnChatPath } = props
  const returnParam = encodeURIComponent(returnChatPath)

  const groups: Array<{
    key: ArtifactGroupKey
    label: string
    icon: typeof FileText
  }> = [
    { key: 'documents', label: 'Документ', icon: FileText },
    { key: 'tables', label: 'Таблица', icon: Table2 },
    { key: 'reports', label: 'Отчёт', icon: BarChart3 },
    { key: 'checks', label: 'Проверка', icon: ShieldCheck },
  ]

  const total = groups.reduce((acc, g) => acc + (artifacts[g.key]?.length || 0), 0)
  if (!total) return null

  const openArtifact = (groupKey: ArtifactGroupKey, artifact: Record<string, unknown>) => {
    const caseId = artifact.case_id || artifact.caseId || (artifact.meta as Record<string, unknown> | undefined)?.case_id
    const docType = String(artifact.type || '').toLowerCase()
    const storage = String(artifact.storage || '').toLowerCase()

    if (groupKey === 'documents' && docType === 'document_draft' && storage === 'global_assistant') {
      toast.info('Файл сохранён в хранилище ассистента — выберите его в файлах при следующем запросе.')
      return
    }

    // Черновик workflow: в редакторе дела — запись Document; дубль — File в деле
    if (groupKey === 'documents' && caseId && docType === 'document_draft' && storage === 'case') {
      const editorDocId = artifact.document_id || (artifact.document as { id?: string } | undefined)?.id
      if (editorDocId) {
        navigate(`/cases/${caseId}/editor/${String(editorDocId)}?returnTo=${returnParam}`)
        return
      }
      if (artifact.id) {
        navigate(`/cases/${caseId}/workflow-file/${String(artifact.id)}?returnTo=${returnParam}`)
        return
      }
    }

    if (groupKey === 'documents' && caseId) {
      const editorDocId = artifact.document_id || (artifact.document as { id?: string } | undefined)?.id
      if (editorDocId) {
        navigate(`/cases/${caseId}/editor/${String(editorDocId)}?returnTo=${returnParam}`)
        return
      }
    }

    const reviewId =
      artifact.review_id ||
      artifact.tabular_review_id ||
      artifact.table_id ||
      (artifact.tabular_review as { id?: string } | undefined)?.id ||
      (artifact.meta as Record<string, unknown> | undefined)?.review_id ||
      artifact.id

    if (groupKey === 'tables' && caseId && reviewId) {
      navigate(`/cases/${caseId}/tabular-review/${reviewId}?returnTo=${returnParam}`)
      return
    }

    const url = artifact.url || artifact.preview_url || artifact.link
    if (typeof url === 'string' && /^https?:\/\//i.test(url)) {
      window.open(url, '_blank', 'noopener,noreferrer')
      return
    }

    toast.error('Не удалось открыть артефакт: нет привязки к делу.')
  }

  return (
    <div className="mt-4 flex flex-wrap gap-2.5">
      {groups.flatMap((group) => {
        const rows = artifacts[group.key] || []
        if (!rows.length) return []
        const Icon = group.icon
        return rows.map((artifact: Record<string, unknown>, idx: number) => {
          const name = artifactDisplayName(artifact, `${group.label} ${idx + 1}`)
          const sub =
            typeof artifact.word_count === 'number'
              ? `${artifact.word_count} слов`
              : artifact.row_count != null
                ? `${artifact.row_count} строк`
                : undefined
          return (
            <button
              key={`${group.key}-${String(artifact.id) || idx}`}
              type="button"
              onClick={() => openArtifact(group.key, artifact)}
              className="group flex flex-col items-start gap-1.5 w-[min(100%,280px)] rounded-xl border text-left px-3.5 py-3 transition-all duration-150 hover:shadow-md hover:border-indigo-200 hover:bg-white focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/40"
              style={{
                borderColor: '#E5E7EB',
                backgroundColor: '#FFFFFF',
                boxShadow: '0 1px 2px rgba(15, 23, 42, 0.06)',
              }}
            >
              <div className="flex items-start gap-2.5 w-full min-w-0">
                <span
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
                  style={{ backgroundColor: '#EEF2FF', color: '#4F46E5' }}
                >
                  <Icon className="h-5 w-5" strokeWidth={1.75} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium leading-snug line-clamp-2" style={{ color: '#111827' }}>
                    {name}
                  </div>
                  {sub && (
                    <div className="text-xs mt-0.5" style={{ color: '#6B7280' }}>
                      {sub}
                    </div>
                  )}
                </div>
              </div>
              <span className="text-[11px] font-medium uppercase tracking-wide" style={{ color: '#A5B4FC' }}>
                {group.label}
              </span>
            </button>
          )
        })
      })}
    </div>
  )
}
