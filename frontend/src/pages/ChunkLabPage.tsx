import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { FolderOpen, MessageSquare, Clock, Workflow, Scissors, Upload, RefreshCw } from 'lucide-react'
import api, { getApiUrl } from '../services/api'
import { TabularDocumentViewer } from '../components/TabularReview/TabularDocumentViewer'

type CitationPayload = {
  citation_id?: string
  source_id?: string
  file_name?: string
  page?: number | null
  quote?: string | null
  quote_anchor?: string | null
  char_start?: number | null
  char_end?: number | null
  chunk_id?: string
  bbox?: { x0?: number; y0?: number; x1?: number; y1?: number }
  bbox_regions?: Array<{ x0?: number; y0?: number; x1?: number; y1?: number }>
  page_bbox?: { width?: number; height?: number }
}

type ChunkRow = {
  chunk_index: number
  chunk_id?: string
  text_preview: string
  citation: CitationPayload
}

type IndexedChunksResponse = {
  file: { id: string; filename: string; file_type: string; processing_status?: string }
  chunks: ChunkRow[]
  total: number
}

function viewerFileType(filename: string): 'pdf' | 'docx' | 'txt' {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.pdf')) return 'pdf'
  if (lower.endsWith('.docx')) return 'docx'
  return 'txt'
}

const ChunkLabPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const [files, setFiles] = useState<Array<{ id: string; filename: string; file_type: string }>>([])
  const [fileId, setFileId] = useState<string>('')
  const [meta, setMeta] = useState<IndexedChunksResponse['file'] | null>(null)
  const [chunks, setChunks] = useState<ChunkRow[]>([])
  const [selected, setSelected] = useState<ChunkRow | null>(null)
  const [loadingList, setLoadingList] = useState(false)
  const [loadingChunks, setLoadingChunks] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const navItems = useMemo(
    () => [
      { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
      { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
      { id: 'chunk-lab', label: 'Чанки', icon: Scissors, path: `/cases/${caseId}/chunk-lab` },
      { id: 'workflows', label: 'Workflows', icon: Workflow, path: '/workflows' },
      { id: 'history', label: 'История', icon: Clock, path: '/history' },
    ],
    [caseId],
  )

  const loadFiles = useCallback(async () => {
    if (!caseId) return
    setLoadingList(true)
    setError(null)
    try {
      const res = await api.get(getApiUrl(`/api/cases/${caseId}/files`))
      const docs = (res.data?.documents || []) as Array<{ id: string; filename: string; file_type: string }>
      setFiles(docs)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить список файлов')
    } finally {
      setLoadingList(false)
    }
  }, [caseId])

  const loadChunks = useCallback(async () => {
    if (!caseId || !fileId) return
    setLoadingChunks(true)
    setError(null)
    try {
      const res = await api.get<IndexedChunksResponse>(
        getApiUrl(`/api/cases/${caseId}/files/${fileId}/indexed-chunks`),
      )
      setMeta(res.data.file)
      setChunks(res.data.chunks || [])
      setSelected(null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить чанки')
      setChunks([])
      setMeta(null)
    } finally {
      setLoadingChunks(false)
    }
  }, [caseId, fileId])

  useEffect(() => {
    setFileId('')
    setChunks([])
    setSelected(null)
    setMeta(null)
  }, [caseId])

  useEffect(() => {
    void loadFiles()
  }, [loadFiles])

  useEffect(() => {
    if (files.length > 0 && !fileId) {
      setFileId(files[0].id)
    }
  }, [files, fileId])

  useEffect(() => {
    if (fileId) void loadChunks()
  }, [fileId, loadChunks])

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const list = e.target.files
    if (!list?.length || !caseId) return
    setUploading(true)
    setError(null)
    try {
      const formData = new FormData()
      for (let i = 0; i < list.length; i++) {
        formData.append('files', list[i])
      }
      const res = await api.post<{
        new_file_ids?: string[]
        files?: Array<{ id: string }>
      }>(getApiUrl(`/api/cases/${caseId}/files`), formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const newIds = res.data?.new_file_ids
      await loadFiles()
      if (newIds?.length) {
        setFileId(newIds[0])
      }
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string } } }
      setError(ax?.response?.data?.detail?.toString() || 'Ошибка загрузки')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const cellData = useMemo(() => {
    if (!selected) return null
    const c = selected.citation
    const extract =
      (c.quote_anchor && String(c.quote_anchor)) ||
      (c.quote && String(c.quote)) ||
      selected.text_preview ||
      null
    return {
      verbatimExtract: extract,
      highlightMode: 'verbatim' as const,
      sourcePage: c.page ?? null,
      sourcePageBasis: 'one' as const,
      highlightBBox: c.bbox,
      highlightBBoxRegions: c.bbox_regions,
      highlightPageBBox: c.page_bbox,
    }
  }, [selected])

  if (!caseId) {
    return (
      <div className="p-6 text-sm text-gray-400">
        Не указано дело. <Link to="/cases" className="text-blue-400 underline">К списку дел</Link>
      </div>
    )
  }

  const fname = meta?.filename || files.find((f) => f.id === fileId)?.filename || ''
  const ftype = viewerFileType(fname)

  return (
    <div className="h-screen flex overflow-hidden" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
      <UnifiedSidebar navItems={navItems} title="Legal AI" />
      <div className="flex-1 flex flex-col min-w-0">
        <header
          className="shrink-0 px-4 py-3 border-b flex items-center justify-between gap-4"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <div>
            <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
              Лаборатория чанков
            </h1>
            <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
              Чанки из PGVector после Docling — клик открывает файл справа с жёлтой подсветкой (как в чате).
            </p>
          </div>
          <Link
            to={`/cases/${caseId}/chat`}
            className="text-sm shrink-0"
            style={{ color: 'var(--color-info)' }}
          >
            ← К ассистенту
          </Link>
        </header>

        <div className="flex-1 flex min-h-0">
          <div
            className="w-[44%] min-w-[320px] flex flex-col border-r overflow-hidden"
            style={{ borderColor: 'var(--color-border)' }}
          >
            <div className="p-3 space-y-3 border-b shrink-0" style={{ borderColor: 'var(--color-border)' }}>
              <div className="flex flex-wrap items-center gap-2">
                <label className="text-xs px-2 py-1 rounded border cursor-pointer" style={{ borderColor: 'var(--color-border)' }}>
                  <Upload className="inline w-3 h-3 mr-1 align-middle" />
                  Загрузить в дело
                  <input type="file" multiple className="hidden" onChange={onUpload} disabled={uploading} />
                </label>
                <button
                  type="button"
                  onClick={() => void loadFiles()}
                  disabled={loadingList}
                  className="text-xs px-2 py-1 rounded border flex items-center gap-1"
                  style={{ borderColor: 'var(--color-border)' }}
                >
                  <RefreshCw className="w-3 h-3" /> Файлы
                </button>
                <button
                  type="button"
                  onClick={() => void loadChunks()}
                  disabled={loadingChunks || !fileId}
                  className="text-xs px-2 py-1 rounded border flex items-center gap-1"
                  style={{ borderColor: 'var(--color-border)' }}
                >
                  <RefreshCw className="w-3 h-3" /> Чанки
                </button>
              </div>
              <div>
                <label className="text-xs block mb-1" style={{ color: 'var(--color-text-muted)' }}>
                  Файл дела
                </label>
                <select
                  value={fileId}
                  onChange={(e) => setFileId(e.target.value)}
                  className="w-full text-sm rounded border px-2 py-1.5 bg-transparent"
                  style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                >
                  {files.length === 0 && <option value="">— нет файлов —</option>}
                  {files.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.filename}
                    </option>
                  ))}
                </select>
              </div>
              {meta?.processing_status && (
                <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                  Статус: {meta.processing_status}
                  {meta.processing_status !== 'ready' && ' — дождитесь индексации и нажмите «Чанки»'}
                </p>
              )}
            </div>

            {error && (
              <div className="m-3 text-sm text-red-400 border border-red-800 rounded p-2">{error}</div>
            )}

            <div className="flex-1 overflow-y-auto p-2 space-y-2">
              {loadingChunks && (
                <p className="text-xs p-2" style={{ color: 'var(--color-text-muted)' }}>
                  Загрузка чанков…
                </p>
              )}
              {!loadingChunks && chunks.length === 0 && (
                <p className="text-xs p-2" style={{ color: 'var(--color-text-muted)' }}>
                  Нет чанков в индексе для этого файла. Убедитесь, что обработка завершилась (статус ready).
                </p>
              )}
              {chunks.map((row) => {
                const active = selected?.chunk_id === row.chunk_id && selected?.chunk_index === row.chunk_index
                return (
                  <button
                    key={`${row.chunk_id || ''}-${row.chunk_index}`}
                    type="button"
                    onClick={() => setSelected(row)}
                    className="w-full text-left rounded-lg border p-2 text-xs transition-colors"
                    style={{
                      borderColor: active ? 'var(--color-info)' : 'var(--color-border)',
                      backgroundColor: active ? 'var(--color-info-bg)' : 'var(--color-bg-elevated)',
                      color: 'var(--color-text-primary)',
                    }}
                  >
                    <div className="font-medium mb-1">
                      Чанк #{row.chunk_index}
                      {row.chunk_id ? (
                        <span className="font-normal opacity-70 ml-1">· {String(row.chunk_id).slice(0, 8)}…</span>
                      ) : null}
                    </div>
                    <div className="opacity-90 line-clamp-4 whitespace-pre-wrap break-words">{row.text_preview}</div>
                    <div className="mt-1 text-[10px] opacity-60">Нажмите — открыть документ справа</div>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="flex-1 min-w-0 flex flex-col" style={{ backgroundColor: 'var(--color-bg-elevated)' }}>
            {!selected || !fileId ? (
              <div className="flex-1 flex items-center justify-center text-sm p-6" style={{ color: 'var(--color-text-muted)' }}>
                Выберите чанк слева — справа откроется документ с подсветкой.
              </div>
            ) : (
              <TabularDocumentViewer
                key={`${selected.chunk_id}-${selected.chunk_index}`}
                fileId={fileId}
                caseId={caseId}
                fileType={ftype}
                fileName={fname}
                cellData={cellData}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default ChunkLabPage
