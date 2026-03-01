import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { FolderOpen, MessageSquare, Table2, Clock, Bot } from 'lucide-react'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { getRecentActivity, RecentActivityItem } from '../services/api'

const navItems = [
  { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
  { id: 'assistant', label: 'Ассистент', icon: MessageSquare, path: '/assistant' },
  { id: 'history', label: 'История', icon: Clock, path: '/history' },
]

const TYPE_CONFIG: Record<RecentActivityItem['type'], { label: string; Icon: typeof MessageSquare }> = {
  case_chat: { label: 'Ассистент', Icon: MessageSquare },
  global_chat: { label: 'Ассистент', Icon: Bot },
  tabular_review: { label: 'Таблица', Icon: Table2 },
}

const formatDate = (iso: string | null) => {
  if (!iso) return '—'
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffDays = Math.floor(diffMs / 86400000)
  if (diffDays === 0) return 'Сегодня, ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  if (diffDays === 1) return 'Вчера, ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: 'long', year: 'numeric' })
}

const groupByDate = (items: RecentActivityItem[]) => {
  const groups: { label: string; items: RecentActivityItem[] }[] = []
  const seen = new Map<string, number>()

  for (const item of items) {
    const d = item.updated_at ? new Date(item.updated_at) : null
    const now = new Date()
    let groupLabel = 'Раньше'
    if (d) {
      const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000)
      if (diffDays === 0) groupLabel = 'Сегодня'
      else if (diffDays === 1) groupLabel = 'Вчера'
      else if (diffDays < 7) groupLabel = 'На этой неделе'
      else if (diffDays < 30) groupLabel = 'В этом месяце'
    }

    if (!seen.has(groupLabel)) {
      seen.set(groupLabel, groups.length)
      groups.push({ label: groupLabel, items: [] })
    }
    groups[seen.get(groupLabel)!].items.push(item)
  }
  return groups
}

const HistoryPage = () => {
  const navigate = useNavigate()
  const [items, setItems] = useState<RecentActivityItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getRecentActivity(50)
      .then(setItems)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const handleClick = (item: RecentActivityItem) => {
    if (item.type === 'case_chat' && item.case_id) {
      navigate(`/cases/${item.case_id}/chat?session=${item.id}`)
    } else if (item.type === 'global_chat') {
      navigate(`/assistant?session=${item.id}`)
    } else if (item.type === 'tabular_review' && item.case_id) {
      navigate(`/cases/${item.case_id}/tabular-review/${item.id}`)
    }
  }

  const groups = groupByDate(items)

  return (
    <div className="h-screen flex overflow-hidden" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
      <UnifiedSidebar navItems={navItems} title="Legal AI" />

      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-4xl mx-auto px-8 py-10">
            {/* Header */}
            <div className="mb-8">
              <h1
                className="text-2xl font-semibold mb-1"
                style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-display)' }}
              >
                История
              </h1>
              <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                Все последние действия — ассистент, таблицы, чаты
              </p>
            </div>

            {/* Content */}
            {loading ? (
              <div className="space-y-3">
                {[...Array(8)].map((_, i) => (
                  <div
                    key={i}
                    className="h-16 rounded-xl animate-pulse"
                    style={{ backgroundColor: 'var(--color-bg-elevated)' }}
                  />
                ))}
              </div>
            ) : items.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <Clock className="w-10 h-10 mb-4" style={{ color: 'var(--color-text-muted)' }} />
                <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                  Истории пока нет
                </p>
              </div>
            ) : (
              <div className="space-y-8">
                {groups.map((group) => (
                  <div key={group.label}>
                    <p
                      className="text-xs font-medium uppercase tracking-wider mb-3"
                      style={{ color: 'var(--color-text-muted)' }}
                    >
                      {group.label}
                    </p>
                    <div
                      className="rounded-xl border overflow-hidden"
                      style={{ borderColor: 'var(--color-border)' }}
                    >
                      {group.items.map((item, i) => {
                        const cfg = TYPE_CONFIG[item.type]
                        const Icon = cfg.Icon
                        return (
                          <button
                            key={`${item.type}-${item.id}`}
                            onClick={() => handleClick(item)}
                            className="w-full flex items-center gap-4 px-5 py-4 text-left transition-colors hover:bg-[var(--color-bg-hover)]"
                            style={{
                              borderBottom:
                                i < group.items.length - 1
                                  ? '1px solid var(--color-border)'
                                  : 'none',
                            }}
                          >
                            {/* Icon */}
                            <div
                              className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                              style={{ backgroundColor: 'var(--color-bg-elevated)' }}
                            >
                              <Icon
                                className="w-4 h-4"
                                style={{ color: 'var(--color-text-secondary)' }}
                              />
                            </div>

                            {/* Text */}
                            <div className="flex-1 min-w-0">
                              <p
                                className="text-sm font-medium truncate"
                                style={{ color: 'var(--color-text-primary)' }}
                              >
                                {item.title}
                              </p>
                              <div className="flex items-center gap-2 mt-0.5">
                                {item.case_name && (
                                  <span
                                    className="text-xs truncate max-w-[160px]"
                                    style={{ color: 'var(--color-text-muted)' }}
                                  >
                                    {item.case_name}
                                  </span>
                                )}
                                {item.case_name && (
                                  <span style={{ color: 'var(--color-border)' }}>·</span>
                                )}
                                <span
                                  className="text-xs px-1.5 py-0.5 rounded"
                                  style={{
                                    color: 'var(--color-text-muted)',
                                    backgroundColor: 'var(--color-bg-elevated)',
                                  }}
                                >
                                  {cfg.label}
                                </span>
                              </div>
                            </div>

                            {/* Date */}
                            <span
                              className="text-xs flex-shrink-0"
                              style={{ color: 'var(--color-text-muted)' }}
                            >
                              {formatDate(item.updated_at)}
                            </span>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default HistoryPage
