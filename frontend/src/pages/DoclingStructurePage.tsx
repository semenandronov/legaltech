import { useMemo, useState } from 'react'
import { FileSearch } from 'lucide-react'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { buildMainNavItems } from '../lib/mainNavItems'
import api, { getApiUrl } from '../services/api'

type DoclingItem = {
  index: number
  level: number
  type: string
  label?: string
  name?: string
  marker?: string
  enumerated?: boolean
  chars: number
  text: string
  text_preview: string
  page_no: number | null
  is_heading: boolean
  prov: Array<{ page_no?: number; bbox?: Record<string, number> }>
}

type DoclingStructureResponse = {
  filename: string
  extension: string
  content_bytes: number
  docling_ocr: boolean
  native_text: boolean
  pages: Array<{ page_no: number; width: number; height: number }>
  type_counts: Record<string, number>
  items_total: number
  items_returned: number
  items_truncated: boolean
  export_markdown_chars: number
  items: DoclingItem[]
}

const DoclingStructurePage = () => {
  const [file, setFile] = useState<File | null>(null)
  const [doOcr, setDoOcr] = useState(true)
  const [nativeText, setNativeText] = useState(false)
  const [maxItems, setMaxItems] = useState(500)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<DoclingStructureResponse | null>(null)
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null)

  const navItems = useMemo(
    () => [
      ...buildMainNavItems(),
      { id: 'docling-structure', label: 'Docling Structure', icon: FileSearch, path: '/docling-structure' },
    ],
    [],
  )

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) {
      setError('Выберите PDF или другой поддерживаемый файл')
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)
    setExpandedIndex(null)

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('do_ocr', String(doOcr))
      formData.append('native_text', String(nativeText))
      formData.append('max_items', String(maxItems))
      const response = await api.post(getApiUrl('/api/upload/docling-structure'), formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 600_000,
      })
      setResult(response.data as DoclingStructureResponse)
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string } }; message?: string }
      setError(ax?.response?.data?.detail || ax?.message || 'Не удалось разобрать документ')
    } finally {
      setLoading(false)
    }
  }

  const downloadJson = () => {
    if (!result) return
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${result.filename || 'docling'}-structure.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="h-screen flex overflow-hidden" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
      <UnifiedSidebar navItems={navItems} title="Legal AI" />
      <div className="flex-1 overflow-auto">
        <div className="max-w-7xl mx-auto p-6 space-y-6">
          <div>
            <h1 className="text-2xl font-semibold text-white">Docling — сырая структура</h1>
            <p className="text-sm text-gray-400 mt-2 max-w-3xl">
              Загрузите файл и посмотрите, что Docling отдаёт напрямую через{' '}
              <code className="text-gray-300">iterate_items</code>: тип узла, уровень вложенности,
              страница, bbox — без legal chunking и нормализации.
            </p>
          </div>

          <form onSubmit={onSubmit} className="bg-[#151a22] border border-[#2a3342] rounded-xl p-4 space-y-4">
            <div>
              <label className="text-sm text-gray-300 block mb-2">Файл (pdf, docx, html, md, pptx)</label>
              <input
                type="file"
                accept=".pdf,.docx,.html,.htm,.md,.pptx"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="block w-full text-sm text-gray-200"
                required
              />
            </div>
            <div className="flex flex-wrap gap-6 text-sm text-gray-200">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={doOcr} onChange={(e) => setDoOcr(e.target.checked)} />
                OCR в Docling
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={nativeText} onChange={(e) => setNativeText(e.target.checked)} />
                Только текстовый слой PDF (без OCR)
              </label>
            </div>
            <div>
              <label className="text-sm text-gray-300 block mb-2">Макс. элементов в ответе</label>
              <input
                type="number"
                min={1}
                max={5000}
                value={maxItems}
                onChange={(e) => setMaxItems(Number(e.target.value || 500))}
                className="w-32 px-3 py-2 rounded-md bg-[#0f141b] border border-[#2a3342] text-white"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-500 disabled:opacity-60 text-white text-sm"
            >
              {loading ? 'Docling разбирает…' : 'Показать структуру'}
            </button>
          </form>

          {error && (
            <div className="bg-red-900/30 border border-red-700 rounded-md px-4 py-3 text-red-200 text-sm">{error}</div>
          )}

          {result && (
            <div className="space-y-4">
              <div className="bg-[#151a22] border border-[#2a3342] rounded-xl p-4 text-sm text-gray-200 flex flex-wrap gap-x-6 gap-y-2">
                <div>
                  Файл: <span className="text-white">{result.filename}</span>
                </div>
                <div>
                  Элементов: <span className="text-white">{result.items_total}</span>
                  {result.items_truncated && <span className="text-yellow-300"> (усечено до {result.items_returned})</span>}
                </div>
                <div>
                  Страниц: <span className="text-white">{result.pages.length}</span>
                </div>
                <div>
                  Markdown export: <span className="text-white">{result.export_markdown_chars} ch</span>
                </div>
                <button
                  type="button"
                  onClick={downloadJson}
                  className="ml-auto text-blue-400 hover:text-blue-300 text-sm"
                >
                  Скачать JSON
                </button>
              </div>

              <div className="bg-[#151a22] border border-[#2a3342] rounded-xl p-4">
                <p className="text-xs text-gray-400 mb-2">Типы элементов</p>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(result.type_counts).map(([type, count]) => (
                    <span
                      key={type}
                      className="text-xs bg-[#0f141b] border border-[#2a3342] text-gray-200 px-2 py-1 rounded"
                    >
                      {type}: {count}
                    </span>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                {result.items.map((item) => (
                  <div key={item.index} className="bg-[#151a22] border border-[#2a3342] rounded-lg overflow-hidden">
                    <button
                      type="button"
                      className="w-full text-left px-4 py-3 hover:bg-[#1a2030] flex flex-wrap gap-2 items-center text-sm"
                      onClick={() => setExpandedIndex(expandedIndex === item.index ? null : item.index)}
                    >
                      <span className="text-gray-500 w-8">#{item.index}</span>
                      <span className="text-xs bg-slate-800 text-slate-200 px-2 py-0.5 rounded">{item.type}</span>
                      <span className="text-xs text-gray-500">L{item.level}</span>
                      {item.is_heading && (
                        <span className="text-xs bg-amber-900/40 text-amber-200 px-2 py-0.5 rounded">heading</span>
                      )}
                      {item.label && (
                        <span className="text-xs text-gray-400">{item.label}</span>
                      )}
                      <span className="text-gray-400">p.{item.page_no ?? '—'}</span>
                      <span className="text-gray-400">{item.chars} ch</span>
                      <span className="text-white truncate flex-1 min-w-[200px]">
                        {item.name || item.text_preview.slice(0, 80) || '—'}
                      </span>
                    </button>
                    {expandedIndex === item.index && (
                      <div className="px-4 pb-4 space-y-2 border-t border-[#2a3342]">
                        {(item.marker || item.enumerated != null || item.name) && (
                          <div className="text-xs text-gray-400 pt-2 space-y-1">
                            {item.name && <div>name: {item.name}</div>}
                            {item.marker && <div>marker: {item.marker}</div>}
                            {item.enumerated != null && <div>enumerated: {String(item.enumerated)}</div>}
                          </div>
                        )}
                        {item.prov.length > 0 && (
                          <pre className="text-xs text-gray-500 whitespace-pre-wrap break-words bg-[#0f141b] border border-[#2a3342] rounded-md p-2 overflow-auto">
                            {JSON.stringify(item.prov, null, 2)}
                          </pre>
                        )}
                        <pre className="text-xs text-gray-200 whitespace-pre-wrap break-words bg-[#0f141b] border border-[#2a3342] rounded-md p-3 max-h-96 overflow-auto">
                          {item.text || '—'}
                        </pre>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default DoclingStructurePage
