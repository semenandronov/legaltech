import { useState, useEffect } from 'react'
import { getCasesList, deleteCase, CasesListResponse } from '../services/api'
import { MikeCasesOverview } from '../components/Cases/MikeCasesOverview'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { FolderOpen, MessageSquare, Clock } from 'lucide-react'
import { toast } from 'sonner'

const PAGE_SIZE = 50

const CasesListPage = () => {
  const [cases, setCases] = useState<CasesListResponse['cases']>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [currentPage, setCurrentPage] = useState(1)
  const [reviewCounts, setReviewCounts] = useState<Record<string, number>>({})

  const mainNavItems = [
    { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
    { id: 'assistant', label: 'Ассистент', icon: MessageSquare, path: '/assistant' },
    { id: 'history', label: 'История', icon: Clock, path: '/history' },
  ]

  useEffect(() => {
    loadCases()
  }, [currentPage])

  const loadCases = async () => {
    setLoading(true)
    try {
      const skip = (currentPage - 1) * PAGE_SIZE
      const data = await getCasesList(skip, PAGE_SIZE)
      const fetchedCases = data.cases || []
      setCases(fetchedCases)
      setTotal(data.total || 0)
      setReviewCounts(
        Object.fromEntries(
          fetchedCases.map((c) => [c.id, c.tabular_reviews_count ?? 0]),
        ),
      )
    } catch (error: unknown) {
      console.error('Ошибка при загрузке дел:', error)
    } finally {
      setLoading(false)
    }
  }

  const handlePageChange = (page: number) => {
    setCurrentPage(page)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const handleDeleteCase = async (caseId: string, options?: { skipConfirm?: boolean }) => {
    const caseItem = cases.find((c) => c.id === caseId)
    const title = caseItem?.title || 'Без названия'
    if (
      !options?.skipConfirm &&
      !window.confirm(
        `Удалить дело «${title}»?\n\nВсе документы, чаты и анализы будут удалены безвозвратно.`,
      )
    ) {
      return false
    }
    try {
      await deleteCase(caseId)
      setCases((prev) => prev.filter((c) => c.id !== caseId))
      setTotal((prev) => prev - 1)
      if (!options?.skipConfirm) {
        toast.success('Дело удалено')
      }
      return true
    } catch (error: unknown) {
      console.error('Ошибка при удалении дела:', error)
      toast.error('Не удалось удалить дело')
      return false
    }
  }

  const handleDeleteCases = async (caseIds: string[]) => {
    if (caseIds.length === 0) return
    if (
      caseIds.length > 1 &&
      !window.confirm(
        `Удалить ${caseIds.length} дел?\n\nВсе документы, чаты и анализы будут удалены безвозвратно.`,
      )
    ) {
      return
    }
    let deleted = 0
    for (const id of caseIds) {
      const ok = await handleDeleteCase(id, { skipConfirm: true })
      if (ok) deleted += 1
    }
    if (deleted > 0) {
      toast.success(deleted === 1 ? 'Дело удалено' : `Удалено дел: ${deleted}`)
    }
  }

  return (
    <div className="ws-shell ws-tabular-shell flex">
      <UnifiedSidebar navItems={mainNavItems} title="Legal AI" showBackButton={false} variant="tabular" />
      <div className="ws-tabular-page">
        <MikeCasesOverview
          cases={cases}
          total={total}
          loading={loading}
          currentPage={currentPage}
          pageSize={PAGE_SIZE}
          onPageChange={handlePageChange}
          onDeleteCase={(caseId) => {
            void handleDeleteCase(caseId)
          }}
          onDeleteCases={(caseIds) => {
            void handleDeleteCases(caseIds)
          }}
          reviewCounts={reviewCounts}
        />
      </div>
    </div>
  )
}

export default CasesListPage
