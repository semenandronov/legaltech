import { useState, useMemo } from 'react'
import { Search, Plus, FolderOpen, FileText, Star, StarOff, X, Copy, Check } from 'lucide-react'
import { toast } from 'sonner'

export interface Clause {
  id: string
  title: string
  content: string
  category: string
  tags: string[]
  isFavorite: boolean
  usageCount: number
  lastUsed?: string
  createdAt: string
}

interface ClauseLibraryProps {
  isOpen: boolean
  onClose: () => void
  onInsertClause: (content: string) => void
  caseId?: string
}

const DEFAULT_CATEGORIES = [
  'Общие положения',
  'Предмет договора',
  'Права и обязанности',
  'Ответственность',
  'Конфиденциальность',
  'Форс-мажор',
  'Разрешение споров',
  'Заключительные положения',
]

// Sample clauses for demonstration
const SAMPLE_CLAUSES: Clause[] = [
  {
    id: '1',
    title: 'Конфиденциальность стандартная',
    content: `Стороны обязуются сохранять конфиденциальность всей информации, полученной в рамках исполнения настоящего Договора, и не разглашать её третьим лицам без предварительного письменного согласия другой Стороны, за исключением случаев, предусмотренных законодательством.`,
    category: 'Конфиденциальность',
    tags: ['NDA', 'конфиденциальность', 'стандартный'],
    isFavorite: true,
    usageCount: 45,
    createdAt: '2024-01-15',
  },
  {
    id: '2',
    title: 'Форс-мажор расширенный',
    content: `Стороны освобождаются от ответственности за неисполнение или ненадлежащее исполнение обязательств по настоящему Договору, если такое неисполнение явилось следствием обстоятельств непреодолимой силы (форс-мажор), включая, но не ограничиваясь: стихийные бедствия, военные действия, террористические акты, эпидемии, пандемии, решения органов государственной власти, существенно затрудняющие или делающие невозможным исполнение обязательств.`,
    category: 'Форс-мажор',
    tags: ['форс-мажор', 'ответственность', 'расширенный'],
    isFavorite: false,
    usageCount: 32,
    createdAt: '2024-02-10',
  },
  {
    id: '3',
    title: 'Арбитражная оговорка',
    content: `Все споры, разногласия и требования, возникающие из настоящего Договора или в связи с ним, в том числе касающиеся его исполнения, нарушения, прекращения или недействительности, подлежат разрешению в Международном коммерческом арбитражном суде при Торгово-промышленной палате Российской Федерации в соответствии с его Регламентом.`,
    category: 'Разрешение споров',
    tags: ['арбитраж', 'МКАС', 'споры'],
    isFavorite: true,
    usageCount: 28,
    createdAt: '2024-01-20',
  },
  {
    id: '4',
    title: 'Ограничение ответственности',
    content: `Совокупная ответственность любой из Сторон по настоящему Договору, независимо от оснований возникновения такой ответственности, ограничивается суммой, фактически уплаченной по Договору за последние 12 (двенадцать) месяцев, предшествующих возникновению соответствующего требования. Ни при каких обстоятельствах Стороны не несут ответственности за упущенную выгоду, косвенные или случайные убытки.`,
    category: 'Ответственность',
    tags: ['ответственность', 'ограничение', 'убытки'],
    isFavorite: false,
    usageCount: 19,
    createdAt: '2024-03-05',
  },
  {
    id: '5',
    title: 'Порядок изменения договора',
    content: `Все изменения и дополнения к настоящему Договору действительны только в том случае, если они совершены в письменной форме и подписаны уполномоченными представителями обеих Сторон. Любые устные договорённости, не оформленные надлежащим образом, не имеют юридической силы.`,
    category: 'Заключительные положения',
    tags: ['изменения', 'дополнения', 'письменная форма'],
    isFavorite: false,
    usageCount: 15,
    createdAt: '2024-02-28',
  },
]

export const ClauseLibrary = ({
  isOpen,
  onClose,
  onInsertClause,
}: ClauseLibraryProps) => {
  const [clauses, setClauses] = useState<Clause[]>(SAMPLE_CLAUSES)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [showFavoritesOnly, setShowFavoritesOnly] = useState(false)
  const [copiedId, setCopiedId] = useState<string | null>(null)

  // Filter clauses based on search, category, and favorites
  const filteredClauses = useMemo(() => {
    return clauses.filter((clause) => {
      const matchesSearch =
        searchQuery === '' ||
        clause.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        clause.content.toLowerCase().includes(searchQuery.toLowerCase()) ||
        clause.tags.some((tag) => tag.toLowerCase().includes(searchQuery.toLowerCase()))

      const matchesCategory = selectedCategory === null || clause.category === selectedCategory

      const matchesFavorites = !showFavoritesOnly || clause.isFavorite

      return matchesSearch && matchesCategory && matchesFavorites
    })
  }, [clauses, searchQuery, selectedCategory, showFavoritesOnly])

  // Sort by usage count (most used first)
  const sortedClauses = useMemo(() => {
    return [...filteredClauses].sort((a, b) => b.usageCount - a.usageCount)
  }, [filteredClauses])

  const handleToggleFavorite = (id: string) => {
    setClauses((prev) =>
      prev.map((clause) =>
        clause.id === id ? { ...clause, isFavorite: !clause.isFavorite } : clause
      )
    )
  }

  const handleInsert = (clause: Clause) => {
    onInsertClause(clause.content)
    // Update usage count
    setClauses((prev) =>
      prev.map((c) =>
        c.id === clause.id
          ? { ...c, usageCount: c.usageCount + 1, lastUsed: new Date().toISOString() }
          : c
      )
    )
    toast.success(`Клауза "${clause.title}" вставлена`)
    onClose()
  }

  const handleCopy = async (clause: Clause) => {
    try {
      await navigator.clipboard.writeText(clause.content)
      setCopiedId(clause.id)
      setTimeout(() => setCopiedId(null), 2000)
      toast.success('Скопировано в буфер обмена')
    } catch {
      toast.error('Не удалось скопировать')
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[85vh] overflow-hidden flex flex-col"
        role="dialog"
        aria-modal="true"
        aria-labelledby="clause-library-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-200">
          <div className="flex items-center gap-3">
            <FolderOpen className="w-6 h-6 text-blue-600" aria-hidden="true" />
            <h2 id="clause-library-title" className="text-xl font-semibold text-gray-900">
              Библиотека клауз
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label="Закрыть"
          >
            <X className="w-5 h-5 text-gray-500" aria-hidden="true" />
          </button>
        </div>

        {/* Search and Filters */}
        <div className="p-4 border-b border-gray-200 space-y-3">
          {/* Search */}
          <div className="relative">
            <Search
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
              aria-hidden="true"
            />
            <input
              type="text"
              placeholder="Поиск по названию, содержанию или тегам…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              aria-label="Поиск клауз"
            />
          </div>

          {/* Category filters */}
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => setSelectedCategory(null)}
              className={`px-3 py-1.5 text-sm rounded-full transition-colors ${
                selectedCategory === null
                  ? 'bg-blue-100 text-blue-700 font-medium'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
              aria-pressed={selectedCategory === null}
            >
              Все
            </button>
            {DEFAULT_CATEGORIES.map((category) => (
              <button
                key={category}
                onClick={() => setSelectedCategory(category)}
                className={`px-3 py-1.5 text-sm rounded-full transition-colors ${
                  selectedCategory === category
                    ? 'bg-blue-100 text-blue-700 font-medium'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
                aria-pressed={selectedCategory === category}
              >
                {category}
              </button>
            ))}
          </div>

          {/* Favorites toggle */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowFavoritesOnly(!showFavoritesOnly)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-full transition-colors ${
                showFavoritesOnly
                  ? 'bg-amber-100 text-amber-700 font-medium'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
              aria-pressed={showFavoritesOnly}
            >
              <Star className="w-3.5 h-3.5" aria-hidden="true" />
              Избранное
            </button>
            <span className="text-sm text-gray-500">
              Найдено: {sortedClauses.length} клауз
            </span>
          </div>
        </div>

        {/* Clauses List */}
        <div className="flex-1 overflow-y-auto p-4">
          {sortedClauses.length === 0 ? (
            <div className="text-center py-12 text-gray-500">
              <FileText className="w-12 h-12 mx-auto mb-4 opacity-50" aria-hidden="true" />
              <p>Клаузы не найдены</p>
              <p className="text-sm mt-1">Попробуйте изменить параметры поиска</p>
            </div>
          ) : (
            <div className="space-y-3">
              {sortedClauses.map((clause) => (
                <div
                  key={clause.id}
                  className="border border-gray-200 rounded-lg p-4 hover:border-blue-300 hover:shadow-sm transition-all"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-2">
                        <h3 className="font-medium text-gray-900 truncate">{clause.title}</h3>
                        <span className="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded">
                          {clause.category}
                        </span>
                      </div>
                      <p className="text-sm text-gray-600 line-clamp-2 mb-2">{clause.content}</p>
                      <div className="flex items-center gap-2 flex-wrap">
                        {clause.tags.map((tag) => (
                          <span
                            key={tag}
                            className="px-2 py-0.5 text-xs bg-blue-50 text-blue-600 rounded"
                          >
                            #{tag}
                          </span>
                        ))}
                        <span className="text-xs text-gray-400 ml-auto">
                          Использовано: {clause.usageCount} раз
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => handleToggleFavorite(clause.id)}
                        className="p-2 hover:bg-gray-100 rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
                        aria-label={clause.isFavorite ? 'Убрать из избранного' : 'Добавить в избранное'}
                        aria-pressed={clause.isFavorite}
                      >
                        {clause.isFavorite ? (
                          <Star className="w-4 h-4 text-amber-500 fill-amber-500" aria-hidden="true" />
                        ) : (
                          <StarOff className="w-4 h-4 text-gray-400" aria-hidden="true" />
                        )}
                      </button>
                      <button
                        onClick={() => handleCopy(clause)}
                        className="p-2 hover:bg-gray-100 rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                        aria-label="Копировать"
                      >
                        {copiedId === clause.id ? (
                          <Check className="w-4 h-4 text-green-500" aria-hidden="true" />
                        ) : (
                          <Copy className="w-4 h-4 text-gray-400" aria-hidden="true" />
                        )}
                      </button>
                      <button
                        onClick={() => handleInsert(clause)}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                        aria-label={`Вставить клаузу "${clause.title}"`}
                      >
                        <Plus className="w-4 h-4" aria-hidden="true" />
                        Вставить
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-gray-200 bg-gray-50">
          <p className="text-xs text-gray-500 text-center">
            Совет: Используйте Ctrl+Shift+L для быстрого открытия библиотеки клауз
          </p>
        </div>
      </div>
    </div>
  )
}

