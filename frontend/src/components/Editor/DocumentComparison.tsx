import { useState, useMemo } from 'react'
import { X, ArrowLeftRight, FileText, ChevronLeft, ChevronRight, Check, Plus, Minus } from 'lucide-react'
import { diffWords, Change } from 'diff'

interface DocumentVersion {
  id: string
  version: number
  content: string
  title: string
  createdAt: string
  author?: string
}

interface DocumentComparisonProps {
  isOpen: boolean
  onClose: () => void
  currentContent: string
  currentTitle: string
  versions: DocumentVersion[]
  onApplyVersion: (content: string) => void
}

interface DiffResult {
  additions: number
  deletions: number
  changes: Change[]
}

const stripHtml = (html: string): string => {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  return doc.body.textContent || ''
}

const computeDiff = (oldText: string, newText: string): DiffResult => {
  const changes = diffWords(oldText, newText)
  
  let additions = 0
  let deletions = 0
  
  changes.forEach((change) => {
    if (change.added) {
      additions += change.value.split(/\s+/).filter(Boolean).length
    } else if (change.removed) {
      deletions += change.value.split(/\s+/).filter(Boolean).length
    }
  })
  
  return { additions, deletions, changes }
}

export const DocumentComparison = ({
  isOpen,
  onClose,
  currentContent,
  currentTitle,
  versions,
  onApplyVersion,
}: DocumentComparisonProps) => {
  const [selectedVersion, setSelectedVersion] = useState<DocumentVersion | null>(
    versions.length > 0 ? versions[0] : null
  )
  const [viewMode, setViewMode] = useState<'side-by-side' | 'inline'>('inline')

  const currentText = useMemo(() => stripHtml(currentContent), [currentContent])
  const versionText = useMemo(
    () => (selectedVersion ? stripHtml(selectedVersion.content) : ''),
    [selectedVersion]
  )

  const diff = useMemo(() => {
    if (!selectedVersion) return null
    return computeDiff(versionText, currentText)
  }, [versionText, currentText, selectedVersion])

  const handleApplyVersion = () => {
    if (selectedVersion) {
      onApplyVersion(selectedVersion.content)
      onClose()
    }
  }

  const navigateVersions = (direction: 'prev' | 'next') => {
    if (!selectedVersion || versions.length === 0) return
    const currentIdx = versions.findIndex((v) => v.id === selectedVersion.id)
    let newIdx = direction === 'prev' ? currentIdx - 1 : currentIdx + 1
    
    if (newIdx < 0) newIdx = versions.length - 1
    if (newIdx >= versions.length) newIdx = 0
    
    setSelectedVersion(versions[newIdx])
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-6xl max-h-[90vh] overflow-hidden flex flex-col"
        role="dialog"
        aria-modal="true"
        aria-labelledby="comparison-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200 bg-gray-50">
          <div className="flex items-center gap-3">
            <ArrowLeftRight className="w-5 h-5 text-blue-600" aria-hidden="true" />
            <h2 id="comparison-title" className="text-lg font-semibold text-gray-900">
              Сравнение версий документа
            </h2>
          </div>
          <div className="flex items-center gap-2">
            {/* View mode toggle */}
            <div className="flex rounded-lg border border-gray-300 overflow-hidden">
              <button
                onClick={() => setViewMode('inline')}
                className={`px-3 py-1.5 text-sm transition-colors ${
                  viewMode === 'inline'
                    ? 'bg-blue-600 text-white'
                    : 'bg-white text-gray-600 hover:bg-gray-50'
                }`}
                aria-pressed={viewMode === 'inline'}
              >
                Построчно
              </button>
              <button
                onClick={() => setViewMode('side-by-side')}
                className={`px-3 py-1.5 text-sm transition-colors ${
                  viewMode === 'side-by-side'
                    ? 'bg-blue-600 text-white'
                    : 'bg-white text-gray-600 hover:bg-gray-50'
                }`}
                aria-pressed={viewMode === 'side-by-side'}
              >
                Рядом
              </button>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              aria-label="Закрыть"
            >
              <X className="w-5 h-5 text-gray-500" aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* Version selector */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigateVersions('prev')}
              disabled={versions.length <= 1}
              className="p-1.5 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              aria-label="Предыдущая версия"
            >
              <ChevronLeft className="w-5 h-5" aria-hidden="true" />
            </button>
            
            <div className="flex items-center gap-3">
              <div className="text-center">
                <div className="text-sm font-medium text-gray-500">Сравниваем</div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="px-2 py-1 bg-red-100 text-red-700 text-sm rounded">
                    Версия {selectedVersion?.version || '?'}
                  </span>
                  <ArrowLeftRight className="w-4 h-4 text-gray-400" aria-hidden="true" />
                  <span className="px-2 py-1 bg-green-100 text-green-700 text-sm rounded">
                    Текущая
                  </span>
                </div>
              </div>
            </div>
            
            <button
              onClick={() => navigateVersions('next')}
              disabled={versions.length <= 1}
              className="p-1.5 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              aria-label="Следующая версия"
            >
              <ChevronRight className="w-5 h-5" aria-hidden="true" />
            </button>
          </div>

          {/* Stats */}
          {diff && (
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1.5 text-sm">
                <Plus className="w-4 h-4 text-green-600" aria-hidden="true" />
                <span className="text-green-600 font-medium">+{diff.additions} слов</span>
              </div>
              <div className="flex items-center gap-1.5 text-sm">
                <Minus className="w-4 h-4 text-red-600" aria-hidden="true" />
                <span className="text-red-600 font-medium">-{diff.deletions} слов</span>
              </div>
            </div>
          )}

          {/* Version selector dropdown */}
          <select
            value={selectedVersion?.id || ''}
            onChange={(e) => {
              const version = versions.find((v) => v.id === e.target.value)
              if (version) setSelectedVersion(version)
            }}
            className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Выбрать версию"
          >
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                Версия {v.version} — {new Date(v.createdAt).toLocaleDateString('ru-RU')}
              </option>
            ))}
          </select>
        </div>

        {/* Comparison content */}
        <div className="flex-1 overflow-auto p-4">
          {versions.length === 0 ? (
            <div className="text-center py-12 text-gray-500">
              <FileText className="w-12 h-12 mx-auto mb-4 opacity-50" aria-hidden="true" />
              <p>Нет сохранённых версий для сравнения</p>
            </div>
          ) : viewMode === 'inline' ? (
            /* Inline diff view */
            <div className="bg-gray-50 rounded-lg p-6 font-mono text-sm leading-relaxed">
              {diff?.changes.map((change, index) => {
                if (change.added) {
                  return (
                    <span
                      key={index}
                      className="bg-green-200 text-green-800 px-0.5 rounded"
                    >
                      {change.value}
                    </span>
                  )
                }
                if (change.removed) {
                  return (
                    <span
                      key={index}
                      className="bg-red-200 text-red-800 line-through px-0.5 rounded"
                    >
                      {change.value}
                    </span>
                  )
                }
                return <span key={index}>{change.value}</span>
              })}
            </div>
          ) : (
            /* Side-by-side view */
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="mb-2 px-3 py-1.5 bg-red-100 text-red-700 text-sm font-medium rounded-t-lg">
                  Версия {selectedVersion?.version} — {selectedVersion && new Date(selectedVersion.createdAt).toLocaleDateString('ru-RU')}
                </div>
                <div className="bg-gray-50 rounded-b-lg p-4 text-sm leading-relaxed h-[50vh] overflow-auto">
                  {versionText}
                </div>
              </div>
              <div>
                <div className="mb-2 px-3 py-1.5 bg-green-100 text-green-700 text-sm font-medium rounded-t-lg">
                  Текущая версия — {currentTitle}
                </div>
                <div className="bg-gray-50 rounded-b-lg p-4 text-sm leading-relaxed h-[50vh] overflow-auto">
                  {currentText}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-4 border-t border-gray-200 bg-gray-50">
          <p className="text-sm text-gray-500">
            {selectedVersion && (
              <>
                Автор: {selectedVersion.author || 'Неизвестен'} • 
                Дата: {new Date(selectedVersion.createdAt).toLocaleString('ru-RU')}
              </>
            )}
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-500"
            >
              Закрыть
            </button>
            <button
              onClick={handleApplyVersion}
              disabled={!selectedVersion}
              className="flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            >
              <Check className="w-4 h-4" aria-hidden="true" />
              Восстановить эту версию
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

