import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { AssistantUIChat } from '../components/Chat/AssistantUIChat'
import { Home, FolderOpen, MessageSquare, Upload, ArrowLeft, Clock, FileText, ChevronRight, X } from 'lucide-react'
import { getChatSessions } from '../services/api'

type AssistMode = 'assist' | 'draft'

interface HistoryItem {
  case_id: string
  case_name: string
  last_message: string
  last_message_at: string
  message_count: number
}

const navItems = [
  { id: 'home', label: 'Главная', icon: Home, path: '/' },
  { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
  { id: 'assistant', label: 'Ассистент', icon: MessageSquare, path: '/assistant' },
]

function formatRelativeTime(dateStr: string): string {
  if (!dateStr) return '—'
  const date = new Date(dateStr)
  const now = new Date()
  const diff = Math.floor((now.getTime() - date.getTime()) / 1000)
  if (diff < 60) return 'только что'
  if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`
  if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`
  if (diff < 604800) return `${Math.floor(diff / 86400)} дн назад`
  return date.toLocaleDateString('ru-RU')
}

// ─────────────────────────────────────────────────────────
// Landing page (before chat starts)
// ─────────────────────────────────────────────────────────
interface LandingViewProps {
  mode: AssistMode
  onModeChange: (m: AssistMode) => void
  question: string
  onQuestionChange: (v: string) => void
  onSubmit: () => void
  files: File[]
  onFilesChange: (files: File[]) => void
  history: HistoryItem[]
  historyLoading: boolean
  onHistorySelect: (item: HistoryItem) => void
}

function LandingView({
  mode,
  onModeChange,
  question,
  onQuestionChange,
  onSubmit,
  files,
  onFilesChange,
  history,
  historyLoading,
  onHistorySelect,
}: LandingViewProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [question])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (question.trim()) onSubmit()
    }
  }

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(true)
  }, [])

  const handleDragLeave = useCallback(() => setDragging(false), [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const newFiles = Array.from(e.dataTransfer.files)
    onFilesChange([...files, ...newFiles])
  }, [files, onFilesChange])

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      onFilesChange([...files, ...Array.from(e.target.files)])
    }
  }

  const removeFile = (idx: number) => {
    onFilesChange(files.filter((_, i) => i !== idx))
  }

  return (
    <div className="flex-1 overflow-y-auto" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
      <div className="max-w-3xl mx-auto px-6 py-12">

        {/* Mode tabs */}
        <div className="flex items-center gap-2 mb-8">
          {(['assist', 'draft'] as AssistMode[]).map((m) => (
            <button
              key={m}
              onClick={() => onModeChange(m)}
              className="px-5 py-2 text-sm font-medium rounded-full transition-all duration-150"
              style={{
                backgroundColor: mode === m ? 'var(--color-text-primary)' : 'transparent',
                color: mode === m ? 'var(--color-bg-primary)' : 'var(--color-text-secondary)',
                border: `1px solid ${mode === m ? 'var(--color-text-primary)' : 'var(--color-border)'}`,
              }}
            >
              {m === 'assist' ? 'Ассистент' : 'Черновик'}
            </button>
          ))}
        </div>

        {/* Input card */}
        <div
          className="rounded-2xl border overflow-hidden mb-4"
          style={{
            backgroundColor: 'var(--color-bg-elevated)',
            borderColor: 'var(--color-border)',
            boxShadow: '0 1px 4px 0 rgba(0,0,0,0.06)',
          }}
        >
          <div className="px-5 pt-5 pb-3">
            <textarea
              ref={textareaRef}
              value={question}
              onChange={(e) => onQuestionChange(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                mode === 'assist'
                  ? 'Задайте вопрос по документам или базе знаний...'
                  : 'Опишите, какой документ нужно составить...'
              }
              rows={3}
              className="w-full resize-none outline-none text-base leading-relaxed bg-transparent"
              style={{
                color: 'var(--color-text-primary)',
                fontFamily: 'var(--font-body)',
                minHeight: '80px',
              }}
            />
          </div>

          {/* Attached files */}
          {files.length > 0 && (
            <div className="px-5 pb-3 flex flex-wrap gap-2">
              {files.map((f, i) => (
                <div
                  key={i}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border"
                  style={{
                    backgroundColor: 'var(--color-bg-tertiary)',
                    borderColor: 'var(--color-border)',
                    color: 'var(--color-text-secondary)',
                  }}
                >
                  <FileText className="w-3 h-3" />
                  <span className="max-w-[140px] truncate">{f.name}</span>
                  <button onClick={() => removeFile(i)} className="ml-0.5 hover:text-red-500 transition-colors">
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Footer */}
          <div
            className="flex items-center justify-between px-5 py-3 border-t"
            style={{ borderTopColor: 'var(--color-border)' }}
          >
            <button
              onClick={() => fileInputRef.current?.click()}
              className="flex items-center gap-2 text-sm font-medium transition-colors duration-150 hover:opacity-70"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <Upload className="w-4 h-4" />
              Прикрепить файлы
            </button>
            <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleFileInput} />

            <button
              onClick={onSubmit}
              disabled={!question.trim()}
              className="px-5 py-2 rounded-lg text-sm font-medium transition-all duration-150 disabled:opacity-40"
              style={{
                backgroundColor: 'var(--color-text-primary)',
                color: 'var(--color-bg-primary)',
              }}
            >
              {mode === 'assist' ? 'Спросить' : 'Составить'}
            </button>
          </div>
        </div>

        {/* Drag-and-drop zone */}
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className="flex flex-col items-center justify-center gap-2 py-6 rounded-xl border-2 border-dashed cursor-pointer transition-all duration-150 mb-10"
          style={{
            borderColor: dragging ? 'var(--color-text-primary)' : 'var(--color-border)',
            backgroundColor: dragging ? 'var(--color-bg-hover)' : 'transparent',
            color: 'var(--color-text-secondary)',
          }}
        >
          <Upload className="w-5 h-5" style={{ color: 'var(--color-text-muted)' }} />
          <p className="text-sm font-medium">Перетащите файлы или нажмите для загрузки</p>
          <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            Выберите файлы с компьютера или из дел — PDF, DOCX, TXT до 30 МБ
          </p>
        </div>

        {/* History */}
        <div>
          <h3
            className="text-xs font-semibold mb-4 uppercase"
            style={{ color: 'var(--color-text-muted)', letterSpacing: '0.08em' }}
          >
            История
          </h3>

          {historyLoading ? (
            <div className="flex items-center justify-center py-12">
              <div
                className="w-5 h-5 border-2 rounded-full animate-spin"
                style={{ borderColor: 'var(--color-border)', borderTopColor: 'var(--color-text-primary)' }}
              />
            </div>
          ) : history.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center" style={{ color: 'var(--color-text-muted)' }}>
              <Clock className="w-8 h-8 mb-3 opacity-40" />
              <p className="text-sm">История пуста — задайте первый вопрос</p>
            </div>
          ) : (
            <div
              className="rounded-xl border overflow-hidden"
              style={{ backgroundColor: 'var(--color-bg-elevated)', borderColor: 'var(--color-border)' }}
            >
              {/* Header */}
              <div
                className="grid text-xs font-semibold uppercase px-5 py-3 border-b"
                style={{
                  gridTemplateColumns: '1fr 120px 80px 110px 20px',
                  borderBottomColor: 'var(--color-border)',
                  color: 'var(--color-text-muted)',
                  letterSpacing: '0.07em',
                }}
              >
                <span>Название</span>
                <span>Дело</span>
                <span className="text-center">Сообщ.</span>
                <span>Дата</span>
                <span />
              </div>

              {/* Rows */}
              {history.map((item, idx) => (
                <button
                  key={idx}
                  onClick={() => onHistorySelect(item)}
                  className="w-full grid text-sm px-5 py-3.5 text-left transition-colors duration-100 border-b last:border-0 hover:bg-[var(--color-bg-hover)]"
                  style={{ gridTemplateColumns: '1fr 120px 80px 110px 20px', borderBottomColor: 'var(--color-border)' }}
                >
                  <span className="truncate pr-4 font-medium" style={{ color: 'var(--color-text-primary)' }}>
                    {item.last_message || 'Без названия'}
                  </span>
                  <span className="truncate pr-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                    {item.case_name || '—'}
                  </span>
                  <span className="text-center text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                    {item.message_count}
                  </span>
                  <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    {formatRelativeTime(item.last_message_at)}
                  </span>
                  <ChevronRight className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────
const GlobalAssistantPage = () => {
  const navigate = useNavigate()
  const [mode, setMode] = useState<AssistMode>('assist')
  const [question, setQuestion] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [chatActive, setChatActive] = useState(false)
  const [activeQuery, setActiveQuery] = useState('')
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)

  useEffect(() => {
    getChatSessions()
      .then((data) => setHistory(Array.isArray(data) ? data : []))
      .catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false))
  }, [])

  const handleSubmit = () => {
    if (!question.trim()) return
    setActiveQuery(question)
    setChatActive(true)
  }

  const handleHistorySelect = (item: HistoryItem) => {
    if (item.case_id) navigate(`/cases/${item.case_id}/chat`)
  }

  const handleBack = () => {
    setChatActive(false)
    setQuestion('')
    setActiveQuery('')
  }

  return (
    <div className="h-screen flex overflow-hidden" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
      <UnifiedSidebar navItems={navItems} title="Legal AI" />

      <div className="flex-1 flex flex-col overflow-hidden">
        {chatActive ? (
          <>
            {/* Chat header */}
            <div
              className="flex items-center gap-3 px-6 py-4 border-b shrink-0"
              style={{ borderBottomColor: 'var(--color-border)' }}
            >
              <button
                onClick={handleBack}
                className="flex items-center gap-2 text-sm font-medium transition-opacity hover:opacity-70"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                <ArrowLeft className="w-4 h-4" />
                Назад
              </button>
              <span
                className="text-sm truncate max-w-sm"
                style={{ color: 'var(--color-text-muted)' }}
                title={activeQuery}
              >
                {activeQuery}
              </span>
            </div>
            <div className="flex-1 overflow-hidden">
              <AssistantUIChat initialQuery={activeQuery} />
            </div>
          </>
        ) : (
          <LandingView
            mode={mode}
            onModeChange={setMode}
            question={question}
            onQuestionChange={setQuestion}
            onSubmit={handleSubmit}
            files={files}
            onFilesChange={setFiles}
            history={history}
            historyLoading={historyLoading}
            onHistorySelect={handleHistorySelect}
          />
        )}
      </div>
    </div>
  )
}

export default GlobalAssistantPage
