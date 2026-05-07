/**
 * Full-page text editor for a case file (e.g. workflow document_draft saved as File).
 * Opens from global assistant artifact cards with ?returnTo=/assistant
 */
import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, FileText, Loader2, Save, MessageSquare, FileEdit, BookOpen, Workflow } from 'lucide-react'
import { toast } from 'sonner'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { getCaseFiles, getDocumentContent, updateCaseFileText } from '../services/api'

const CaseWorkflowFilePage = () => {
  const { caseId, fileId } = useParams<{ caseId: string; fileId: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const returnTo = searchParams.get('returnTo') || '/assistant'

  const [title, setTitle] = useState('Документ')
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  const goBack = useCallback(() => {
    try {
      const decoded = decodeURIComponent(returnTo)
      navigate(decoded.startsWith('/') ? decoded : `/${decoded}`)
    } catch {
      navigate('/assistant')
    }
  }, [navigate, returnTo])

  useEffect(() => {
    if (!caseId || !fileId) {
      toast.error('Неверная ссылка')
      navigate('/cases')
      return
    }

    let cancelled = false
    ;(async () => {
      setLoading(true)
      const delays = [0, 450, 900, 1400]
      let lastErr: unknown
      let loaded = false
      for (const d of delays) {
        if (cancelled) break
        if (d > 0) await new Promise((r) => setTimeout(r, d))
        try {
          const filesRes = await getCaseFiles(caseId)
          const meta = filesRes.files?.find((f: { id: string }) => f.id === fileId)
          if (meta?.filename) {
            setTitle(meta.filename.replace(/\.txt$/i, '') || meta.filename)
          }
          const blob = await getDocumentContent(caseId, fileId)
          const t = await blob.text()
          if (!cancelled) {
            setText(t)
            setDirty(false)
            loaded = true
            break
          }
        } catch (e: unknown) {
          lastErr = e
        }
      }
      if (!loaded && lastErr && !cancelled) {
        console.error(lastErr)
        toast.error('Не удалось загрузить файл')
        goBack()
      }
      if (!cancelled) setLoading(false)
    })()
    return () => {
      cancelled = true
    }
  }, [caseId, fileId, navigate, goBack])

  const handleSave = async () => {
    if (!caseId || !fileId) return
    setSaving(true)
    try {
      await updateCaseFileText(caseId, fileId, text)
      setDirty(false)
      toast.success('Сохранено')
    } catch (e: unknown) {
      console.error(e)
      toast.error('Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const navItems = caseId
    ? [
        { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
        { id: 'editor', label: 'Редактор', icon: FileEdit, path: `/cases/${caseId}/editor` },
        { id: 'playbooks', label: 'Playbooks', icon: BookOpen, path: `/cases/${caseId}/playbooks` },
        { id: 'workflows', label: 'Workflows', icon: Workflow, path: `/cases/${caseId}/workflows` },
      ]
    : []

  if (loading) {
    return (
      <div className="h-screen flex bg-white">
        {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen flex overflow-hidden bg-white">
      {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
      <div className="flex-1 flex flex-col min-w-0" style={{ backgroundColor: 'var(--color-bg-primary, #fafafa)' }}>
        <header
          className="flex items-center justify-between gap-3 px-4 py-3 border-b shrink-0 bg-white"
          style={{ borderColor: '#E5E7EB' }}
        >
          <div className="flex items-center gap-3 min-w-0">
            <button
              type="button"
              onClick={goBack}
              className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-sm font-medium transition-colors hover:bg-gray-100 shrink-0"
              style={{ color: '#374151' }}
            >
              <ArrowLeft className="w-4 h-4" />
              Назад в переписку
            </button>
            <div className="h-6 w-px bg-gray-200 shrink-0" />
            <div className="flex items-center gap-2 min-w-0">
              <FileText className="w-5 h-5 shrink-0 text-indigo-600" />
              <h1 className="text-base font-semibold truncate" style={{ color: '#111827' }}>
                {title}
              </h1>
            </div>
          </div>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving || !dirty}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Сохранить
          </button>
        </header>

        <div className="flex-1 p-4 min-h-0">
          <textarea
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              setDirty(true)
            }}
            className="w-full h-full min-h-[320px] resize-none rounded-xl border p-4 text-sm leading-relaxed font-mono shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400"
            style={{
              borderColor: '#E5E7EB',
              backgroundColor: '#fff',
              color: '#111827',
            }}
            spellCheck
            placeholder="Текст документа…"
          />
        </div>
      </div>
    </div>
  )
}

export default CaseWorkflowFilePage
