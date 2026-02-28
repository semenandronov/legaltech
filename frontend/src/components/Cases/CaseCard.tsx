import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Folder, Table2, MoreVertical, Trash2 } from 'lucide-react'
import { CaseListItem } from '../../services/api'

interface CaseCardProps {
  caseItem: CaseListItem
  onDelete?: (caseId: string) => void
  reviewCount?: number
}

function formatUpdatedAt(dateString: string): string {
  const date = new Date(dateString)
  return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
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
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    if (!menuOpen) return
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [menuOpen])

  return (
    <div
      className="cursor-pointer rounded-xl border transition-all duration-150 hover:shadow-sm group relative flex flex-col"
      style={{
        backgroundColor: 'var(--color-bg-elevated)',
        borderColor: 'var(--color-border)',
        padding: '20px',
      }}
      onClick={() => navigate(`/cases/${caseItem.id}`)}
    >
      {/* Context menu */}
      {onDelete && (
        <div ref={menuRef} className="absolute top-3 right-3" style={{ zIndex: 10 }}>
          <button
            className="p-1 rounded transition-all duration-150 opacity-0 group-hover:opacity-100"
            style={{ color: 'var(--color-text-muted)' }}
            onClick={(e) => { e.stopPropagation(); setMenuOpen(!menuOpen) }}
          >
            <MoreVertical className="w-4 h-4" />
          </button>
          {menuOpen && (
            <div
              className="absolute right-0 top-full mt-1 rounded-lg border shadow-lg py-1 min-w-[160px]"
              style={{
                backgroundColor: 'var(--color-bg-elevated)',
                borderColor: 'var(--color-border)',
                zIndex: 50,
              }}
            >
              <button
                className="w-full px-3 py-2 text-left text-sm flex items-center gap-2 transition-colors duration-100 hover:bg-[var(--color-bg-hover)]"
                style={{ color: 'var(--color-error, #dc2626)' }}
                onClick={(e) => { e.stopPropagation(); setMenuOpen(false); onDelete(caseItem.id) }}
              >
                <Trash2 className="w-4 h-4" />
                Удалить
              </button>
            </div>
          )}
        </div>
      )}

      {/* Date — top, gray, small */}
      <p className="text-xs mb-3" style={{ color: '#9CA3AF' }}>
        Обновлено {formatUpdatedAt(caseItem.updated_at)}
      </p>

      {/* Title + badge — flexible middle */}
      <div className="flex-1">
        <h3
          className="text-base font-semibold leading-snug mb-2 pr-5"
          style={{ color: '#111827' }}
        >
          {caseItem.title || 'Без названия'}
        </h3>
      </div>

      {/* Footer stats — stacked, Harvey-style */}
      <div className="flex flex-col gap-1.5" style={{ color: '#6B7280' }}>
        <span className="flex items-center gap-1.5 text-xs">
          <Folder className="w-3.5 h-3.5" style={{ flexShrink: 0 }} />
          {pluralDocs(caseItem.num_documents)}
        </span>
        <span className="flex items-center gap-1.5 text-xs">
          <Table2 className="w-3.5 h-3.5" style={{ flexShrink: 0 }} />
          {pluralReviews(reviewCount)}
        </span>
      </div>
    </div>
  )
}

export default CaseCard
