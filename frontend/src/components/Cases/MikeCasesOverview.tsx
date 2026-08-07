import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, FolderOpen, Plus } from 'lucide-react'
import type { CaseListItem } from '@/services/api'
import CaseCard from '@/components/Cases/CaseCard'
import { CasesViewToggle, type CasesViewMode } from '@/components/Cases/CasesViewToggle'
import { MikePageHeader } from '@/components/TabularReview/mike/MikePageHeader'
import { MikeTableToolbar } from '@/components/TabularReview/mike/MikeTableToolbar'
import { MikeRowActionMenuItems, MikeRowActions } from '@/components/TabularReview/mike/MikeRowActions'
import {
  MikeTableBody,
  MikeTableCell,
  MikeTableEmptyState,
  MikeTableHeaderCell,
  MikeTableHeaderRow,
  MikeTablePrimaryCell,
  MikeTableRow,
  MikeTableScrollArea,
  MikeTableStickyCell,
} from '@/components/TabularReview/mike/mikeListTablePrimitives'
import {
  SkeletonDot,
  SkeletonLine,
  STICKY_CELL_BG,
  TABLE_CHECKBOX_CLASS,
} from '@/components/TabularReview/mike/mikeTablePrimitives'

interface MikeCasesOverviewProps {
  cases: CaseListItem[]
  total: number
  loading: boolean
  currentPage: number
  pageSize: number
  onPageChange: (page: number) => void
  onDeleteCase?: (caseId: string) => void
  onDeleteCases?: (caseIds: string[]) => void
  reviewCounts?: Record<string, number>
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

export function MikeCasesOverview({
  cases,
  total,
  loading,
  currentPage,
  pageSize,
  onPageChange,
  onDeleteCase,
  onDeleteCases,
  reviewCounts,
}: MikeCasesOverviewProps) {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [viewMode, setViewMode] = useState<CasesViewMode>('grid')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [actionsOpen, setActionsOpen] = useState(false)
  const actionsRef = useRef<HTMLDivElement>(null)

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  useEffect(() => {
    if (viewMode === 'grid') {
      setSelectedIds([])
    }
  }, [viewMode])

  useEffect(() => {
    function handleClick(event: MouseEvent) {
      if (actionsRef.current && !actionsRef.current.contains(event.target as Node)) {
        setActionsOpen(false)
      }
    }
    if (actionsOpen) document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [actionsOpen])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return cases
    return cases.filter((item) => (item.title ?? '').toLowerCase().includes(q))
  }, [cases, search])

  const ownedCases = useMemo(() => filtered.filter((c) => !c.is_shared), [filtered])
  const sharedCases = useMemo(() => filtered.filter((c) => !!c.is_shared), [filtered])

  const allSelected = filtered.length > 0 && filtered.every((item) => selectedIds.includes(item.id))
  const someSelected = !allSelected && filtered.some((item) => selectedIds.includes(item.id))

  function toggleAll() {
    if (allSelected) {
      setSelectedIds([])
    } else {
      setSelectedIds(filtered.map((item) => item.id))
    }
  }

  function toggleOne(id: string) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  function handleDeleteSelected() {
    if (selectedIds.length === 0) return
    setActionsOpen(false)
    if (onDeleteCases) {
      onDeleteCases(selectedIds)
    } else if (onDeleteCase) {
      for (const id of selectedIds) {
        onDeleteCase(id)
      }
    }
    setSelectedIds([])
  }

  const toolbarActions = (
    <>
      {viewMode === 'list' && selectedIds.length > 0 && (onDeleteCase || onDeleteCases) && (
        <div ref={actionsRef} className="relative">
          <button
            type="button"
            onClick={() => setActionsOpen((value) => !value)}
            className="flex items-center gap-1 text-xs font-medium text-gray-700 transition-colors hover:text-gray-900"
          >
            Действия
            <ChevronDown className="h-3.5 w-3.5" />
          </button>
          {actionsOpen && (
            <div className="absolute right-0 top-full z-[120] mt-1 w-48 overflow-hidden rounded-xl border border-white/70 bg-white/90 shadow-[0_8px_24px_rgba(15,23,42,0.08)] backdrop-blur-2xl">
              <MikeRowActionMenuItems onDelete={handleDeleteSelected} onClose={() => setActionsOpen(false)} />
            </div>
          )}
        </div>
      )}
    </>
  )

  const emptyState = (
    <MikeTableEmptyState>
      <FolderOpen className="mb-4 h-8 w-8 text-gray-300" aria-hidden />
      <p className="font-serif text-2xl font-medium text-gray-900">Дела</p>
      <p className="mt-1 text-left text-xs text-gray-400">
        {search.trim()
          ? 'Ничего не найдено. Попробуйте другой запрос.'
          : 'Загружайте документы в дела и запускайте чаты и табличные обзоры.'}
      </p>
      {!search.trim() && (
        <button
          type="button"
          onClick={() => navigate('/cases/new')}
          className="mt-4 inline-flex items-center gap-1 rounded-full bg-gray-900 px-3 py-1 text-xs font-medium text-white shadow-md transition-colors hover:bg-gray-700"
        >
          + Создать дело
        </button>
      )}
    </MikeTableEmptyState>
  )

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
      <MikePageHeader
        loading={loading}
        actions={[
          {
            type: 'search',
            value: search,
            onChange: setSearch,
            placeholder: 'Поиск по делам…',
          },
          {
            type: 'new',
            onClick: () => navigate('/cases/new'),
            title: 'Новое дело',
          },
        ]}
      >
        <h1 className="font-serif text-2xl font-medium text-gray-900">Дела</h1>
      </MikePageHeader>

      <MikeTableToolbar
        leading={<CasesViewToggle value={viewMode} onChange={setViewMode} />}
        actions={toolbarActions}
      />

      {viewMode === 'list' ? (
        <MikeTableScrollArea>
          <MikeTableHeaderRow>
            <MikeTableStickyCell header>
              {loading ? (
                <SkeletonDot />
              ) : (
                <input
                  type="checkbox"
                  checked={allSelected}
                  ref={(el) => {
                    if (el) el.indeterminate = someSelected
                  }}
                  onChange={toggleAll}
                  className={TABLE_CHECKBOX_CLASS}
                  aria-label="Выбрать все дела"
                />
              )}
              <span>Название</span>
            </MikeTableStickyCell>
            <MikeTableHeaderCell className="ml-auto w-24">Файлы</MikeTableHeaderCell>
            <MikeTableHeaderCell className="w-36">Таблицы</MikeTableHeaderCell>
            <MikeTableHeaderCell className="w-32">Обновлено</MikeTableHeaderCell>
            <MikeTableHeaderCell className="w-8" />
          </MikeTableHeaderRow>

          {loading ? (
            <MikeTableBody>
              {[1, 2, 3, 4, 5].map((i) => (
                <MikeTableRow key={i} interactive={false}>
                  <MikeTableStickyCell hover={false} bgClassName="bg-transparent">
                    <SkeletonDot />
                    <SkeletonLine className="h-3.5 w-48" />
                  </MikeTableStickyCell>
                  <MikeTableCell className="ml-auto w-24">
                    <SkeletonLine className="w-8" />
                  </MikeTableCell>
                  <MikeTableCell className="w-36">
                    <SkeletonLine className="w-8" />
                  </MikeTableCell>
                  <MikeTableCell className="w-32">
                    <SkeletonLine className="w-24" />
                  </MikeTableCell>
                  <MikeTableCell className="w-8" />
                </MikeTableRow>
              ))}
            </MikeTableBody>
          ) : filtered.length === 0 ? (
            emptyState
          ) : (
            <MikeTableBody>
              {filtered.map((caseItem) => {
                const rowBg = selectedIds.includes(caseItem.id) ? 'bg-gray-50' : STICKY_CELL_BG
                return (
                  <MikeTableRow
                    key={caseItem.id}
                    className={selectedIds.includes(caseItem.id) ? 'bg-gray-50' : undefined}
                    rightClickDropdown={
                      onDeleteCase
                        ? (close) => (
                            <MikeRowActionMenuItems
                              onDelete={() => onDeleteCase(caseItem.id)}
                              onClose={close}
                            />
                          )
                        : undefined
                    }
                    onClick={() => navigate(`/cases/${caseItem.id}`)}
                  >
                    <MikeTablePrimaryCell
                      bgClassName={rowBg}
                      selected={selectedIds.includes(caseItem.id)}
                      onSelectionChange={() => toggleOne(caseItem.id)}
                      label={
                        caseItem.is_shared
                          ? `${caseItem.title || 'Без названия'} · доступно мне`
                          : caseItem.title || 'Без названия'
                      }
                    />
                    <MikeTableCell className="ml-auto w-24">{caseItem.num_documents}</MikeTableCell>
                    <MikeTableCell className="w-36">
                      {reviewCounts?.[caseItem.id] ?? caseItem.tabular_reviews_count ?? 0}
                    </MikeTableCell>
                    <MikeTableCell className="w-32">{formatDate(caseItem.updated_at)}</MikeTableCell>
                    <MikeTableCell
                      className="flex w-8 items-center justify-center"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {onDeleteCase && !caseItem.is_shared && (
                        <MikeRowActions onDelete={() => onDeleteCase(caseItem.id)} />
                      )}
                    </MikeTableCell>
                  </MikeTableRow>
                )
              })}
            </MikeTableBody>
          )}
        </MikeTableScrollArea>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-8 pt-4 md:px-10">
          {loading ? (
            <div className="grid grid-cols-3 gap-3">
              {[...Array(6)].map((_, i) => (
                <div
                  key={i}
                  className="flex min-h-[196px] animate-pulse flex-col rounded-lg border border-gray-200 bg-white p-4"
                >
                  <div className="mb-3 h-3 w-24 rounded bg-gray-100" />
                  <div className="mb-2 h-4 w-full rounded bg-gray-100" />
                  <div className="mb-4 h-4 w-2/3 rounded bg-gray-100" />
                  <div className="mt-auto h-3 w-20 rounded bg-gray-100" />
                </div>
              ))}
            </div>
          ) : filtered.length === 0 ? (
            emptyState
          ) : (
            <div className="space-y-8">
              <div>
                <h2 className="mb-3 text-xs font-medium text-gray-500">Мои</h2>
                <div className="grid grid-cols-3 gap-3">
                  <button
                    type="button"
                    onClick={() => navigate('/cases/new')}
                    className="flex min-h-[196px] flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-gray-300 bg-white/60 p-4 transition-colors hover:border-gray-400 hover:bg-[#fafbfc]"
                  >
                    <span className="flex h-9 w-9 items-center justify-center rounded-full bg-gray-100 text-gray-500">
                      <Plus className="h-4 w-4" />
                    </span>
                    <div className="px-4 text-center">
                      <p className="text-sm font-medium text-gray-800">Новое дело</p>
                      <p className="mt-1 text-xs leading-relaxed text-gray-400">
                        До 10 000 файлов в деле
                      </p>
                    </div>
                  </button>

                  {ownedCases.map((caseItem) => (
                    <CaseCard
                      key={caseItem.id}
                      caseItem={caseItem}
                      onDelete={onDeleteCase}
                      reviewCount={reviewCounts?.[caseItem.id] ?? caseItem.tabular_reviews_count ?? 0}
                    />
                  ))}
                </div>
              </div>

              {sharedCases.length > 0 ? (
                <div>
                  <h2 className="mb-3 text-xs font-medium text-gray-500">Доступные мне</h2>
                  <div className="grid grid-cols-3 gap-3">
                    {sharedCases.map((caseItem) => (
                      <CaseCard
                        key={caseItem.id}
                        caseItem={caseItem}
                        reviewCount={reviewCounts?.[caseItem.id] ?? caseItem.tabular_reviews_count ?? 0}
                      />
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </div>
      )}

      {totalPages > 1 && !loading && (
        <div className="flex shrink-0 items-center justify-between border-t border-gray-200 px-4 py-3 text-xs text-gray-500 md:px-10">
          <span>
            {(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, total)} из {total}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={currentPage <= 1}
              onClick={() => onPageChange(currentPage - 1)}
              className="rounded-full px-3 py-1 transition-colors hover:bg-gray-100 disabled:cursor-default disabled:opacity-40"
            >
              Назад
            </button>
            <span>
              {currentPage} / {totalPages}
            </span>
            <button
              type="button"
              disabled={currentPage >= totalPages}
              onClick={() => onPageChange(currentPage + 1)}
              className="rounded-full px-3 py-1 transition-colors hover:bg-gray-100 disabled:cursor-default disabled:opacity-40"
            >
              Вперёд
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
