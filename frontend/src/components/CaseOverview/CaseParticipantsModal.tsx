'use client'

import { useCallback, useEffect, useState } from 'react'
import { Loader2, UserPlus, X } from 'lucide-react'
import { toast } from 'sonner'
import {
  extractErrorMessage,
  getCaseMembers,
  inviteCaseMember,
  removeCaseMember,
  updateCaseMemberRole,
  type CaseMemberItem,
} from '@/services/api'
import { useAuth } from '@/contexts/AuthContext'

interface CaseParticipantsModalProps {
  open: boolean
  caseId: string
  onClose: () => void
}

const ROLE_LABEL: Record<string, string> = {
  owner: 'Владелец',
  editor: 'Редактор',
  viewer: 'Зритель',
}

function initials(name?: string | null, email?: string) {
  const source = (name || email || '?').trim()
  const parts = source.split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return source.slice(0, 2).toUpperCase()
}

export function CaseParticipantsModal({ open, caseId, onClose }: CaseParticipantsModalProps) {
  const { user } = useAuth()
  const [loading, setLoading] = useState(false)
  const [members, setMembers] = useState<CaseMemberItem[]>([])
  const [myRole, setMyRole] = useState<string | null>(null)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'editor' | 'viewer'>('editor')
  const [submitting, setSubmitting] = useState(false)

  const canManage = myRole === 'owner'

  const load = useCallback(async () => {
    if (!caseId) return
    setLoading(true)
    try {
      const data = await getCaseMembers(caseId)
      setMembers(data.members || [])
      setMyRole(data.my_role ?? null)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Не удалось загрузить участников'
      toast.error(message)
    } finally {
      setLoading(false)
    }
  }, [caseId])

  useEffect(() => {
    if (open) {
      void load()
      setEmail('')
    }
  }, [open, load])

  if (!open) return null

  const handleInvite = async () => {
    const trimmed = email.trim()
    if (!trimmed) {
      toast.error('Укажите email')
      return
    }
    setSubmitting(true)
    try {
      await inviteCaseMember(caseId, trimmed, role)
      toast.success('Участник добавлен')
      setEmail('')
      await load()
    } catch (err: unknown) {
      toast.error(extractErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-xl border border-gray-200 bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="case-participants-title"
      >
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <div>
            <h2 id="case-participants-title" className="text-base font-medium text-gray-900">
              Участники дела
            </h2>
            <p className="mt-0.5 text-xs text-gray-500">Доступ к документам, таблице и комментариям</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-gray-400 hover:bg-gray-50 hover:text-gray-700"
            aria-label="Закрыть"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[70vh] space-y-5 overflow-y-auto px-5 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-10 text-gray-400">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : (
            <>
              <section>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-400">Люди</h3>
                {members.length <= 1 ? (
                  <p className="mb-3 text-sm text-gray-500">
                    Пока только вы. Добавьте коллегу по email — аккаунт должен уже существовать.
                  </p>
                ) : null}
                <ul className="space-y-2">
                  {members.map((m) => {
                    const isYou = user?.id === m.user_id
                    return (
                      <li
                        key={m.user_id}
                        className="flex items-center gap-3 rounded-lg border border-gray-100 px-3 py-2"
                      >
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-100 text-xs font-medium text-gray-600">
                          {initials(m.full_name, m.email)}
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-gray-900">
                            {m.full_name || m.email}
                            {isYou ? (
                              <span className="ml-1.5 text-xs font-normal text-gray-400">Вы</span>
                            ) : null}
                          </p>
                          <p className="truncate text-xs text-gray-500">{m.email}</p>
                        </div>
                        {canManage && m.role !== 'owner' ? (
                          <select
                            className="rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-700"
                            value={m.role}
                            onChange={(e) => {
                              void (async () => {
                                try {
                                  await updateCaseMemberRole(
                                    caseId,
                                    m.user_id,
                                    e.target.value as 'editor' | 'viewer',
                                  )
                                  await load()
                                } catch (err: unknown) {
                                  toast.error(err instanceof Error ? err.message : 'Ошибка смены роли')
                                }
                              })()
                            }}
                          >
                            <option value="editor">Редактор</option>
                            <option value="viewer">Зритель</option>
                          </select>
                        ) : (
                          <span className="text-xs text-gray-500">{ROLE_LABEL[m.role] || m.role}</span>
                        )}
                        {canManage && m.role !== 'owner' && !isYou ? (
                          <button
                            type="button"
                            className="text-xs text-gray-400 hover:text-red-600"
                            onClick={() => {
                              void (async () => {
                                try {
                                  await removeCaseMember(caseId, m.user_id)
                                  toast.success('Участник исключён')
                                  await load()
                                } catch (err: unknown) {
                                  toast.error(err instanceof Error ? err.message : 'Не удалось исключить')
                                }
                              })()
                            }}
                          >
                            Исключить
                          </button>
                        ) : null}
                      </li>
                    )
                  })}
                </ul>
              </section>

              {canManage ? (
                <section>
                  <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-400">
                    Добавить
                  </h3>
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="email@company.com"
                      className="min-w-0 flex-1 rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-400"
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') void handleInvite()
                      }}
                    />
                    <select
                      value={role}
                      onChange={(e) => setRole(e.target.value as 'editor' | 'viewer')}
                      className="rounded-md border border-gray-200 px-2 py-2 text-sm"
                    >
                      <option value="editor">Редактор</option>
                      <option value="viewer">Зритель</option>
                    </select>
                    <button
                      type="button"
                      disabled={submitting}
                      onClick={() => void handleInvite()}
                      className="inline-flex items-center justify-center gap-1.5 rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
                    >
                      {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />}
                      Добавить
                    </button>
                  </div>
                </section>
              ) : null}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
