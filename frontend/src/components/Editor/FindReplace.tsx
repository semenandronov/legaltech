import { useState, useEffect, useCallback, useRef } from 'react'
import { Search, Replace, X, ChevronUp, ChevronDown, CaseSensitive, Regex } from 'lucide-react'
import { Editor } from '@tiptap/react'
import { toast } from 'sonner'
import { textSpanToPmRange, replaceTextSpanPreservingMarks } from '@/utils/docTextPosition'

interface FindReplaceProps {
  editor: Editor | null
  isOpen: boolean
  onClose: () => void
}

interface SearchResult {
  charFrom: number
  charTo: number
  from: number
  to: number
  text: string
}

export const FindReplace = ({ editor, isOpen, onClose }: FindReplaceProps) => {
  const [findText, setFindText] = useState('')
  const [replaceText, setReplaceText] = useState('')
  const [caseSensitive, setCaseSensitive] = useState(false)
  const [useRegex, setUseRegex] = useState(false)
  const [results, setResults] = useState<SearchResult[]>([])
  const [currentIndex, setCurrentIndex] = useState(-1)
  const [showReplace, setShowReplace] = useState(false)
  const findInputRef = useRef<HTMLInputElement>(null)

  const syncHighlights = useCallback(
    (nextResults: SearchResult[], index: number) => {
      if (!editor) return
      if (nextResults.length === 0) {
        editor.commands.clearSearchHighlights()
        return
      }
      editor.commands.setSearchHighlights(
        nextResults.map((r) => ({ from: r.from, to: r.to })),
        index,
      )
    },
    [editor],
  )

  useEffect(() => {
    if (isOpen && findInputRef.current) {
      findInputRef.current.focus()
    }
  }, [isOpen])

  useEffect(() => {
    if (!isOpen && editor) {
      editor.commands.clearSearchHighlights()
    }
  }, [isOpen, editor])

  const performSearch = useCallback(() => {
    if (!editor || !findText) {
      setResults([])
      setCurrentIndex(-1)
      syncHighlights([], -1)
      return
    }

    const searchResults: SearchResult[] = []
    const doc = editor.state.doc

    try {
      let searchPattern: RegExp
      if (useRegex) {
        searchPattern = new RegExp(findText, caseSensitive ? 'g' : 'gi')
      } else {
        const escapedText = findText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        searchPattern = new RegExp(escapedText, caseSensitive ? 'g' : 'gi')
      }

      const docText = doc.textContent
      let match: RegExpExecArray | null
      searchPattern.lastIndex = 0

      while ((match = searchPattern.exec(docText)) !== null) {
        const charFrom = match.index
        const charTo = match.index + match[0].length
        const pmRange = textSpanToPmRange(doc, charFrom, charTo)
        if (pmRange) {
          searchResults.push({
            charFrom,
            charTo,
            from: pmRange.from,
            to: pmRange.to,
            text: match[0],
          })
        }
        if (match[0].length === 0) {
          searchPattern.lastIndex++
        }
      }
    } catch {
      // invalid regex
    }

    searchResults.sort((a, b) => a.from - b.from)

    const index = searchResults.length > 0 ? 0 : -1
    setResults(searchResults)
    setCurrentIndex(index)
    syncHighlights(searchResults, index)

    if (searchResults.length > 0) {
      highlightResult(editor, searchResults[0])
    }
  }, [editor, findText, caseSensitive, useRegex, syncHighlights])

  useEffect(() => {
    const timer = setTimeout(performSearch, 200)
    return () => clearTimeout(timer)
  }, [performSearch])

  useEffect(() => {
    if (!isOpen || !editor) return
    let timer: ReturnType<typeof setTimeout>
    const onUpdate = () => {
      clearTimeout(timer)
      timer = setTimeout(performSearch, 200)
    }
    editor.on('update', onUpdate)
    return () => {
      clearTimeout(timer)
      editor.off('update', onUpdate)
    }
  }, [isOpen, editor, performSearch])

  const highlightResult = (ed: Editor, result: SearchResult) => {
    ed.chain()
      .focus()
      .setTextSelection({ from: result.from, to: result.to })
      .scrollIntoView()
      .run()
  }

  const goToNext = () => {
    if (!editor || results.length === 0) return
    const nextIndex = (currentIndex + 1) % results.length
    setCurrentIndex(nextIndex)
    syncHighlights(results, nextIndex)
    highlightResult(editor, results[nextIndex])
  }

  const goToPrev = () => {
    if (!editor || results.length === 0) return
    const prevIndex = (currentIndex - 1 + results.length) % results.length
    setCurrentIndex(prevIndex)
    syncHighlights(results, prevIndex)
    highlightResult(editor, results[prevIndex])
  }

  const replaceCurrent = () => {
    if (!editor || currentIndex < 0 || currentIndex >= results.length) return

    const { charFrom, charTo } = results[currentIndex]
    if (replaceTextSpanPreservingMarks(editor, charFrom, charTo, replaceText)) {
      toast.success('Текст заменён')
      setTimeout(performSearch, 100)
    }
  }

  const replaceAll = () => {
    if (!editor || results.length === 0) return

    const sorted = [...results].sort((a, b) => b.from - a.from)
    let tr = editor.state.tr

    for (const { from, to } of sorted) {
      const $from = tr.doc.resolve(from)
      const marks = $from.marks()
      const newNode =
        marks.length > 0
          ? editor.state.schema.text(replaceText, marks)
          : editor.state.schema.text(replaceText)
      tr = tr.replaceWith(from, to, newNode)
    }

    editor.view.dispatch(tr)
    editor.commands.focus()

    toast.success(`Заменено: ${sorted.length} вхождений`)
    setResults([])
    setCurrentIndex(-1)
    editor.commands.clearSearchHighlights()
  }

  const goToNextRef = useRef(goToNext)
  const goToPrevRef = useRef(goToPrev)
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    goToNextRef.current = goToNext
    goToPrevRef.current = goToPrev
    onCloseRef.current = onClose
  })

  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onCloseRef.current()
      } else if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        goToNextRef.current()
      } else if (e.key === 'Enter' && e.shiftKey) {
        e.preventDefault()
        goToPrevRef.current()
      } else if (e.key === 'F3' && !e.shiftKey) {
        e.preventDefault()
        goToNextRef.current()
      } else if (e.key === 'F3' && e.shiftKey) {
        e.preventDefault()
        goToPrevRef.current()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen])

  if (!isOpen) return null

  return (
    <div
      className="absolute top-12 right-4 bg-white rounded-lg shadow-lg border border-gray-200 p-3 z-50 w-80"
      role="dialog"
      aria-label="Поиск и замена"
    >
      <div className="flex items-center gap-2 mb-2">
        <div className="relative flex-1">
          <Search
            className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
            aria-hidden="true"
          />
          <input
            ref={findInputRef}
            type="text"
            placeholder="Найти…"
            value={findText}
            onChange={(e) => setFindText(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            aria-label="Текст для поиска"
          />
        </div>
        <div className="flex items-center gap-0.5">
          <button
            onClick={() => setCaseSensitive(!caseSensitive)}
            className={`p-1.5 rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
              caseSensitive ? 'bg-blue-100 text-blue-700' : 'hover:bg-gray-100 text-gray-500'
            }`}
            title="С учётом регистра"
            aria-label="С учётом регистра"
            aria-pressed={caseSensitive}
          >
            <CaseSensitive className="w-4 h-4" aria-hidden="true" />
          </button>
          <button
            onClick={() => setUseRegex(!useRegex)}
            className={`p-1.5 rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
              useRegex ? 'bg-blue-100 text-blue-700' : 'hover:bg-gray-100 text-gray-500'
            }`}
            title="Регулярные выражения"
            aria-label="Регулярные выражения"
            aria-pressed={useRegex}
          >
            <Regex className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-gray-500">
          {results.length > 0
            ? `${currentIndex + 1} из ${results.length}`
            : findText
              ? 'Не найдено'
              : ''}
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={goToPrev}
            disabled={results.length === 0}
            className="p-1 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            title="Предыдущее (Shift+Enter)"
            aria-label="Предыдущее совпадение"
          >
            <ChevronUp className="w-4 h-4" aria-hidden="true" />
          </button>
          <button
            onClick={goToNext}
            disabled={results.length === 0}
            className="p-1 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            title="Следующее (Enter)"
            aria-label="Следующее совпадение"
          >
            <ChevronDown className="w-4 h-4" aria-hidden="true" />
          </button>
          <button
            onClick={() => setShowReplace(!showReplace)}
            className={`p-1 rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
              showReplace ? 'bg-blue-100 text-blue-700' : 'hover:bg-gray-100 text-gray-500'
            }`}
            title="Показать замену"
            aria-label="Показать замену"
            aria-expanded={showReplace}
          >
            <Replace className="w-4 h-4" aria-hidden="true" />
          </button>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-gray-100 text-gray-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            title="Закрыть (Escape)"
            aria-label="Закрыть"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </div>

      {showReplace && (
        <div className="space-y-2 pt-2 border-t border-gray-200">
          <div className="relative">
            <Replace
              className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
              aria-hidden="true"
            />
            <input
              type="text"
              placeholder="Заменить на…"
              value={replaceText}
              onChange={(e) => setReplaceText(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              aria-label="Текст для замены"
            />
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={replaceCurrent}
              disabled={results.length === 0 || currentIndex < 0}
              className="flex-1 px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            >
              Заменить
            </button>
            <button
              onClick={replaceAll}
              disabled={results.length === 0}
              className="flex-1 px-3 py-1.5 text-sm border border-blue-600 text-blue-600 rounded hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            >
              Заменить все ({results.length})
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
