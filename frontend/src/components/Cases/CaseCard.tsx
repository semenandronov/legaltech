import { useNavigate } from 'react-router-dom'
import { Folder, Table2 } from 'lucide-react'
import { CaseListItem } from '../../services/api'
import { MikeRowActions } from '@/components/TabularReview/mike/MikeRowActions'

interface CaseCardProps {
  caseItem: CaseListItem
  onDelete?: (caseId: string) => void
  reviewCount?: number
}

function formatUpdatedAt(dateString: string): string {
  const date = new Date(dateString)
  return date.toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function pluralDocs(n: number): string {
  if (n % 10 === 1 && n % 100 !== 11) return `${n} файл`
  if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) return `${n} файла`
  return `${n} файлов`
}

function pluralReviews(n: number): string {
  if (n % 10 === 1 && n % 100 !== 11) return `${n} таблица`
  if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) return `${n} таблицы`
  return `${n} таблиц`
}

const CaseCard = ({ caseItem, onDelete, reviewCount = 0 }: CaseCardProps) => {
  const navigate = useNavigate()
  const roleLabel =
    caseItem.my_role === 'owner'
      ? 'Владелец'
      : caseItem.my_role === 'editor'
        ? 'Редактор'
        : caseItem.my_role === 'viewer'
          ? 'Зритель'
          : null

  return (
    <div
      className="group relative flex h-full min-h-[196px] cursor-pointer flex-col rounded-lg border border-gray-200 bg-white p-4 transition-colors hover:border-gray-300 hover:bg-[#fafbfc]"
      onClick={() => navigate(`/cases/${caseItem.id}`)}
    >
      {onDelete && !caseItem.is_shared && (
        <div
          className="absolute right-2 top-2 opacity-0 transition-opacity group-hover:opacity-100"
          onClick={(event) => event.stopPropagation()}
        >
          <MikeRowActions onDelete={() => onDelete(caseItem.id)} />
        </div>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <p className="text-xs text-gray-400">Обновлено {formatUpdatedAt(caseItem.updated_at)}</p>
        {caseItem.is_shared ? (
          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-gray-600">
            Доступно мне
          </span>
        ) : (
          <span className="rounded bg-gray-50 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-gray-400">
            Моё
          </span>
        )}
      </div>

      <h3 className="mb-3 line-clamp-2 flex-1 pr-6 text-sm font-medium leading-snug text-gray-900">
        {caseItem.title || 'Без названия'}
      </h3>

      <div className="flex flex-col gap-1.5 text-xs text-gray-500">
        {caseItem.is_shared && caseItem.owner_name ? (
          <span>Владелец: {caseItem.owner_name}{roleLabel ? ` · ${roleLabel}` : ''}</span>
        ) : null}
        <span className="flex items-center gap-1.5">
          <Folder className="h-3.5 w-3.5 shrink-0 text-gray-400" />
          {pluralDocs(caseItem.num_documents)}
        </span>
        <span className="flex items-center gap-1.5">
          <Table2 className="h-3.5 w-3.5 shrink-0 text-gray-400" />
          {pluralReviews(reviewCount)}
        </span>
      </div>
    </div>
  )
}

export default CaseCard
