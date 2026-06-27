import { Cloud, FileText, X, CheckCircle, AlertCircle, Loader } from 'lucide-react'
import type { StagedCaseFile } from '../../lib/caseFileStaging'
import { stagedDisplayName } from '../../lib/caseFileStaging'
import type { FileProcessingStatus } from '../../services/api'
import { processingStatusLabel } from '../../hooks/useCaseProcessingPoll'
import { cn } from '@/lib/utils'

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
      <p className="text-xs font-medium text-gray-700">
        {title}
        {processing.length > 0 && (
          <span className="font-normal text-gray-400">
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
                  className="flex-shrink-0 rounded-full p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700"
                  aria-label={`Удалить ${name}`}
                >
                  <X className="h-3.5 w-3.5" />
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
      className={cn(
        'flex items-center gap-3 rounded-lg border bg-white px-4 py-3',
        icon === 'error' ? 'border-red-200' : 'border-gray-200',
      )}
    >
      {icon === 'ready' ? (
        <CheckCircle className="h-4 w-4 flex-shrink-0 text-green-500" />
      ) : icon === 'error' ? (
        <AlertCircle className="h-4 w-4 flex-shrink-0 text-red-500" />
      ) : icon === 'busy' ? (
        <Loader className="h-4 w-4 flex-shrink-0 animate-spin text-gray-400" />
      ) : icon === 'drive' ? (
        <Cloud className="h-4 w-4 flex-shrink-0 text-gray-400" />
      ) : (
        <FileText className="h-4 w-4 flex-shrink-0 text-gray-400" />
      )}
      <div className="min-w-0 flex-1">
        <span className="block truncate text-sm text-gray-900">{filename}</span>
        <span className="text-xs text-gray-500">{subtitle}</span>
      </div>
      {trailing}
    </div>
  )
}
