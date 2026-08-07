'use client'

import { useMemo, useState } from 'react'
import { Loader2 } from 'lucide-react'
import type { CellComment } from '@/services/tabularReviewApi'

export interface MikeCellCommentsSectionProps {
  comments: CellComment[]
  loading: boolean
  submitting: boolean
  currentUserId?: string | null
  readOnly?: boolean
  onSubmit: (text: string) => Promise<void> | void
  onResolve: (commentId: string) => Promise<void> | void
  onUnresolve: (commentId: string) => Promise<void> | void
  onDelete: (commentId: string) => Promise<void> | void
}

function formatCommentTime(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('ru-RU', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return ''
  }
}

export function MikeCellCommentsSection({
  comments,
  loading,
  submitting,
  currentUserId,
  readOnly = false,
  onSubmit,
  onResolve,
  onUnresolve,
  onDelete,
}: MikeCellCommentsSectionProps) {
  const [draft, setDraft] = useState('')
  const [showResolved, setShowResolved] = useState(false)
  const [actionId, setActionId] = useState<string | null>(null)

  const visibleComments = useMemo(() => {
    const filtered = showResolved ? comments : comments.filter((c) => !c.is_resolved)
    return [...filtered].sort((a, b) => {
      const ta = a.created_at ? Date.parse(a.created_at) : 0
      const tb = b.created_at ? Date.parse(b.created_at) : 0
      return tb - ta
    })
  }, [comments, showResolved])

  const resolvedCount = comments.filter((c) => c.is_resolved).length
  const openCount = comments.length - resolvedCount

  const handleSubmit = async () => {
    const text = draft.trim()
    if (!text || submitting) return
    await onSubmit(text)
    setDraft('')
  }

  const runAction = async (commentId: string, action: () => Promise<void> | void) => {
    setActionId(commentId)
    try {
      await action()
    } finally {
      setActionId(null)
    }
  }

  return (
    <section className="ws-mike-cell-comments">
      <div className="ws-mike-cell-comments-header">
        <p className="ws-mike-cell-detail-popover-label">
          Комментарии
          {openCount > 0 ? ` · ${openCount}` : ''}
        </p>
        {resolvedCount > 0 && (
          <button
            type="button"
            className="ws-mike-cell-comments-toggle"
            onClick={() => setShowResolved((v) => !v)}
          >
            {showResolved ? 'Скрыть закрытые' : `Показать закрытые (${resolvedCount})`}
          </button>
        )}
      </div>

      <div className="ws-mike-cell-comments-list" aria-busy={loading}>
        {loading && comments.length === 0 ? (
          <div className="ws-mike-cell-comments-skeleton">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-400" aria-hidden />
            <span>Загрузка…</span>
          </div>
        ) : visibleComments.length === 0 ? (
          <p className="ws-mike-cell-detail-popover-text ws-mike-cell-detail-popover-text--muted">
            Пока нет комментариев. Напишите, почему важна эта ячейка.
          </p>
        ) : (
          visibleComments.map((comment) => {
            const isOwn =
              Boolean(currentUserId) && comment.created_by_id === currentUserId
            const busy = actionId === comment.id
            return (
              <article
                key={comment.id}
                className={`ws-mike-cell-comment ${
                  comment.is_resolved ? 'ws-mike-cell-comment--resolved' : ''
                }`}
              >
                <div className="ws-mike-cell-comment-meta">
                  <span className="ws-mike-cell-comment-author">
                    {comment.created_by || 'Пользователь'}
                  </span>
                  <span className="ws-mike-cell-comment-time">
                    {formatCommentTime(comment.created_at)}
                  </span>
                  {comment.is_resolved && (
                    <span className="ws-mike-cell-comment-badge">Закрыт</span>
                  )}
                </div>
                <p className="ws-mike-cell-comment-text">{comment.comment_text}</p>
                {!readOnly && (
                <div className="ws-mike-cell-comment-actions">
                  {comment.is_resolved ? (
                    <button
                      type="button"
                      disabled={busy}
                      className="ws-mike-cell-comment-action"
                      onClick={() => void runAction(comment.id, () => onUnresolve(comment.id))}
                    >
                      Открыть снова
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={busy}
                      className="ws-mike-cell-comment-action"
                      onClick={() => void runAction(comment.id, () => onResolve(comment.id))}
                    >
                      Закрыть
                    </button>
                  )}
                  {isOwn && (
                    <button
                      type="button"
                      disabled={busy}
                      className="ws-mike-cell-comment-action ws-mike-cell-comment-action--danger"
                      onClick={() => void runAction(comment.id, () => onDelete(comment.id))}
                    >
                      Удалить
                    </button>
                  )}
                </div>
                )}
              </article>
            )
          })
        )}
      </div>

      {readOnly ? (
        <p className="ws-mike-cell-detail-popover-text ws-mike-cell-detail-popover-text--muted mt-2">
          Режим просмотра — комментирование недоступно.
        </p>
      ) : (
      <div className="ws-mike-cell-comments-composer">
        <textarea
          value={draft}
          rows={2}
          placeholder="Комментарий к ячейке…"
          className="ws-mike-cell-comments-input"
          disabled={submitting}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
              event.preventDefault()
              void handleSubmit()
            }
          }}
        />
        <div className="ws-mike-cell-comments-composer-row">
          <span className="ws-mike-cell-comments-hint">⌘/Ctrl + Enter</span>
          <button
            type="button"
            className="ws-mike-cell-comments-submit"
            disabled={submitting || !draft.trim()}
            onClick={() => void handleSubmit()}
          >
            {submitting ? 'Отправка…' : 'Отправить'}
          </button>
        </div>
      </div>
      )}
    </section>
  )
}
