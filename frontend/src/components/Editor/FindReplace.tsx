import { useState, useEffect, useCallback, useRef } from 'react'
import { Search, Replace, X, ChevronUp, ChevronDown, CaseSensitive, Regex } from 'lucide-react'
import { Editor } from '@tiptap/react'
import { toast } from 'sonner'

interface FindReplaceProps {
  editor: Editor | null
  isOpen: boolean
  onClose: () => void
}

interface SearchResult {
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

  // Focus input when opened
  useEffect(() => {
    if (isOpen && findInputRef.current) {
      findInputRef.current.focus()
    }
  }, [isOpen])

  // Search for matches
  const performSearch = useCallback(() => {
    if (!editor || !findText) {
      setResults([])
      setCurrentIndex(-1)
      return
    }

    const searchResults: SearchResult[] = []
    
    try {
      let searchPattern: RegExp
      if (useRegex) {
        searchPattern = new RegExp(findText, caseSensitive ? 'g' : 'gi')
      } else {
        const escapedText = findText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        searchPattern = new RegExp(escapedText, caseSensitive ? 'g' : 'gi')
      }

      // Search directly in ProseMirror document to get correct positions
      editor.state.doc.descendants((node, pos) => {
        if (!node.isText || !node.text) return true
        
        const text = node.text
        let match
        
        // Reset regex lastIndex for each node
        searchPattern.lastIndex = 0
        
        while ((match = searchPattern.exec(text)) !== null) {
          searchResults.push({
            from: pos + match.index,
            to: pos + match.index + match[0].length,
            text: match[0],
          })
          
          // Prevent infinite loop for zero-length matches
          if (match[0].length === 0) {
            searchPattern.lastIndex++
          }
        }
        
        return true
      })
    } catch {
      // Invalid regex - silently ignore
    }

    // Sort results by position
    searchResults.sort((a, b) => a.from - b.from)

    setResults(searchResults)
    setCurrentIndex(searchResults.length > 0 ? 0 : -1)
    
    // Highlight first result
    if (searchResults.length > 0) {
      highlightResult(searchResults[0])
    }
  }, [editor, findText, caseSensitive, useRegex])

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(performSearch, 200)
    return () => clearTimeout(timer)
  }, [performSearch])

  const highlightResult = (result: SearchResult) => {
    if (!editor) return
    
    editor
      .chain()
      .focus()
      .setTextSelection({ from: result.from, to: result.to })
      .scrollIntoView()
      .run()
  }

  const goToNext = () => {
    if (results.length === 0) return
    const nextIndex = (currentIndex + 1) % results.length
    setCurrentIndex(nextIndex)
    highlightResult(results[nextIndex])
  }

  const goToPrev = () => {
    if (results.length === 0) return
    const prevIndex = (currentIndex - 1 + results.length) % results.length
    setCurrentIndex(prevIndex)
    highlightResult(results[prevIndex])
  }

  const replaceCurrent = () => {
    if (!editor || currentIndex < 0 || currentIndex >= results.length) return
    
    const result = results[currentIndex]
    
    editor
      .chain()
      .focus()
      .setTextSelection({ from: result.from, to: result.to })
      .deleteSelection()
      .insertContent(replaceText)
      .run()
    
    toast.success('Текст заменён')
    
    // Re-search after replacement
    setTimeout(performSearch, 100)
  }

  const replaceAll = () => {
    if (!editor || results.length === 0) return
    
    // Replace from end to start to maintain positions
    const sortedResults = [...results].sort((a, b) => b.from - a.from)
    
    let replacedCount = 0
    sortedResults.forEach((result) => {
      editor
        .chain()
        .setTextSelection({ from: result.from, to: result.to })
        .deleteSelection()
        .insertContent(replaceText)
        .run()
      replacedCount++
    })
    
    toast.success(`Заменено: ${replacedCount} вхождений`)
    
    // Clear results after replacement
    setResults([])
    setCurrentIndex(-1)
  }

  // Refs for stable callbacks to avoid stale closures
  const goToNextRef = useRef(goToNext)
  const goToPrevRef = useRef(goToPrev)
  const onCloseRef = useRef(onClose)
  
  useEffect(() => {
    goToNextRef.current = goToNext
    goToPrevRef.current = goToPrev
    onCloseRef.current = onClose
  })

  // Handle keyboard shortcuts
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
      {/* Find row */}
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

      {/* Navigation */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-gray-500">
          {results.length > 0 
            ? `${currentIndex + 1} из ${results.length}` 
            : findText ? 'Не найдено' : ''}
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

      {/* Replace row */}
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

