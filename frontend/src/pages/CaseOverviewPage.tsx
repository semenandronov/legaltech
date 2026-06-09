import { useState, useEffect, useRef, Fragment, useCallback } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import {
  MessageSquare, FolderOpen, FileText, FileEdit, Table, BookOpen, Workflow,
  Search, Upload, Plus, ChevronRight, File, Loader2, Cloud,
  MoreHorizontal, Trash2, ArrowRight, Check, X, Pencil, AlertCircle,
} from 'lucide-react'
import { Drawer } from '@mui/material'
import { toast } from 'sonner'
import {
  getCase, getDocuments, getChatSessionsForCase, addFilesToCase, createFolder, getCaseFolders,
  moveFileToFolder, deleteFileFromCase, deleteFolder, renameFolder,
  cancelFileProcessing,
  CaseResponse, FolderItem, FilesResponse, UploadedFile,
} from '../services/api'
import { useCaseProcessingPoll } from '../hooks/useCaseProcessingPoll'
import {
  uploadStagedFilesToCase,
  type CaseOverviewLocationState,
} from '../lib/casePostCreateUpload'
import {
  buildPostCreatePendingRows,
  clearPostCreatePendingSession,
  formatCaseDocumentCountLabel,
  readPostCreatePendingFromSession,
  removePendingRowsForUploads,
  writePostCreatePendingToSession,
  type PostCreatePendingRow,
} from '../lib/postCreatePendingFiles'
import { createDocumentFromFile } from '../services/documentEditorApi'
import { tabularReviewApi } from '../services/tabularReviewApi'
import { CaseTabularHubModal } from '../components/TabularReview/CaseTabularHubModal'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import DocumentViewer from '../components/Documents/DocumentViewer'
import { DocumentWithMetadata } from '../components/Documents/DocumentsList'
import { GoogleDriveImportButton } from '../components/Documents/GoogleDriveImportButton'

interface DocumentFile {
  id: string
  filename: string
  file_type?: string
  folder_id?: string | null
  created_at?: string
  doc_type?: string
  classification?: any
  size?: number
  pages?: number
}

const formatDate = (s?: string | null) => {
  if (!s) return '—'
  return new Date(s).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

const formatSize = (bytes?: number) => {
  if (!bytes) return '—'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' КБ'
  return (bytes / (1024 * 1024)).toFixed(1) + ' МБ'
}


// Estimate seconds to process a single file based on type and size
const estimateFileSecs = (filename: string, sizeBytes?: number): number => {
  const mb = (sizeBytes || 0) / (1024 * 1024)
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  const secPerMb = ext === 'pdf' ? 30 : 5
  return Math.max(15, Math.round(mb * secPerMb))
}

const DOC_TYPE_LABELS: Record<string, string> = {
  contract: 'Договор',
  power_of_attorney: 'Доверенность',
  court_decision: 'Судебное решение',
  claim: 'Претензия',
  lawsuit: 'Исковое заявление',
  invoice: 'Счёт',
  act: 'Акт',
  protocol: 'Протокол',
  agreement: 'Соглашение',
  admin_penalty_challenge: 'Жалоба',
  nda: 'NDA',
  other: 'Другой',
}

const formatDocType = (docType?: string) => {
  if (!docType) return '—'
  return DOC_TYPE_LABELS[docType] ?? docType
}

const mapCaseDocuments = (documents: any[]): DocumentFile[] =>
  documents.map((doc: any) => ({
    id: doc.id,
    filename: doc.filename,
    file_type: doc.file_type,
    folder_id: doc.folder_id ?? null,
    created_at: doc.created_at,
    doc_type: doc.doc_type || doc.classification?.doc_type,
    classification: doc.classification,
    size: doc.size,
    pages: doc.pages ?? doc.page_count ?? doc.classification?.pages ?? doc.classification?.page_count,
  }))

const PRESETS = [
  {
    id: 'chat',
    title: 'Ассистент',
    description: 'Задайте вопросы по документам дела',
    path: (id: string) => `/cases/${id}/chat`,
  },
  {
    id: 'tabular',
    title: 'Таблица',
    description: 'Один вопрос — ко всем документам дела',
    path: (id: string) => `/cases/${id}/tabular-review`,
  },
]

const CaseOverviewPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [postCreatePendingRows, setPostCreatePendingRows] = useState<PostCreatePendingRow[]>(
    () => {
      const fromNav = buildPostCreatePendingRows(
        (location.state as CaseOverviewLocationState | null)?.postCreateUpload,
      )
      if (fromNav.length > 0) return fromNav
      if (caseId) return readPostCreatePendingFromSession(caseId)
      return []
    },
  )
  const [postCreateUploading, setPostCreateUploading] = useState(
    () => postCreatePendingRows.some((r) => r.status === 'uploading'),
  )
  const [postCreateUploadStatus, setPostCreateUploadStatus] = useState('')

  const [caseData, setCaseData] = useState<CaseResponse | null>(null)
  const [files, setFiles] = useState<DocumentFile[]>([])
  const [folders, setFolders] = useState<FolderItem[]>([])
  const [sessions, setSessions] = useState<Array<{
    session_id: string
    first_message: string
    last_message_at: string | null
    message_count: number
  }>>([])
  const [reviews, setReviews] = useState<Array<{
    id: string
    name: string
    status: string
    updated_at?: string
    created_at?: string
  }>>([])
  const [loadingCase, setLoadingCase] = useState(true)
  const [loadingFiles, setLoadingFiles] = useState(true)
  const [loadingSessions, setLoadingSessions] = useState(true)
  const [loadingReviews, setLoadingReviews] = useState(true)
  const [fileSearch, setFileSearch] = useState('')
  const [uploading, setUploading] = useState(false)
  const [creatingFolder, setCreatingFolder] = useState(false)
  const [newFolderName, setNewFolderName] = useState('')
  const folderInputRef = useRef<HTMLInputElement>(null)

  // Folder expansion
  const [expandedFolderIds, setExpandedFolderIds] = useState<Set<string>>(new Set())

  const toggleFolderExpand = (folderId: string) => {
    setExpandedFolderIds(prev => {
      const next = new Set(prev)
      if (next.has(folderId)) next.delete(folderId)
      else next.add(folderId)
      return next
    })
  }

  // Selection & file management
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [showMoveModal, setShowMoveModal] = useState(false)
  const [moveFileIds, setMoveFileIds] = useState<string[]>([])
  const [moveDestFolderId, setMoveDestFolderId] = useState<string | null | undefined>(undefined)
  const [activeMenu, setActiveMenu] = useState<string | null>(null)
  const [menuAnchor, setMenuAnchor] = useState<{ top?: number; bottom?: number; right: number } | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  // Document viewer
  const [viewerDoc, setViewerDoc] = useState<DocumentWithMetadata | null>(null)
  const [openInEditorLoading, setOpenInEditorLoading] = useState<string | null>(null)

  // Rename folder
  const [renameTarget, setRenameTarget] = useState<FolderItem | null>(null)
  const [renameName, setRenameName] = useState('')

  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const processingStartedAtRef = useRef<number | null>(null)

  const reloadFiles = useCallback(() => {
    if (!caseId) return
    getDocuments(caseId).then((d) => setFiles(mapCaseDocuments(d.documents || [])))
  }, [caseId])

  const { processingMap, ingestUploadResponse, fetchStatus } = useCaseProcessingPoll(caseId ?? null, {
    onAllDone: reloadFiles,
  })

  const [showAllActions, setShowAllActions] = useState(false)

  // Harvey-style query creation flow
  const [showQueryTypeModal, setShowQueryTypeModal] = useState(false)
  const [showFilePicker, setShowFilePicker] = useState(false)
  const [pickerSelectedIds, setPickerSelectedIds] = useState<Set<string>>(new Set())
  const [pickerSearch, setPickerSearch] = useState('')
  const [creatingReview, setCreatingReview] = useState(false)
  const [showTabularHub, setShowTabularHub] = useState(false)

  useEffect(() => {
    if (!caseId) return
    loadAll()
  }, [caseId])

  const anyFileProcessing = Object.values(processingMap).some(
    (s) => s === 'pending' || s === 'processing',
  )

  useEffect(() => {
    if (!anyFileProcessing) {
      if (elapsedTimerRef.current) {
        clearInterval(elapsedTimerRef.current)
        elapsedTimerRef.current = null
      }
      processingStartedAtRef.current = null
      return
    }
    if (!elapsedTimerRef.current) {
      processingStartedAtRef.current = Date.now()
      setElapsedSeconds(0)
      elapsedTimerRef.current = setInterval(() => {
        const secs = Math.floor(
          (Date.now() - (processingStartedAtRef.current ?? Date.now())) / 1000,
        )
        setElapsedSeconds(secs)
      }, 1000)
    }
    return () => {
      if (elapsedTimerRef.current) {
        clearInterval(elapsedTimerRef.current)
        elapsedTimerRef.current = null
      }
    }
  }, [anyFileProcessing])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setActiveMenu(null)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const openMenu = (id: string, e: React.MouseEvent) => {
    if (activeMenu === id) { setActiveMenu(null); return }
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    const right = window.innerWidth - rect.right
    if (window.innerHeight - rect.bottom > 200) {
      setMenuAnchor({ top: rect.bottom + 4, right })
    } else {
      setMenuAnchor({ bottom: window.innerHeight - rect.top + 4, right })
    }
    setActiveMenu(id)
  }

  const loadAll = async () => {
    if (!caseId) return
    setLoadingCase(true)
    setLoadingFiles(true)
    setLoadingSessions(true)
    setLoadingReviews(true)
    try {
      const [caseRes, docsRes, foldersRes, sessionsRes, reviewsRes] = await Promise.allSettled([
        getCase(caseId),
        getDocuments(caseId),
        getCaseFolders(caseId),
        getChatSessionsForCase(caseId),
        tabularReviewApi.listReviews(caseId, 0, 100),
      ])
      if (caseRes.status === 'fulfilled') setCaseData(caseRes.value)
      if (docsRes.status === 'fulfilled') setFiles(mapCaseDocuments(docsRes.value.documents || []))
      if (foldersRes.status === 'fulfilled') setFolders(foldersRes.value || [])
      if (sessionsRes.status === 'fulfilled') setSessions(sessionsRes.value || [])
      else setSessions([])
      if (reviewsRes.status === 'fulfilled') setReviews(reviewsRes.value.reviews || [])
      else setReviews([])
    } finally {
      setLoadingCase(false)
      setLoadingFiles(false)
      setLoadingSessions(false)
      setLoadingReviews(false)
    }
  }

  const [folderError, setFolderError] = useState<string | null>(null)

  const handleCreateFolder = async () => {
    if (!caseId || !newFolderName.trim()) return
    setFolderError(null)
    try {
      await createFolder(caseId, newFolderName.trim(), null)
      setNewFolderName('')
      setCreatingFolder(false)
      getCaseFolders(caseId).then(d => setFolders(d || []))
    } catch (err: any) {
      setFolderError(err?.response?.data?.detail || err?.message || 'Ошибка при создании папки')
    }
  }

  const mergeUploadedIntoList = (uploaded: UploadedFile[]) => {
    if (!uploaded.length) return
    setFiles((prev) => {
      const ids = new Set(prev.map((f) => f.id))
      const mapped: DocumentFile[] = uploaded.map((f) => ({
        id: f.id,
        filename: f.filename,
        file_type: f.file_type,
        created_at: f.created_at,
        size: f.size,
        folder_id: f.folder_id ?? null,
      }))
      return [...prev, ...mapped.filter((m) => !ids.has(m.id))]
    })
  }

  const handleFilesAdded = (result: FilesResponse) => {
    mergeUploadedIntoList(result.files ?? [])
    setPostCreatePendingRows((prev) => {
      const next = removePendingRowsForUploads(prev, result.files ?? [])
      if (caseId) writePostCreatePendingToSession(caseId, next)
      return next
    })
    setCaseData((prev) =>
      prev ? { ...prev, num_documents: result.total ?? prev.num_documents } : prev,
    )
    ingestUploadResponse(result)
  }

  useEffect(() => {
    if (!caseId) return
    const payload = (location.state as CaseOverviewLocationState | null)?.postCreateUpload
    if (!payload || (payload.locals.length === 0 && payload.drives.length === 0)) return

    const storageKey = `legalai:postCreateUpload:${caseId}`
    if (sessionStorage.getItem(storageKey)) {
      navigate({ pathname: location.pathname, search: location.search }, { replace: true, state: {} })
      const restored = readPostCreatePendingFromSession(caseId)
      if (restored.length > 0) {
        setPostCreatePendingRows(restored)
        setPostCreateUploading(restored.some((r) => r.status === 'uploading'))
      }
      return
    }
    sessionStorage.setItem(storageKey, '1')

    navigate({ pathname: location.pathname, search: location.search }, { replace: true, state: {} })

    const fileCount = payload.locals.length + payload.drives.length
    const pendingRows = buildPostCreatePendingRows(payload)
    setPostCreatePendingRows(pendingRows)
    writePostCreatePendingToSession(caseId, pendingRows)
    setPostCreateUploading(true)
    setPostCreateUploadStatus(
      fileCount === 1 ? 'Загрузка файла…' : `Загрузка файлов (0 из ${fileCount})…`,
    )

    void (async () => {
      try {
        const { responses, driveErrors } = await uploadStagedFilesToCase(caseId, payload, {
          onStep: (message) => setPostCreateUploadStatus(message),
        })
        for (const res of responses) {
          handleFilesAdded(res)
        }
        if (driveErrors.length > 0) {
          toast.error(driveErrors.join('; '))
        } else if (responses.length > 0) {
          toast.success(
            fileCount === 1
              ? 'Файл добавлен, идёт обработка'
              : `Добавлено файлов: ${fileCount}, идёт обработка`,
          )
        }
      } catch {
        toast.error('Не удалось загрузить файлы в дело')
      } finally {
        setPostCreateUploading(false)
        setPostCreateUploadStatus('')
        setPostCreatePendingRows([])
        clearPostCreatePendingSession(caseId)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- один раз при переходе с /cases/new
  }, [caseId])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!caseId || !e.target.files || e.target.files.length === 0) return
    const filesToUpload = Array.from(e.target.files)
    e.target.value = ''
    setUploading(true)
    try {
      const result = await addFilesToCase(caseId, filesToUpload)
      handleFilesAdded(result)
      toast.success(
        filesToUpload.length === 1
          ? 'Файл добавлен, идёт обработка'
          : `Добавлено файлов: ${filesToUpload.length}`,
      )
    } catch {
      toast.error('Не удалось загрузить файлы')
    } finally {
      setUploading(false)
    }
  }

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const openMoveModal = (fileIds: string[]) => {
    setMoveFileIds(fileIds)
    setMoveDestFolderId(undefined)
    setShowMoveModal(true)
    setActiveMenu(null)
  }

  const handleMoveFiles = async () => {
    if (!caseId || moveFileIds.length === 0) return
    try {
      await Promise.all(moveFileIds.map(id => moveFileToFolder(caseId, id, moveDestFolderId ?? null)))
      toast.success('Перемещено')
      setShowMoveModal(false)
      setSelectedIds(new Set())
      setMoveFileIds([])
      reloadFiles()
    } catch { toast.error('Не удалось переместить') }
  }

  const handleDeleteFile = async (fileId: string) => {
    if (!caseId) return
    try {
      await deleteFileFromCase(caseId, fileId)
      setActiveMenu(null)
      reloadFiles()
    } catch { toast.error('Не удалось удалить файл') }
  }

  const handleCancelFile = async (fileId: string) => {
    if (!caseId) return
    try {
      await cancelFileProcessing(caseId, fileId)
      setActiveMenu(null)
      await fetchStatus()
    } catch { toast.error('Не удалось отменить обработку') }
  }

  const handleDeleteFolderItem = async (folderId: string) => {
    if (!caseId) return
    try {
      await deleteFolder(caseId, folderId)
      setActiveMenu(null)
      getCaseFolders(caseId).then(d => setFolders(d || []))
    } catch { toast.error('Не удалось удалить папку') }
  }

  const handleDeleteSelected = async () => {
    if (!caseId) return
    const fileIds = [...selectedIds].filter(id => !id.startsWith('folder-'))
    const folderIds = [...selectedIds].filter(id => id.startsWith('folder-')).map(id => id.replace('folder-', ''))
    try {
      await Promise.all([
        ...fileIds.map(id => deleteFileFromCase(caseId, id)),
        ...folderIds.map(id => deleteFolder(caseId, id)),
      ])
      toast.success('Удалено')
      setSelectedIds(new Set())
      loadAll()
    } catch { toast.error('Ошибка при удалении') }
  }

  const handleOpenInEditor = async (file: DocumentFile) => {
    if (!caseId) return
    setOpenInEditorLoading(file.id)
    setActiveMenu(null)
    try {
      const doc = await createDocumentFromFile(file.id, caseId, file.filename)
      navigate(`/cases/${caseId}/editor/${doc.id}`)
    } catch (err: any) {
      toast.error(err.message || 'Не удалось открыть в редакторе')
    } finally {
      setOpenInEditorLoading(null)
    }
  }

  const handleRenameFolder = async () => {
    if (!caseId || !renameTarget || !renameName.trim()) return
    try {
      await renameFolder(caseId, renameTarget.id, renameName.trim())
      toast.success('Папка переименована')
      setRenameTarget(null)
      getCaseFolders(caseId).then(d => setFolders(d || []))
    } catch { toast.error('Не удалось переименовать') }
  }

  const handleCreateReview = async () => {
    if (!caseId || pickerSelectedIds.size === 0) return
    setCreatingReview(true)
    try {
      const review = await tabularReviewApi.createReview(
        caseId,
        'Untitled',
        undefined,
        [...pickerSelectedIds]
      )
      setShowFilePicker(false)
      setPickerSelectedIds(new Set())
      setPickerSearch('')
      navigate(`/cases/${caseId}/tabular-review/${review.id}`)
    } catch {
      toast.error('Не удалось создать таблицу')
    } finally {
      setCreatingReview(false)
    }
  }

  const navItems = [
    { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
    { id: 'editor', label: 'Редактор', icon: FileEdit, path: `/cases/${caseId}/editor` },
    { id: 'playbooks', label: 'Playbooks', icon: BookOpen, path: `/cases/${caseId}/playbooks` },
    { id: 'workflows', label: 'Workflows', icon: Workflow, path: `/cases/${caseId}/workflows` },
  ]

  // Root-level files only (no folder). When search is active, show all matching files regardless of folder.
  const filteredFiles = files.filter(f =>
    (fileSearch ? true : !f.folder_id) &&
    f.filename.toLowerCase().includes(fileSearch.toLowerCase())
  )

  const filteredPendingRows = postCreatePendingRows.filter((row) =>
    row.filename.toLowerCase().includes(fileSearch.toLowerCase()),
  )

  const hasVisibleFileSection =
    postCreatePendingRows.length > 0 || files.length > 0 || folders.length > 0

  const documentCountLabel = formatCaseDocumentCountLabel(
    caseData?.num_documents ?? 0,
    files.length,
    postCreatePendingRows,
    postCreateUploading,
  )

  const getFilesInFolder = (folderId: string) =>
    files.filter(f =>
      f.folder_id === folderId &&
      f.filename.toLowerCase().includes(fileSearch.toLowerCase())
    )

  return (
    <div
      className="h-screen flex overflow-hidden"
      style={{ backgroundColor: 'var(--color-bg-primary)' }}
    >
      <UnifiedSidebar navItems={navItems} title="Legal AI" />

      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-auto">
          <div className="px-8 pt-8 pb-12">

            {/* Breadcrumb */}
            <div
              className="flex items-center gap-1.5 text-sm mb-5"
              style={{ color: 'var(--color-text-muted)' }}
            >
              <button
                onClick={() => navigate('/cases')}
                className="hover:underline transition-colors"
                style={{ color: 'var(--color-text-muted)' }}
              >
                Дела
              </button>
              <span>/</span>
            </div>

            {/* Case header */}
            {loadingCase ? (
              <div className="mb-8">
                <div
                  className="h-7 w-64 rounded animate-pulse mb-2"
                  style={{ backgroundColor: 'var(--color-bg-elevated)' }}
                />
                <div
                  className="h-4 w-32 rounded animate-pulse"
                  style={{ backgroundColor: 'var(--color-bg-elevated)' }}
                />
              </div>
            ) : (
              <div className="mb-8">
                <h1
                  className="text-2xl font-semibold tracking-tight mb-1"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  {caseData?.title || 'Без названия'}
                </h1>
                <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                  {documentCountLabel}
                </p>
              </div>
            )}

            {/* Create new section */}
            <section className="mb-8">
              <h2
                className="text-sm font-medium mb-3"
                style={{ color: 'var(--color-text-primary)' }}
              >
                Начать работу
              </h2>
              <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
                {/* New query card — dashed */}
                <button
                  onClick={() => setShowQueryTypeModal(true)}
                  className="rounded-lg border-2 border-dashed flex flex-col items-start p-4 gap-2 text-left transition-all duration-150 hover:border-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] group"
                  style={{ borderColor: 'var(--color-border)', minHeight: '96px' }}
                >
                  <div
                    className="w-7 h-7 rounded-md flex items-center justify-center border transition-colors duration-150 group-hover:border-[var(--color-text-secondary)]"
                    style={{ borderColor: 'var(--color-border)' }}
                  >
                    <Plus className="w-4 h-4" style={{ color: 'var(--color-text-secondary)' }} />
                  </div>
                  <div>
                    <p className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                      Новый запрос
                    </p>
                    <p className="text-xs mt-0.5 leading-snug" style={{ color: 'var(--color-text-muted)' }}>
                      Выберите тип запроса и файлы
                    </p>
                  </div>
                </button>

                {/* Preset cards */}
                {PRESETS.map(preset => (
                  <button
                    key={preset.id}
                    onClick={() => {
                      if (preset.id === 'tabular') {
                        setShowTabularHub(true)
                        return
                      }
                      navigate(preset.path(caseId!))
                    }}
                    className="rounded-lg border flex flex-col items-start p-4 gap-2 text-left transition-all duration-150 hover:bg-[var(--color-bg-hover)]"
                    style={{
                      borderColor: 'var(--color-border)',
                      backgroundColor: 'var(--color-bg-elevated)',
                      minHeight: '96px',
                    }}
                  >
                    <div className="flex items-center justify-between w-full">
                      <p className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                        {preset.title}
                      </p>
                      <ChevronRight className="w-3.5 h-3.5" style={{ color: 'var(--color-text-muted)' }} />
                    </div>
                    <p className="text-xs leading-snug" style={{ color: 'var(--color-text-muted)' }}>
                      {preset.description}
                    </p>
                  </button>
                ))}
              </div>
            </section>

            {/* Recent actions section */}
            <section className="mb-8">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                  Последние действия
                </h2>
                {(sessions.length + reviews.length) > 5 && (
                  <button
                    onClick={() => setShowAllActions(true)}
                    className="text-xs hover:underline"
                    style={{ color: 'var(--color-text-muted)' }}
                  >
                    Все действия ({sessions.length + reviews.length})
                  </button>
                )}
              </div>
              {(loadingSessions || loadingReviews) ? (
                <div className="space-y-2">
                  {[...Array(3)].map((_, i) => (
                    <div
                      key={i}
                      className="h-10 rounded-lg animate-pulse"
                      style={{ backgroundColor: 'var(--color-bg-elevated)' }}
                    />
                  ))}
                </div>
              ) : (() => {
                type ActionItem =
                  | { kind: 'chat'; session_id: string; first_message: string; last_message_at: string | null; message_count: number; date: number }
                  | { kind: 'review'; id: string; name: string; status: string; date: number }

                const chatItems: ActionItem[] = sessions.map(s => ({
                  kind: 'chat' as const,
                  ...s,
                  date: s.last_message_at ? new Date(s.last_message_at).getTime() : 0,
                }))
                const reviewItems: ActionItem[] = reviews.map(r => ({
                  kind: 'review' as const,
                  ...r,
                  date: r.updated_at ? new Date(r.updated_at).getTime() : (r.created_at ? new Date(r.created_at).getTime() : 0),
                }))
                const allItems = [...chatItems, ...reviewItems]
                  .sort((a, b) => b.date - a.date)
                  .slice(0, 5)

                if (allItems.length === 0) {
                  return (
                    <p className="text-sm py-4" style={{ color: 'var(--color-text-muted)' }}>
                      Действий пока нет
                    </p>
                  )
                }

                return (
                  <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--color-border)' }}>
                    {allItems.map((item, i) => (
                      <button
                        key={item.kind === 'chat' ? `chat-${item.session_id}` : `review-${item.id}`}
                        onClick={() => {
                          if (item.kind === 'chat') navigate(`/cases/${caseId}/chat?session=${item.session_id}`)
                          else navigate(`/cases/${caseId}/tabular-review/${item.id}`)
                        }}
                        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-[var(--color-bg-hover)] transition-colors"
                        style={{
                          borderBottom: i < allItems.length - 1 ? '1px solid var(--color-border)' : 'none',
                        }}
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          {item.kind === 'chat' ? (
                            <MessageSquare className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                          ) : (
                            <Table className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                          )}
                          <span className="text-sm truncate" style={{ color: 'var(--color-text-primary)' }}>
                            {item.kind === 'chat' ? (item.first_message || 'Сессия') : item.name}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 flex-shrink-0 ml-4">
                          <span
                            className="text-xs px-1.5 py-0.5 rounded"
                            style={{
                              color: item.kind === 'chat' ? 'var(--color-accent)' : 'rgba(16,185,129,0.9)',
                              backgroundColor: item.kind === 'chat' ? 'var(--color-accent-subtle, rgba(99,102,241,0.08))' : 'rgba(16,185,129,0.08)',
                            }}
                          >
                            {item.kind === 'chat' ? 'Ассистент' : 'Таблица'}
                          </span>
                          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                            {item.kind === 'chat' ? formatDate(item.last_message_at) : formatDate(item.date ? new Date(item.date).toISOString() : undefined)}
                          </span>
                        </div>
                      </button>
                    ))}
                  </div>
                )
              })()}
            </section>

            {/* Project files section */}
            <section>
              {/* Upload / processing banner */}
              {postCreateUploading && (
                <div
                  className="flex items-center gap-2 px-4 py-2.5 mb-3 rounded-lg text-sm"
                  style={{
                    backgroundColor: 'var(--color-bg-elevated)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text-secondary)',
                  }}
                >
                  <Loader2 className="w-4 h-4 animate-spin flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                  <span>
                    {postCreateUploadStatus || 'Загрузка файлов в дело…'}
                  </span>
                </div>
              )}
              {(() => {
                const pendingFiles = files.filter(f => {
                  const s = processingMap[f.id]
                  return s === 'pending' || s === 'processing'
                })
                const ready = Object.values(processingMap).filter(s => s === 'ready').length
                const total = Object.values(processingMap).length
                if (postCreateUploading || total === 0 || pendingFiles.length === 0) return null

                // Recalculate estimate from remaining pending files
                const estimatedSecs = pendingFiles.reduce((sum, f) => sum + estimateFileSecs(f.filename, f.size), 0)
                const remaining = Math.max(0, estimatedSecs - elapsedSeconds)
                const countdownStr = remaining === 0
                  ? 'завершается…'
                  : remaining < 60
                  ? `ещё ~${remaining} сек`
                  : `ещё ~${Math.ceil(remaining / 60)} мин`
                return (
                  <div
                    className="flex items-center gap-2 px-4 py-2.5 mb-3 rounded-lg text-sm"
                    style={{
                      backgroundColor: 'var(--color-bg-elevated)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text-secondary)',
                    }}
                  >
                    <Loader2 className="w-4 h-4 animate-spin flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                    <span>
                      Обработка файлов…{' '}
                      <span style={{ color: 'var(--color-text-primary)', fontWeight: 500 }}>
                        {ready} из {total} готово
                      </span>
                      <span style={{ color: 'var(--color-text-muted)' }}>{' '}· {countdownStr}</span>
                    </span>
                    <span className="text-xs ml-auto" style={{ color: 'var(--color-text-muted)' }}>
                      Вы можете работать с готовыми файлами, остальные появятся автоматически
                    </span>
                  </div>
                )
              })()}

              <div className="flex items-center justify-between mb-3">
                <h2
                  className="text-sm font-medium"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  Файлы проекта
                </h2>
                <div className="flex items-center gap-2">
                  {/* Search */}
                  <div
                    className="flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm"
                    style={{
                      borderColor: 'var(--color-border)',
                      backgroundColor: 'var(--color-bg-elevated)',
                    }}
                  >
                    <Search className="w-3.5 h-3.5" style={{ color: 'var(--color-text-muted)' }} />
                    <input
                      type="text"
                      value={fileSearch}
                      onChange={e => setFileSearch(e.target.value)}
                      placeholder="Поиск"
                      className="bg-transparent outline-none w-36 text-xs"
                      style={{ color: 'var(--color-text-primary)' }}
                    />
                  </div>
                  {/* Create folder */}
                  {creatingFolder ? (
                    <>
                      <div className="flex items-center gap-1">
                        <input
                          ref={folderInputRef}
                          type="text"
                          value={newFolderName}
                          onChange={e => setNewFolderName(e.target.value)}
                          onKeyDown={e => {
                            if (e.key === 'Enter') handleCreateFolder()
                            if (e.key === 'Escape') { setCreatingFolder(false); setNewFolderName(''); setFolderError(null) }
                          }}
                          autoFocus
                          placeholder="Название папки"
                          className="px-2 py-1.5 rounded-lg border text-xs outline-none"
                          style={{
                            borderColor: folderError ? 'var(--color-error, #dc2626)' : 'var(--color-border)',
                            backgroundColor: 'var(--color-bg-elevated)',
                            color: 'var(--color-text-primary)',
                            width: '140px',
                          }}
                        />
                        <button
                          onClick={handleCreateFolder}
                          disabled={!newFolderName.trim()}
                          className="px-2 py-1.5 rounded-lg text-xs font-medium transition-colors"
                          style={{
                            backgroundColor: 'var(--color-text-primary)',
                            color: 'var(--color-bg-primary)',
                            opacity: !newFolderName.trim() ? 0.4 : 1,
                          }}
                        >
                          ОК
                        </button>
                        <button
                          onClick={() => { setCreatingFolder(false); setNewFolderName(''); setFolderError(null) }}
                          className="px-2 py-1.5 rounded-lg text-xs border transition-colors hover:bg-[var(--color-bg-hover)]"
                          style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
                        >
                          Отмена
                        </button>
                      </div>
                      {folderError && (
                        <p className="text-xs" style={{ color: 'var(--color-error, #dc2626)' }}>
                          {folderError}
                        </p>
                      )}
                    </>
                  ) : (
                    <button
                      onClick={() => setCreatingFolder(true)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors hover:bg-[var(--color-bg-hover)]"
                      style={{
                        borderColor: 'var(--color-border)',
                        color: 'var(--color-text-primary)',
                        backgroundColor: 'var(--color-bg-elevated)',
                      }}
                    >
                      <FolderOpen className="w-3.5 h-3.5" />
                      Создать папку
                    </button>
                  )}
                  {/* Upload */}
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    className="hidden"
                    onChange={handleUpload}
                  />
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploading}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors hover:bg-[var(--color-bg-hover)]"
                    style={{
                      borderColor: 'var(--color-border)',
                      color: 'var(--color-text-primary)',
                      backgroundColor: 'var(--color-bg-elevated)',
                    }}
                  >
                    {uploading
                      ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      : <Upload className="w-3.5 h-3.5" />
                    }
                    Загрузить файлы
                  </button>
                  {caseId && (
                    <GoogleDriveImportButton
                      caseId={caseId}
                      disabled={uploading}
                      onImportStarted={() => setUploading(true)}
                      onImportComplete={(response) => {
                        handleFilesAdded(response)
                        getCase(caseId).then((d) => setCaseData(d))
                        setUploading(false)
                      }}
                      onImportFailed={() => setUploading(false)}
                    />
                  )}
                </div>
              </div>

              {loadingFiles && !hasVisibleFileSection ? (
                <div className="space-y-2">
                  {[...Array(4)].map((_, i) => (
                    <div
                      key={i}
                      className="h-10 rounded-lg animate-pulse"
                      style={{ backgroundColor: 'var(--color-bg-elevated)' }}
                    />
                  ))}
                </div>
              ) : !hasVisibleFileSection ? (
                <div
                  className="rounded-lg border-2 border-dashed flex flex-col items-center justify-center py-12"
                  style={{ borderColor: 'var(--color-border)' }}
                >
                  <p className="text-sm mb-3" style={{ color: 'var(--color-text-muted)' }}>
                    Файлы не загружены
                  </p>
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    className="flex items-center gap-1.5 px-4 py-2 rounded-lg border text-sm font-medium transition-colors hover:bg-[var(--color-bg-hover)]"
                    style={{
                      borderColor: 'var(--color-border)',
                      color: 'var(--color-text-primary)',
                      backgroundColor: 'var(--color-bg-elevated)',
                    }}
                  >
                    <Upload className="w-4 h-4" />
                    Загрузить файлы
                  </button>
                  {caseId && (
                    <GoogleDriveImportButton
                      caseId={caseId}
                      onImportStarted={() => setUploading(true)}
                      onImportComplete={(response) => {
                        handleFilesAdded(response)
                        getCase(caseId).then((d) => setCaseData(d))
                        setUploading(false)
                      }}
                      onImportFailed={() => setUploading(false)}
                    />
                  )}
                </div>
              ) : (() => {
                const filteredFolders = folders.filter(f => f.name.toLowerCase().includes(fileSearch.toLowerCase()))
                const allCurrentIds = [
                  ...filteredFolders.map(f => `folder-${f.id}`),
                  ...filteredFiles.map(f => f.id),
                ]
                const allSelected = allCurrentIds.length > 0 && allCurrentIds.every(id => selectedIds.has(id))
                const toggleSelectAll = () => {
                  if (allSelected) setSelectedIds(new Set())
                  else setSelectedIds(new Set(allCurrentIds))
                }
                return (
                <div
                  className="rounded-lg border overflow-hidden"
                  style={{ borderColor: 'var(--color-border)' }}
                >
                  {/* Table header */}
                  <div
                    className="grid text-xs font-medium px-2 py-2 border-b items-center"
                    style={{
                      gridTemplateColumns: '28px 1fr 120px 100px 80px 32px',
                      borderBottomColor: 'var(--color-border)',
                      backgroundColor: 'var(--color-bg-elevated)',
                      color: 'var(--color-text-muted)',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleSelectAll}
                      className="rounded cursor-pointer"
                    />
                    <span className="pl-2">Название</span>
                    <span>Тип документа</span>
                    <span>Обновлено</span>
                    <span>Размер</span>
                    <span />
                  </div>

                  {/* Folder rows (with expandable files) */}
                  {filteredFolders.map((folder) => {
                    const rowId = `folder-${folder.id}`
                    const isSelected = selectedIds.has(rowId)
                    const menuOpen = activeMenu === rowId
                    const isExpanded = expandedFolderIds.has(folder.id)
                    const folderFiles = getFilesInFolder(folder.id)
                    return (
                      <Fragment key={rowId}>
                        {/* Folder row */}
                        <div
                          className="grid items-center px-2 py-2.5 transition-colors cursor-pointer"
                          style={{
                            gridTemplateColumns: '28px 1fr 120px 100px 80px 32px',
                            borderBottom: '1px solid var(--color-border)',
                            backgroundColor: isSelected ? 'var(--color-bg-hover)' : undefined,
                          }}
                          onClick={() => toggleFolderExpand(folder.id)}
                        >
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelect(rowId)}
                            onClick={e => e.stopPropagation()}
                            className="rounded cursor-pointer"
                          />
                          <div className="flex items-center gap-2 min-w-0 pl-2">
                            <ChevronRight
                              className="w-3.5 h-3.5 flex-shrink-0 transition-transform duration-150"
                              style={{
                                color: 'var(--color-text-muted)',
                                transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
                              }}
                            />
                            <FolderOpen className="w-3.5 h-3.5 flex-shrink-0 text-amber-400" />
                            <span className="text-sm truncate" style={{ color: 'var(--color-text-primary)' }}>
                              {folder.name}
                            </span>
                            {folder.file_count > 0 && (
                              <span className="text-xs flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
                                ({folder.file_count})
                              </span>
                            )}
                          </div>
                          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Папка</span>
                          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>—</span>
                          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>—</span>
                          <div className="relative flex justify-center" onClick={e => e.stopPropagation()}>
                            <button
                              onClick={(e) => openMenu(rowId, e)}
                              className="p-1 rounded transition-colors hover:bg-[var(--color-bg-hover)]"
                              style={{ color: 'var(--color-text-muted)' }}
                            >
                              <MoreHorizontal className="w-3.5 h-3.5" />
                            </button>
                            {menuOpen && (
                              <div
                                ref={menuRef}
                                className="rounded-xl shadow-lg py-1 w-44"
                                style={{
                                  position: 'fixed',
                                  top: menuAnchor?.top,
                                  bottom: menuAnchor?.bottom,
                                  right: menuAnchor?.right ?? 0,
                                  backgroundColor: 'var(--color-bg-elevated)',
                                  border: '1px solid var(--color-border)',
                                  zIndex: 9999,
                                }}
                              >
                                <button
                                  onClick={() => { setRenameTarget(folder); setRenameName(folder.name); setActiveMenu(null) }}
                                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors hover:bg-[var(--color-bg-hover)]"
                                  style={{ color: 'var(--color-text-primary)' }}
                                >
                                  <Pencil className="w-3.5 h-3.5 flex-shrink-0" />
                                  Переименовать
                                </button>
                                <div style={{ borderTop: '1px solid var(--color-border)' }} />
                                <button
                                  onClick={() => handleDeleteFolderItem(folder.id)}
                                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors"
                                  style={{ color: 'var(--color-error, #dc2626)' }}
                                >
                                  <Trash2 className="w-3.5 h-3.5 flex-shrink-0" />
                                  Удалить
                                </button>
                              </div>
                            )}
                          </div>
                        </div>

                        {/* Expanded: files inside folder */}
                        {isExpanded && (
                          <>
                            {folderFiles.length === 0 ? (
                              <div
                                className="px-12 py-3 text-xs"
                                style={{
                                  borderBottom: '1px solid var(--color-border)',
                                  color: 'var(--color-text-muted)',
                                  backgroundColor: 'var(--color-bg-primary)',
                                }}
                              >
                                Папка пуста
                              </div>
                            ) : folderFiles.map((file) => {
                              const isFileSel = selectedIds.has(file.id)
                              const fileMenuOpen = activeMenu === file.id
                              return (
                                <div
                                  key={file.id}
                                  className="grid items-center py-2 transition-colors"
                                  style={{
                                    gridTemplateColumns: '28px 1fr 120px 100px 80px 32px',
                                    borderBottom: '1px solid var(--color-border)',
                                    backgroundColor: isFileSel ? 'var(--color-bg-hover)' : 'var(--color-bg-primary)',
                                    paddingLeft: '8px',
                                    paddingRight: '8px',
                                  }}
                                >
                                  <input
                                    type="checkbox"
                                    checked={isFileSel}
                                    onChange={() => toggleSelect(file.id)}
                                    onClick={e => e.stopPropagation()}
                                    className="rounded cursor-pointer"
                                  />
                                  <div
                                    className="flex items-center gap-2 min-w-0 pl-8 cursor-pointer"
                                    onClick={() => setViewerDoc({ id: file.id, filename: file.filename, file_type: file.file_type || '', created_at: file.created_at || '', classification: file.classification })}
                                  >
                                    <File className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                                    <span className="text-sm truncate hover:underline" style={{ color: 'var(--color-text-primary)' }}>
                                      {file.filename}
                                    </span>
                                  </div>
                                  <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{file.doc_type || file.file_type || '—'}</span>
                                  <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{formatDate(file.created_at)}</span>
                                  <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{formatSize(file.size)}</span>
                                  <div className="relative flex justify-center" onClick={e => e.stopPropagation()}>
                                    <button
                                      onClick={(e) => openMenu(file.id, e)}
                                      className="p-1 rounded transition-colors hover:bg-[var(--color-bg-hover)]"
                                      style={{ color: 'var(--color-text-muted)' }}
                                    >
                                      <MoreHorizontal className="w-3.5 h-3.5" />
                                    </button>
                                    {fileMenuOpen && (
                                      <div
                                        ref={menuRef}
                                        className="rounded-xl shadow-lg py-1 w-48"
                                        style={{
                                          position: 'fixed',
                                          top: menuAnchor?.top,
                                          bottom: menuAnchor?.bottom,
                                          right: menuAnchor?.right ?? 0,
                                          backgroundColor: 'var(--color-bg-elevated)',
                                          border: '1px solid var(--color-border)',
                                          zIndex: 9999,
                                        }}
                                      >
                                        <button
                                          onClick={() => { setViewerDoc({ id: file.id, filename: file.filename, file_type: file.file_type || '', created_at: file.created_at || '', classification: file.classification }); setActiveMenu(null) }}
                                          className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors hover:bg-[var(--color-bg-hover)]"
                                          style={{ color: 'var(--color-text-primary)' }}
                                        >
                                          <FileText className="w-3.5 h-3.5 flex-shrink-0" />
                                          Просмотр
                                        </button>
                                        <button
                                          onClick={() => handleOpenInEditor(file)}
                                          disabled={openInEditorLoading === file.id}
                                          className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors hover:bg-[var(--color-bg-hover)] disabled:opacity-50"
                                          style={{ color: 'var(--color-text-primary)' }}
                                        >
                                          {openInEditorLoading === file.id ? <Loader2 className="w-3.5 h-3.5 flex-shrink-0 animate-spin" /> : <FileEdit className="w-3.5 h-3.5 flex-shrink-0" />}
                                          Открыть в редакторе
                                        </button>
                                        <button
                                          onClick={() => openMoveModal([file.id])}
                                          className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors hover:bg-[var(--color-bg-hover)]"
                                          style={{ color: 'var(--color-text-primary)' }}
                                        >
                                          <ArrowRight className="w-3.5 h-3.5 flex-shrink-0" />
                                          Переместить
                                        </button>
                                        <div style={{ borderTop: '1px solid var(--color-border)' }} />
                                        <button
                                          onClick={() => handleDeleteFile(file.id)}
                                          className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors"
                                          style={{ color: 'var(--color-error, #dc2626)' }}
                                        >
                                          <Trash2 className="w-3.5 h-3.5 flex-shrink-0" />
                                          Удалить
                                        </button>
                                      </div>
                                    )}
                                  </div>
                                </div>
                              )
                            })}
                          </>
                        )}
                      </Fragment>
                    )
                  })}

                  {/* Pending rows (сразу после «Создать дело», до ответа API) */}
                  {filteredPendingRows.map((row) => (
                    <div
                      key={`pending-${row.stagingKey}`}
                      className="grid items-center px-2 py-2.5"
                      style={{
                        gridTemplateColumns: '28px 1fr 120px 100px 80px 32px',
                        borderBottom: '1px solid var(--color-border)',
                        opacity: 0.85,
                      }}
                    >
                      <input
                        type="checkbox"
                        disabled
                        className="rounded cursor-not-allowed opacity-40"
                      />
                      <div className="flex items-center gap-2.5 min-w-0 pl-2">
                        <Loader2
                          className="w-3.5 h-3.5 flex-shrink-0 animate-spin"
                          style={{ color: 'var(--color-text-muted)' }}
                        />
                        {row.source === 'drive' ? (
                          <Cloud
                            className="w-3.5 h-3.5 flex-shrink-0"
                            style={{ color: 'var(--color-text-muted)' }}
                          />
                        ) : (
                          <File
                            className="w-3.5 h-3.5 flex-shrink-0"
                            style={{ color: 'var(--color-text-muted)' }}
                          />
                        )}
                        <span
                          className="text-sm truncate"
                          style={{ color: 'var(--color-text-primary)' }}
                        >
                          {row.filename}
                        </span>
                        <span
                          className="text-xs flex-shrink-0"
                          style={{ color: 'var(--color-text-muted)' }}
                        >
                          {row.status === 'error' ? 'Ошибка загрузки' : 'Загрузка…'}
                        </span>
                      </div>
                      <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                        —
                      </span>
                      <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                        —
                      </span>
                      <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                        —
                      </span>
                      <span />
                    </div>
                  ))}

                  {/* File rows */}
                  {filteredFiles.map((file) => {
                    const isSelected = selectedIds.has(file.id)
                    const menuOpen = activeMenu === file.id
                    const fileStatus = processingMap[file.id]
                    const isProcessing = fileStatus === 'pending' || fileStatus === 'processing'
                    const isError = fileStatus === 'error'
                    const isCancelled = fileStatus === 'cancelled'
                    return (
                      <div
                        key={file.id}
                        className="grid items-center px-2 py-2.5 transition-colors"
                        style={{
                          gridTemplateColumns: '28px 1fr 120px 100px 80px 32px',
                          borderBottom: '1px solid var(--color-border)',
                          backgroundColor: isSelected ? 'var(--color-bg-hover)' : undefined,
                          opacity: isProcessing ? 0.7 : 1,
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelect(file.id)}
                          onClick={e => e.stopPropagation()}
                          className="rounded cursor-pointer"
                        />
                        <div
                          className="flex items-center gap-2.5 min-w-0 pl-2 cursor-pointer"
                          onClick={() => !isProcessing && setViewerDoc({ id: file.id, filename: file.filename, file_type: file.file_type || '', created_at: file.created_at || '', classification: file.classification })}
                        >
                          {isProcessing ? (
                            <Loader2 className="w-3.5 h-3.5 flex-shrink-0 animate-spin" style={{ color: 'var(--color-text-muted)' }} />
                          ) : isError ? (
                            <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-error, #dc2626)' }} />
                          ) : isCancelled ? (
                            <X className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                          ) : (
                            <File className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                          )}
                          <span className="text-sm truncate hover:underline" style={{ color: 'var(--color-text-primary)' }}>
                            {file.filename}
                          </span>
                          {isCancelled && (
                            <span className="text-xs flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>Отменено</span>
                          )}
                          {isProcessing && (
                            <span className="text-xs flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
                              {fileStatus === 'processing' ? 'Обработка…' : 'Ожидание…'}
                            </span>
                          )}
                        </div>
                        <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                          {isProcessing ? '—' : (file.doc_type ? formatDocType(file.doc_type) : file.file_type || '—')}
                        </span>
                        <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                          {formatDate(file.created_at)}
                        </span>
                        <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                          {formatSize(file.size)}
                        </span>
                        <div className="relative flex justify-center" onClick={e => e.stopPropagation()}>
                          <button
                            onClick={(e) => openMenu(file.id, e)}
                            className="p-1 rounded transition-colors hover:bg-[var(--color-bg-hover)]"
                            style={{ color: 'var(--color-text-muted)' }}
                          >
                            <MoreHorizontal className="w-3.5 h-3.5" />
                          </button>
                          {menuOpen && (
                            <div
                              ref={menuRef}
                              className="rounded-xl shadow-lg py-1 w-48"
                              style={{
                                position: 'fixed',
                                top: menuAnchor?.top,
                                bottom: menuAnchor?.bottom,
                                right: menuAnchor?.right ?? 0,
                                backgroundColor: 'var(--color-bg-elevated)',
                                border: '1px solid var(--color-border)',
                                zIndex: 9999,
                              }}
                            >
                              <button
                                onClick={() => { setViewerDoc({ id: file.id, filename: file.filename, file_type: file.file_type || '', created_at: file.created_at || '', classification: file.classification }); setActiveMenu(null) }}
                                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors hover:bg-[var(--color-bg-hover)]"
                                style={{ color: 'var(--color-text-primary)' }}
                              >
                                <FileText className="w-3.5 h-3.5 flex-shrink-0" />
                                Просмотр
                              </button>
                              <button
                                onClick={() => handleOpenInEditor(file)}
                                disabled={openInEditorLoading === file.id}
                                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors hover:bg-[var(--color-bg-hover)] disabled:opacity-50"
                                style={{ color: 'var(--color-text-primary)' }}
                              >
                                {openInEditorLoading === file.id ? <Loader2 className="w-3.5 h-3.5 flex-shrink-0 animate-spin" /> : <FileEdit className="w-3.5 h-3.5 flex-shrink-0" />}
                                Открыть в редакторе
                              </button>
                              <button
                                onClick={() => openMoveModal([file.id])}
                                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors hover:bg-[var(--color-bg-hover)]"
                                style={{ color: 'var(--color-text-primary)' }}
                              >
                                <ArrowRight className="w-3.5 h-3.5 flex-shrink-0" />
                                Переместить
                              </button>
                              <div style={{ borderTop: '1px solid var(--color-border)' }} />
                              {isProcessing && (
                                <button
                                  onClick={() => handleCancelFile(file.id)}
                                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors hover:bg-[var(--color-bg-hover)]"
                                  style={{ color: 'var(--color-text-secondary)' }}
                                >
                                  <X className="w-3.5 h-3.5 flex-shrink-0" />
                                  Отменить обработку
                                </button>
                              )}
                              <button
                                onClick={() => handleDeleteFile(file.id)}
                                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors"
                                style={{ color: 'var(--color-error, #dc2626)' }}
                              >
                                <Trash2 className="w-3.5 h-3.5 flex-shrink-0" />
                                Удалить
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
                )
              })()}
            </section>

          </div>
        </div>

        {/* Selection action bar */}
        {selectedIds.size > 0 && (
          <div
            className="shrink-0 border-t flex items-center gap-3 px-8 py-3"
            style={{
              borderTopColor: 'var(--color-border)',
              backgroundColor: 'var(--color-bg-elevated)',
            }}
          >
            <span className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>
              Выбрано: {selectedIds.size}
            </span>
            <button
              onClick={() => {
                const fileIds = [...selectedIds].filter(id => !id.startsWith('folder-'))
                if (fileIds.length > 0) openMoveModal(fileIds)
              }}
              disabled={[...selectedIds].every(id => id.startsWith('folder-'))}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors hover:bg-[var(--color-bg-hover)] disabled:opacity-40"
              style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
            >
              <ArrowRight className="w-3.5 h-3.5" />
              Переместить
            </button>
            <button
              onClick={handleDeleteSelected}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors"
              style={{ borderColor: 'var(--color-error, #dc2626)', color: 'var(--color-error, #dc2626)' }}
            >
              <Trash2 className="w-3.5 h-3.5" />
              Удалить
            </button>
            <button
              onClick={() => setSelectedIds(new Set())}
              className="ml-auto p-1 transition-colors hover:opacity-70"
              style={{ color: 'var(--color-text-muted)' }}
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>

      {/* Rename folder modal */}
      {renameTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ backgroundColor: 'rgba(0,0,0,0.2)' }}>
          <div
            className="rounded-2xl shadow-xl w-96 p-6"
            style={{ backgroundColor: 'var(--color-bg-elevated)', border: '1px solid var(--color-border)' }}
          >
            <h2 className="text-base font-semibold mb-4" style={{ color: 'var(--color-text-primary)' }}>
              Переименовать папку
            </h2>
            <input
              autoFocus
              type="text"
              value={renameName}
              onChange={e => setRenameName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleRenameFolder(); if (e.key === 'Escape') setRenameTarget(null) }}
              className="w-full px-3 py-2 text-sm rounded-lg outline-none mb-4"
              style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-text-primary)' }}
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setRenameTarget(null)}
                className="px-4 py-2 text-sm rounded-lg transition-colors hover:bg-[var(--color-bg-hover)]"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                Отмена
              </button>
              <button
                onClick={handleRenameFolder}
                disabled={!renameName.trim()}
                className="px-4 py-2 text-sm rounded-lg transition-colors disabled:opacity-40"
                style={{ backgroundColor: 'var(--color-text-primary)', color: 'var(--color-bg-primary)' }}
              >
                Сохранить
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Move modal */}
      {showMoveModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ backgroundColor: 'rgba(0,0,0,0.2)' }}>
          <div
            className="rounded-2xl shadow-xl w-96 p-6"
            style={{ backgroundColor: 'var(--color-bg-elevated)', border: '1px solid var(--color-border)' }}
          >
            <h2 className="text-base font-semibold mb-1" style={{ color: 'var(--color-text-primary)' }}>
              Переместить в папку
            </h2>
            <p className="text-sm mb-4" style={{ color: 'var(--color-text-muted)' }}>
              {moveFileIds.length} файл(ов)
            </p>
            <div
              className="rounded-xl overflow-y-auto mb-4"
              style={{ border: '1px solid var(--color-border)', maxHeight: '240px' }}
            >
              <button
                onClick={() => setMoveDestFolderId(null)}
                className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm transition-colors text-left"
                style={{
                  backgroundColor: moveDestFolderId === null ? 'var(--color-bg-hover)' : undefined,
                  color: 'var(--color-text-primary)',
                }}
              >
                <FolderOpen className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                <span className="flex-1">Корень (без папки)</span>
                {moveDestFolderId === null && <Check className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-accent)' }} />}
              </button>
              {folders.map(f => (
                <button
                  key={f.id}
                  onClick={() => setMoveDestFolderId(f.id)}
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm transition-colors text-left"
                  style={{
                    borderTop: '1px solid var(--color-border)',
                    backgroundColor: moveDestFolderId === f.id ? 'var(--color-bg-hover)' : undefined,
                    color: 'var(--color-text-primary)',
                  }}
                >
                  <FolderOpen className="w-4 h-4 flex-shrink-0 text-amber-400" />
                  <span className="flex-1 truncate">{f.name}</span>
                  {moveDestFolderId === f.id && <Check className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-accent)' }} />}
                </button>
              ))}
              {folders.length === 0 && (
                <p className="px-3 py-4 text-sm text-center" style={{ color: 'var(--color-text-muted)' }}>
                  Папок нет. Сначала создайте папку.
                </p>
              )}
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowMoveModal(false)}
                className="px-4 py-2 text-sm rounded-lg transition-colors hover:bg-[var(--color-bg-hover)]"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                Отмена
              </button>
              <button
                onClick={handleMoveFiles}
                disabled={moveDestFolderId === undefined}
                className="px-4 py-2 text-sm rounded-lg transition-colors disabled:opacity-40"
                style={{
                  backgroundColor: 'var(--color-text-primary)',
                  color: 'var(--color-bg-primary)',
                }}
              >
                Переместить
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Query type modal ── */}
      {showQueryTypeModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ backgroundColor: 'rgba(0,0,0,0.25)' }}>
          <div
            className="rounded-2xl shadow-2xl w-[640px] p-8"
            style={{ backgroundColor: 'var(--color-bg-elevated)', border: '1px solid var(--color-border)' }}
          >
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                Выберите тип запроса
              </h2>
              <button
                onClick={() => setShowQueryTypeModal(false)}
                className="p-1.5 rounded-lg transition-colors hover:bg-[var(--color-bg-hover)]"
                style={{ color: 'var(--color-text-muted)' }}
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              {/* Tabular Review */}
              <button
                onClick={() => { setShowQueryTypeModal(false); setShowTabularHub(true) }}
                className="rounded-xl border p-5 text-left transition-all duration-150 hover:bg-[var(--color-bg-hover)] hover:shadow-sm"
                style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-primary)' }}
              >
                <div className="flex items-center justify-between mb-4">
                  <div
                    className="w-10 h-10 rounded-lg flex items-center justify-center"
                    style={{ backgroundColor: 'var(--color-bg-elevated)' }}
                  >
                    <Table className="w-4.5 h-4.5" style={{ color: 'var(--color-text-secondary)' }} />
                  </div>
                  <ChevronRight className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
                </div>
                <p className="text-sm font-semibold mb-1" style={{ color: 'var(--color-text-primary)' }}>
                  Таблица
                </p>
                <p className="text-xs leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
                  Один вопрос ко всем документам: сравнение, фильтр и экспорт
                </p>
              </button>

              {/* Assistant thread */}
              <button
                onClick={() => { setShowQueryTypeModal(false); navigate(`/cases/${caseId}/chat`) }}
                className="rounded-xl border p-5 text-left transition-all duration-150 hover:bg-[var(--color-bg-hover)] hover:shadow-sm"
                style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-primary)' }}
              >
                <div className="flex items-center justify-between mb-4">
                  <div
                    className="w-10 h-10 rounded-lg flex items-center justify-center"
                    style={{ backgroundColor: 'var(--color-bg-elevated)' }}
                  >
                    <MessageSquare className="w-4.5 h-4.5" style={{ color: 'var(--color-text-secondary)' }} />
                  </div>
                  <ChevronRight className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
                </div>
                <p className="text-sm font-semibold mb-1" style={{ color: 'var(--color-text-primary)' }}>
                  Ассистент
                </p>
                <p className="text-xs leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
                  Получите единый ответ, основанный на информации из всех файлов дела
                </p>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── File picker modal ── */}
      {showFilePicker && (() => {
        const pickerFiles = files.filter(f =>
          f.filename.toLowerCase().includes(pickerSearch.toLowerCase())
        )
        const allPicked = pickerFiles.length > 0 && pickerFiles.every(f => pickerSelectedIds.has(f.id))
        const toggleAll = () => {
          if (allPicked) setPickerSelectedIds(new Set())
          else setPickerSelectedIds(new Set(pickerFiles.map(f => f.id)))
        }
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ backgroundColor: 'rgba(0,0,0,0.25)' }}>
            <div
              className="rounded-2xl shadow-2xl w-[680px] flex flex-col"
              style={{ backgroundColor: 'var(--color-bg-elevated)', border: '1px solid var(--color-border)', maxHeight: '80vh' }}
            >
              {/* Header */}
              <div className="px-6 py-5 border-b" style={{ borderBottomColor: 'var(--color-border)' }}>
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-base font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                    Выберите файлы
                  </h2>
                  <button
                    onClick={() => { setShowFilePicker(false); setPickerSelectedIds(new Set()); setPickerSearch('') }}
                    className="p-1.5 rounded-lg transition-colors hover:bg-[var(--color-bg-hover)]"
                    style={{ color: 'var(--color-text-muted)' }}
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <div
                  className="flex items-center gap-2 px-3 py-2 rounded-lg border"
                  style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-primary)' }}
                >
                  <Search className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                  <input
                    type="text"
                    placeholder="Поиск файлов..."
                    value={pickerSearch}
                    onChange={e => setPickerSearch(e.target.value)}
                    className="flex-1 bg-transparent outline-none text-sm"
                    style={{ color: 'var(--color-text-primary)' }}
                    autoFocus
                  />
                </div>
              </div>

              {/* Table header */}
              <div
                className="grid text-xs font-medium px-4 py-2.5 border-b"
                style={{
                  gridTemplateColumns: '32px 1fr 160px 100px',
                  borderBottomColor: 'var(--color-border)',
                  color: 'var(--color-text-muted)',
                }}
              >
                <input type="checkbox" checked={allPicked} onChange={toggleAll} className="rounded cursor-pointer" />
                <span>Название</span>
                <span>Тип документа</span>
                <span>Размер</span>
              </div>

              {/* File list */}
              <div className="flex-1 overflow-y-auto">
                {pickerFiles.length === 0 ? (
                  <div className="py-12 text-center text-sm" style={{ color: 'var(--color-text-muted)' }}>
                    {files.length === 0 ? 'Нет файлов в деле' : 'Ничего не найдено'}
                  </div>
                ) : pickerFiles.map(file => {
                  const checked = pickerSelectedIds.has(file.id)
                  return (
                    <label
                      key={file.id}
                      className="grid items-center px-4 py-2.5 cursor-pointer transition-colors hover:bg-[var(--color-bg-hover)]"
                      style={{
                        gridTemplateColumns: '32px 1fr 160px 100px',
                        borderBottom: '1px solid var(--color-border)',
                        backgroundColor: checked ? 'var(--color-bg-hover)' : undefined,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => {
                          setPickerSelectedIds(prev => {
                            const next = new Set(prev)
                            if (next.has(file.id)) next.delete(file.id)
                            else next.add(file.id)
                            return next
                          })
                        }}
                        className="rounded cursor-pointer"
                      />
                      <div className="flex items-center gap-2 min-w-0 pr-4">
                        <FileText className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                        <span className="text-sm truncate" style={{ color: 'var(--color-text-primary)' }}>
                          {file.filename}
                        </span>
                      </div>
                      <span className="text-xs pr-4 truncate" style={{ color: 'var(--color-text-muted)' }}>
                        {formatDocType(file.doc_type || file.file_type)}
                      </span>
                      <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                        {[formatSize(file.size), file.pages ? `${file.pages} стр.` : null].filter(Boolean).join(' · ')}
                      </span>
                    </label>
                  )
                })}
              </div>

              {/* Footer */}
              <div
                className="flex items-center justify-between px-6 py-4 border-t"
                style={{ borderTopColor: 'var(--color-border)' }}
              >
                <span className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                  {pickerSelectedIds.size > 0 ? `${pickerSelectedIds.size} файл(ов) выбрано` : 'Выберите файлы'}
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={() => { setShowFilePicker(false); setShowQueryTypeModal(true); setPickerSelectedIds(new Set()); setPickerSearch('') }}
                    className="px-4 py-2 text-sm rounded-lg transition-colors hover:bg-[var(--color-bg-hover)]"
                    style={{ color: 'var(--color-text-secondary)' }}
                  >
                    Назад
                  </button>
                  <button
                    onClick={handleCreateReview}
                    disabled={pickerSelectedIds.size === 0 || creatingReview}
                    className="px-4 py-2 text-sm rounded-lg transition-colors disabled:opacity-40 flex items-center gap-2"
                    style={{ backgroundColor: 'var(--color-text-primary)', color: 'var(--color-bg-primary)' }}
                  >
                    {creatingReview && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                    Создать таблицу
                  </button>
                </div>
              </div>
            </div>
          </div>
        )
      })()}

      {/* Document viewer drawer */}
      <Drawer anchor="right" open={!!viewerDoc} onClose={() => setViewerDoc(null)}>
        <div style={{ width: 600, height: '100%', display: 'flex', flexDirection: 'column' }}>
          <div
            className="flex items-center justify-between px-4 py-3 border-b shrink-0"
            style={{ borderBottomColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-elevated)' }}
          >
            <span className="font-medium text-sm truncate max-w-xs" style={{ color: 'var(--color-text-primary)' }}>
              {viewerDoc?.filename}
            </span>
            <button
              onClick={() => setViewerDoc(null)}
              className="p-1.5 rounded-lg transition-colors ml-3 shrink-0 hover:bg-[var(--color-bg-hover)]"
              style={{ color: 'var(--color-text-muted)' }}
            >
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="flex-1 overflow-auto">
            {viewerDoc && caseId && (
              <DocumentViewer document={viewerDoc} caseId={caseId} />
            )}
          </div>
        </div>
      </Drawer>

      {/* All actions drawer */}
      <Drawer anchor="right" open={showAllActions} onClose={() => setShowAllActions(false)}>
        <div style={{ width: 480, height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--color-bg-primary)' }}>
          <div
            className="flex items-center justify-between px-4 py-3 border-b shrink-0"
            style={{ borderBottomColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-elevated)' }}
          >
            <span className="font-medium text-sm" style={{ color: 'var(--color-text-primary)' }}>
              Все действия
            </span>
            <button
              onClick={() => setShowAllActions(false)}
              className="p-1.5 rounded-lg transition-colors hover:bg-[var(--color-bg-hover)]"
              style={{ color: 'var(--color-text-muted)' }}
            >
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="flex-1 overflow-auto">
            {(() => {
              type ActionItem =
                | { kind: 'chat'; session_id: string; first_message: string; last_message_at: string | null; message_count: number; date: number }
                | { kind: 'review'; id: string; name: string; status: string; date: number }

              const chatItems: ActionItem[] = sessions.map(s => ({
                kind: 'chat' as const, ...s,
                date: s.last_message_at ? new Date(s.last_message_at).getTime() : 0,
              }))
              const reviewItems: ActionItem[] = reviews.map(r => ({
                kind: 'review' as const, ...r,
                date: r.updated_at ? new Date(r.updated_at).getTime() : (r.created_at ? new Date(r.created_at).getTime() : 0),
              }))
              const allItems = [...chatItems, ...reviewItems].sort((a, b) => b.date - a.date)

              if (allItems.length === 0) {
                return (
                  <p className="text-sm px-4 py-8" style={{ color: 'var(--color-text-muted)' }}>
                    Действий пока нет
                  </p>
                )
              }

              return (
                <div>
                  {allItems.map((item) => (
                    <button
                      key={item.kind === 'chat' ? `chat-${item.session_id}` : `review-${item.id}`}
                      onClick={() => {
                        setShowAllActions(false)
                        if (item.kind === 'chat') navigate(`/cases/${caseId}/chat?session=${item.session_id}`)
                        else navigate(`/cases/${caseId}/tabular-review/${item.id}`)
                      }}
                      className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-[var(--color-bg-hover)] transition-colors"
                      style={{ borderBottom: '1px solid var(--color-border)' }}
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        {item.kind === 'chat' ? (
                          <MessageSquare className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                        ) : (
                          <Table className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                        )}
                        <span className="text-sm truncate" style={{ color: 'var(--color-text-primary)' }}>
                          {item.kind === 'chat' ? (item.first_message || 'Сессия') : item.name}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 flex-shrink-0 ml-4">
                        <span
                          className="text-xs px-1.5 py-0.5 rounded"
                          style={{
                            color: item.kind === 'chat' ? 'var(--color-accent)' : 'rgba(16,185,129,0.9)',
                            backgroundColor: item.kind === 'chat' ? 'var(--color-accent-subtle, rgba(99,102,241,0.08))' : 'rgba(16,185,129,0.08)',
                          }}
                        >
                          {item.kind === 'chat' ? 'Ассистент' : 'Таблица'}
                        </span>
                        <span className="text-xs flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
                          {formatDate(item.date ? new Date(item.date).toISOString() : undefined)}
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              )
            })()}
          </div>
        </div>
      </Drawer>

      {caseId && (
        <CaseTabularHubModal
          open={showTabularHub}
          onClose={() => setShowTabularHub(false)}
          caseId={caseId}
          files={files.map((f) => ({ id: f.id, filename: f.filename }))}
          reviews={reviews}
          loadingReviews={loadingReviews}
          onReviewOpen={(reviewId) => navigate(`/cases/${caseId}/tabular-review/${reviewId}`)}
          onReviewsChanged={loadAll}
        />
      )}
    </div>
  )
}

export default CaseOverviewPage
