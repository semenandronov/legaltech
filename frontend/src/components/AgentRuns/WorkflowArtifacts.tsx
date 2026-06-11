import { Link } from 'react-router-dom'
import { FileText, Table } from 'lucide-react'

export interface WorkflowArtifactItem {
  type: 'document' | 'tabular_review' | string
  id: string
  title: string
  path: string
  preview?: string
  row_count?: number
  saved_count?: number
}

function artifactIcon(type: string) {
  if (type === 'tabular_review') return Table
  return FileText
}

function artifactLabel(type: string): string {
  if (type === 'tabular_review') return 'Таблица'
  if (type === 'document') return 'Документ'
  return 'Артефакт'
}

export function WorkflowArtifacts({ items }: { items: WorkflowArtifactItem[] }) {
  if (!items.length) return null

  return (
    <div className="mb-4">
      <p className="text-xs font-medium mb-2 uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
        Созданные материалы
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        {items.map((item) => {
          const Icon = artifactIcon(item.type)
          return (
            <Link
              key={`${item.type}-${item.id}`}
              to={item.path}
              className="flex items-start gap-3 rounded-xl border p-3 transition-colors hover:bg-[var(--color-bg-hover)]"
              style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-elevated)' }}
            >
              <div
                className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: 'var(--color-bg-hover)' }}
              >
                <Icon className="w-4 h-4" style={{ color: 'var(--color-accent-muted)' }} />
              </div>
              <div className="min-w-0">
                <p className="text-[10px] font-medium uppercase tracking-wide" style={{ color: 'var(--color-text-disabled)' }}>
                  {artifactLabel(item.type)}
                </p>
                <p className="text-sm font-medium truncate" style={{ color: 'var(--color-text-primary)' }}>
                  {item.title}
                </p>
                {item.type === 'tabular_review' && (
                  <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                    {item.row_count ?? 0} строк
                    {item.saved_count != null ? ` · ${item.saved_count} ячеек` : ''}
                  </p>
                )}
                {item.preview && item.type === 'document' && (
                  <p
                    className="text-xs mt-1 leading-snug"
                    style={{
                      color: 'var(--color-text-muted)',
                      display: '-webkit-box',
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: 'vertical' as const,
                      overflow: 'hidden',
                    }}
                  >
                    {item.preview}
                  </p>
                )}
              </div>
            </Link>
          )
        })}
      </div>
    </div>
  )
}
