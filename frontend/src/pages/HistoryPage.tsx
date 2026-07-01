import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Clock, MessageSquare, Table2 } from 'lucide-react'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { MikePageHeader } from '../components/TabularReview/mike/MikePageHeader'
import {
  MikeTableBody,
  MikeTableCell,
  MikeTableEmptyState,
  MikeTableHeaderCell,
  MikeTableHeaderRow,
  MikeTableRow,
  MikeTableScrollArea,
  MikeTableStickyCell,
} from '../components/TabularReview/mike/mikeListTablePrimitives'
import { SkeletonLine } from '../components/TabularReview/mike/mikeTablePrimitives'
import { buildMainNavItems } from '../lib/mainNavItems'
import { isProductFeatureEnabled } from '../lib/productFeatures'
import { getRecentActivity, RecentActivityItem } from '../services/api'

const TYPE_CONFIG: Record<
  Exclude<RecentActivityItem['type'], 'global_chat'>,
  { label: string; Icon: typeof MessageSquare }
> & { global_chat?: { label: string; Icon: typeof MessageSquare } } = {
  case_chat: { label: 'Чат по делу', Icon: MessageSquare },
  global_chat: { label: 'Глобальный чат', Icon: MessageSquare },
  tabular_review: { label: 'Таблица', Icon: Table2 },
}

const formatDate = (iso: string | null) => {
  if (!iso) return '—'
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffDays = Math.floor(diffMs / 86400000)
  if (diffDays === 0) {
    return 'Сегодня, ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  }
  if (diffDays === 1) {
    return 'Вчера, ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', year: 'numeric' })
}

const HistoryPage = () => {
  const navigate = useNavigate()
  const [items, setItems] = useState<RecentActivityItem[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  useEffect(() => {
    getRecentActivity(50)
      .then(setItems)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const visibleItems = useMemo(() => {
    let list = items
    if (!isProductFeatureEnabled('globalAssistant')) {
      list = list.filter((item) => item.type !== 'global_chat')
    }
    const q = search.trim().toLowerCase()
    if (!q) return list
    return list.filter((item) => {
      const haystack = [item.title, item.case_name ?? ''].join(' ').toLowerCase()
      return haystack.includes(q)
    })
  }, [items, search])

  const handleClick = (item: RecentActivityItem) => {
    if (item.type === 'case_chat' && item.case_id) {
      navigate(`/cases/${item.case_id}/chat?session=${item.id}`)
    } else if (item.type === 'global_chat' && isProductFeatureEnabled('globalAssistant')) {
      navigate(`/assistant?session=${item.id}`)
    } else if (item.type === 'tabular_review' && item.case_id) {
      navigate(`/cases/${item.case_id}/tabular-review/${item.id}`)
    }
  }

  const emptyState = (
    <MikeTableEmptyState>
      <Clock className="mb-4 h-8 w-8 text-gray-300" aria-hidden />
      <p className="font-serif text-2xl font-medium text-gray-900">История</p>
      <p className="mt-1 text-left text-xs text-gray-400">
        {search.trim()
          ? 'Ничего не найдено. Попробуйте другой запрос.'
          : 'Здесь появятся недавние чаты и табличные обзоры.'}
      </p>
      {!search.trim() && (
        <button
          type="button"
          onClick={() => navigate('/cases')}
          className="mt-4 inline-flex items-center gap-1 rounded-full bg-gray-900 px-3 py-1 text-xs font-medium text-white shadow-md transition-colors hover:bg-gray-700"
        >
          Перейти к делам
        </button>
      )}
    </MikeTableEmptyState>
  )

  return (
    <div className="ws-shell ws-tabular-shell flex">
      <UnifiedSidebar
        navItems={buildMainNavItems()}
        title="Legal AI"
        showBackButton={false}
        variant="tabular"
      />

      <div className="ws-tabular-page">
        <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
          <MikePageHeader
            loading={loading}
            actions={[
              {
                type: 'search',
                value: search,
                onChange: setSearch,
                placeholder: 'Поиск по истории…',
              },
            ]}
          >
            <h1 className="font-serif text-2xl font-medium text-gray-900">История</h1>
          </MikePageHeader>

          <MikeTableScrollArea>
            <MikeTableHeaderRow>
              <MikeTableStickyCell header>
                <span>Название</span>
              </MikeTableStickyCell>
              <MikeTableHeaderCell className="w-36">Тип</MikeTableHeaderCell>
              <MikeTableHeaderCell className="min-w-[160px] flex-1">Дело</MikeTableHeaderCell>
              <MikeTableHeaderCell className="w-40">Обновлено</MikeTableHeaderCell>
            </MikeTableHeaderRow>

            {loading ? (
              <MikeTableBody>
                {[1, 2, 3, 4, 5, 6].map((i) => (
                  <MikeTableRow key={i} interactive={false}>
                    <MikeTableStickyCell hover={false} bgClassName="bg-transparent">
                      <SkeletonLine className="w-48" />
                    </MikeTableStickyCell>
                    <MikeTableCell className="w-36">
                      <SkeletonLine className="w-20" />
                    </MikeTableCell>
                    <MikeTableCell className="min-w-[160px] flex-1">
                      <SkeletonLine className="w-28" />
                    </MikeTableCell>
                    <MikeTableCell className="w-40">
                      <SkeletonLine className="w-24" />
                    </MikeTableCell>
                  </MikeTableRow>
                ))}
              </MikeTableBody>
            ) : visibleItems.length === 0 ? (
              emptyState
            ) : (
              <MikeTableBody>
                {visibleItems.map((item) => {
                  const cfg = TYPE_CONFIG[item.type]
                  if (!cfg) return null
                  const clickable =
                    (item.type === 'case_chat' && !!item.case_id) ||
                    (item.type === 'global_chat' && isProductFeatureEnabled('globalAssistant')) ||
                    (item.type === 'tabular_review' && !!item.case_id)

                  return (
                    <MikeTableRow
                      key={`${item.type}-${item.id}`}
                      interactive={clickable}
                      onClick={clickable ? () => handleClick(item) : undefined}
                    >
                      <MikeTableStickyCell>
                        <span className="min-w-0 flex-1 truncate text-sm font-medium text-gray-800">
                          {item.title}
                        </span>
                      </MikeTableStickyCell>
                      <MikeTableCell className="w-36">
                        <span className="inline-block rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium leading-none text-gray-600">
                          {cfg.label}
                        </span>
                      </MikeTableCell>
                      <MikeTableCell className="min-w-[160px] flex-1 text-gray-700">
                        {item.case_name ?? '—'}
                      </MikeTableCell>
                      <MikeTableCell className="w-40">{formatDate(item.updated_at)}</MikeTableCell>
                    </MikeTableRow>
                  )
                })}
              </MikeTableBody>
            )}
          </MikeTableScrollArea>
        </div>
      </div>
    </div>
  )
}

export default HistoryPage
