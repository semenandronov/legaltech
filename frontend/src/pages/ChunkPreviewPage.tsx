import { useMemo, useState } from 'react'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { FolderOpen, MessageSquare, Clock, Scissors } from 'lucide-react'
import api, { getApiUrl } from '../services/api'

type ChunkPreviewRow = {
  index: number
  chars: number
  preview: string
  text: string
  metadata: Record<string, unknown>
}

type ChunkPreviewResponse = {
  filename: string
  engine: 'docling' | 'yandex'
  content_bytes: number
  chunks_total: number
  chunks_returned: number
  total_chars_returned: number
  truncated: boolean
  chunks: ChunkPreviewRow[]
}

const ChunkPreviewPage = () => {
  const [file, setFile] = useState<File | null>(null)
  const [engine, setEngine] = useState<'docling' | 'yandex'>('docling')
  const [maxChunks, setMaxChunks] = useState<number>(200)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ChunkPreviewResponse | null>(null)

  const navItems = useMemo(
    () => [
      { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
      { id: 'assistant', label: 'Ассистент', icon: MessageSquare, path: '/assistant' },
      { id: 'history', label: 'История', icon: Clock, path: '/history' },
      { id: 'chunk-preview', label: 'Chunk Preview', icon: Scissors, path: '/chunk-preview' },
    ],
    []
  )

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) {
      setError('Выберите файл для анализа')
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('engine', engine)
      formData.append('max_chunks', String(Math.max(1, Math.min(maxChunks || 200, 1000))))
      const response = await api.post(getApiUrl('/api/upload/chunk-preview'), formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setResult(response.data as ChunkPreviewResponse)
    } catch (err: any) {
      const detail =
        err?.response?.data?.detail ||
        err?.message ||
        'Не удалось построить превью чанков'
      setError(String(detail))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-screen flex overflow-hidden" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
      <UnifiedSidebar navItems={navItems} title="Legal AI" />
      <div className="flex-1 overflow-auto">
        <div className="max-w-6xl mx-auto p-6 space-y-6">
          <div>
            <h1 className="text-2xl font-semibold text-white">Тестовое превью чанков</h1>
            <p className="text-sm text-gray-400 mt-2">
              Загрузите документ и посмотрите, как текущий pipeline разбивает его на чанки.
            </p>
          </div>

          <form onSubmit={onSubmit} className="bg-[#151a22] border border-[#2a3342] rounded-xl p-4 space-y-4">
            <div>
              <label className="text-sm text-gray-300 block mb-2">Файл</label>
              <input
                type="file"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="block w-full text-sm text-gray-200"
                required
              />
            </div>
            <div>
              <label className="text-sm text-gray-300 block mb-2">Движок обработки</label>
              <select
                value={engine}
                onChange={(e) => setEngine(e.target.value as 'docling' | 'yandex')}
                className="w-64 px-3 py-2 rounded-md bg-[#0f141b] border border-[#2a3342] text-white"
              >
                <option value="docling">Docling</option>
                <option value="yandex">Yandex OCR</option>
              </select>
              <p className="text-xs text-gray-400 mt-2">
                Для PDF можно сравнить качество разбиения: Docling vs Yandex OCR.
              </p>
            </div>
            <div>
              <label className="text-sm text-gray-300 block mb-2">Максимум чанков в ответе (1-1000)</label>
              <input
                type="number"
                min={1}
                max={1000}
                value={maxChunks}
                onChange={(e) => setMaxChunks(Number(e.target.value || 200))}
                className="w-40 px-3 py-2 rounded-md bg-[#0f141b] border border-[#2a3342] text-white"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-500 disabled:opacity-60 text-white text-sm"
            >
              {loading ? 'Разбираю...' : 'Показать чанки'}
            </button>
          </form>

          {error && (
            <div className="bg-red-900/30 border border-red-700 rounded-md px-4 py-3 text-red-200 text-sm">
              {error}
            </div>
          )}

          {result && (
            <div className="space-y-4">
              <div className="bg-[#151a22] border border-[#2a3342] rounded-xl p-4 text-sm text-gray-200">
                <div>Файл: <span className="text-white">{result.filename}</span></div>
                <div>Движок: <span className="text-white">{result.engine}</span></div>
                <div>Размер: {result.content_bytes} bytes</div>
                <div>Всего чанков: {result.chunks_total}</div>
                <div>Показано: {result.chunks_returned}</div>
                {result.truncated && <div className="text-yellow-300">Ответ усечён по max_chunks</div>}
              </div>

              {result.chunks.map((chunk) => (
                <div key={chunk.index} className="bg-[#151a22] border border-[#2a3342] rounded-xl p-4">
                  <div className="text-sm text-gray-300 mb-2">
                    Chunk #{chunk.index} · {chunk.chars} chars
                  </div>
                  <pre className="text-xs text-gray-200 whitespace-pre-wrap break-words bg-[#0f141b] border border-[#2a3342] rounded-md p-3">
                    {chunk.text}
                  </pre>
                  <details className="mt-3">
                    <summary className="text-xs text-gray-400 cursor-pointer">metadata</summary>
                    <pre className="text-xs text-gray-300 whitespace-pre-wrap break-words mt-2 bg-[#0f141b] border border-[#2a3342] rounded-md p-3">
                      {JSON.stringify(chunk.metadata, null, 2)}
                    </pre>
                  </details>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default ChunkPreviewPage
