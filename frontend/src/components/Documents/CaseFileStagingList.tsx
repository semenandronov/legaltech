import { Cloud, FileText, X, CheckCircle, AlertCircle, Loader } from 'lucide-react'
import type { StagedCaseFile } from '../../lib/caseFileStaging'
import { stagedDisplayName } from '../../lib/caseFileStaging'
import type { FileProcessingStatus } from '../../services/api'
import { processingStatusLabel } from '../../hooks/useCaseProcessingPoll'

type Row =
  | { type: 'staged'; item: StagedCaseFile }
  | { type: 'processing'; file: FileProcessingStatus }

export type CaseFileStagingListProps = {
  staged: StagedCaseFile[]
  processing?: FileProcessingStatus[]
  onRemoveStaged?: (key: string) => void
  canRemove?: boolean
  formatFileSize?: (bytes: number) => string
  title?: string
}

export function CaseFileStagingList({
  staged,
  processing = [],
  onRemoveStaged,
  canRemove = true,
  formatFileSize,
  title = 'Файлы к загрузке',
}: CaseFileStagingListProps) {
  const rows: Row[] = [
    ...processing.map((file) => ({ type: 'processing' as const, file })),
    ...staged.map((item) => ({ type: 'staged' as const, item })),
  ]

  if (rows.length === 0) return null

  const readyCount = processing.filter((f) => f.status === 'ready').length

  return (
    <div className="mt-4 space-y-2">
      <p className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
        {title}
        {processing.length > 0 && (
          <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}>
            {' '}
            · готово {readyCount}/{processing.length}
          </span>
        )}
      </p>
      {rows.map((row) => {
        if (row.type === 'processing') {
          const pf = row.file
          return (
            <StagingRow
              key={`proc-${pf.id}`}
              filename={pf.filename}
              icon={pf.status === 'ready' ? 'ready' : pf.status === 'error' ? 'error' : 'busy'}
              subtitle={processingStatusLabel(pf.status) + (pf.error ? ` — ${pf.error}` : '')}
            />
          )
        }
        const item = row.item
        const name = stagedDisplayName(item)
        const subtitle =
          item.kind === 'local'
            ? formatFileSize
              ? formatFileSize(item.file.size)
              : 'С компьютера'
            : 'Google Drive'
        return (
          <StagingRow
            key={item.key}
            filename={name}
            icon={item.kind === 'drive' ? 'drive' : 'local'}
            subtitle={`${subtitle} · ${processingStatusLabel(undefined, true)}`}
            trailing={
              canRemove && onRemoveStaged ? (
                <button
                  type="button"
                  onClick={() => onRemoveStaged(item.key)}
                  className="flex-shrink-0 p-0.5 rounded transition-colors hover:opacity-70"
                  style={{ color: 'var(--color-text-muted)' }}
                  aria-label={`Удалить ${name}`}
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              ) : undefined
            }
          />
        )
      })}
    </div>
  )
}

function StagingRow({
  filename,
  icon,
  subtitle,
  trailing,
}: {
  filename: string
  icon: 'local' | 'drive' | 'ready' | 'error' | 'busy'
  subtitle: string
  trailing?: React.ReactNode
}) {
  return (
    <div
      className="flex items-center gap-3 px-4 py-3 rounded-lg border"
      style={{
        borderColor: icon === 'error' ? 'var(--color-error, #dc2626)' : 'var(--color-border)',
        backgroundColor: 'var(--color-bg-elevated)',
      }}
    >
      {icon === 'ready' ? (
        <CheckCircle className="w-4 h-4 flex-shrink-0 text-green-500" />
      ) : icon === 'error' ? (
        <AlertCircle className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--color-error, #dc2626)' }} />
      ) : icon === 'busy' ? (
        <Loader className="w-4 h-4 flex-shrink-0 animate-spin" style={{ color: 'var(--color-text-muted)' }} />
      ) : icon === 'drive' ? (
        <Cloud className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
      ) : (
        <FileText className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
      )}
      <div className="flex-1 min-w-0">
        <span className="text-sm truncate block" style={{ color: 'var(--color-text-primary)' }}>
          {filename}
        </span>
        <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
          {subtitle}
        </span>
      </div>
      {trailing}
    </div>
  )
}
