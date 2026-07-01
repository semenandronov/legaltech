import { useState, useEffect, useRef, Fragment, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  MessageSquare, FolderOpen, FileText, Table,
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
import { useCaseStagedUpload } from '../hooks/useCaseStagedUpload'
import { consumeCaseStagedUploadResult, clearCaseStagedUpload } from '../lib/caseStagedUploadCoordinator'
import {
  formatCaseDocumentCountLabel,
  removePendingRowsForUploads,
  type PostCreatePendingRow,
} from '../lib/postCreatePendingFiles'
import { tabularReviewApi } from '../services/tabularReviewApi'
import { CaseTabularHubModal } from '../components/TabularReview/CaseTabularHubModal'
import { CaseOverviewPageHeader } from '../components/CaseOverview/CaseOverviewPageHeader'
import { MikeTableToolbar } from '../components/TabularReview/mike/MikeTableToolbar'
import { TABLE_CHECKBOX_CLASS } from '../components/TabularReview/mike/mikeTablePrimitives'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import DocumentViewer from '../components/Documents/DocumentViewer'
import { DocumentWithMetadata } from '../components/Documents/DocumentsList'
import { GoogleDriveImportButton } from '../components/Documents/GoogleDriveImportButton'
import { buildMainNavItems } from '@/lib/mainNavItems'
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
] as const

function isCaseAssistantChatSession(sessionId: string): boolean {
  return !sessionId.startsWith('tabular:')
}

const CaseOverviewPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const {
    isUploading: isStagedUploading,
    pendingRows: stagedPendingRows,
    statusMessage: stagedUploadStatus,
    isError: isStagedUploadError,
    errorMessage: stagedUploadError,
    snapshot: stagedUploadSnapshot,
  } = useCaseStagedUpload(caseId)

  const [inlinePendingRows, setInlinePendingRows] = useState<PostCreatePendingRow[]>([])

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

  const handleFilesAdded = useCallback((result: FilesResponse) => {
    mergeUploadedIntoList(result.files ?? [])
    setInlinePendingRows((prev) => removePendingRowsForUploads(prev, result.files ?? []))
    setCaseData((prev) =>
      prev ? { ...prev, num_documents: result.total ?? prev.num_documents } : prev,
    )
    ingestUploadResponse(result)
  }, [ingestUploadResponse])

  const applyStagedUploadResult = useCallback(
    (result: { responses: FilesResponse[]; driveErrors: string[] }) => {
      for (const res of result.responses) {
        mergeUploadedIntoList(res.files ?? [])
        ingestUploadResponse(res)
      }
      const fileCount = result.responses.reduce((n, res) => n + (res.files?.length ?? 0), 0)
      if (result.driveErrors.length > 0) {
        toast.error(result.driveErrors.join('; '))
      } else if (fileCount > 0) {
        toast.success(
          fileCount === 1
            ? 'Файл добавлен, идёт обработка'
            : `Добавлено файлов: ${fileCount}, идёт обработка`,
        )
      }
      if (caseId) {
        void getCase(caseId).then((data) => setCaseData(data))
        void getDocuments(caseId).then((d) => setFiles(mapCaseDocuments(d.documents || [])))
      }
    },
    [caseId, ingestUploadResponse],
  )

  const stagedUploadErrorShownRef = useRef<string | null>(null)

  useEffect(() => {
    if (!caseId || stagedUploadSnapshot?.phase !== 'done') return
    consumeCaseStagedUploadResult(caseId, applyStagedUploadResult)
  }, [caseId, stagedUploadSnapshot?.phase, applyStagedUploadResult])

  useEffect(() => {
    if (!caseId || !isStagedUploadError || !stagedUploadError) return
    if (stagedUploadErrorShownRef.current === stagedUploadError) return
    stagedUploadErrorShownRef.current = stagedUploadError
    toast.error(stagedUploadError)
    clearCaseStagedUpload(caseId)
  }, [caseId, isStagedUploadError, stagedUploadError])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!caseId || !e.target.files || e.target.files.length === 0) return
    const filesToUpload = Array.from(e.target.files)
    e.target.value = ''
    const optimisticRows: PostCreatePendingRow[] = filesToUpload.map((file, index) => ({
      stagingKey: `inline-${Date.now()}-${index}`,
      filename: file.name,
      source: 'local',
      status: 'uploading',
    }))
    setInlinePendingRows((prev) => [...prev, ...optimisticRows])
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
      setInlinePendingRows((prev) =>
        prev.filter((row) => !optimisticRows.some((opt) => opt.stagingKey === row.stagingKey)),
      )
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

  const navItems = buildMainNavItems()

  const allPendingRows = useMemo(
    () => [...stagedPendingRows, ...inlinePendingRows],
    [stagedPendingRows, inlinePendingRows],
  )
  const isFileListBusy = isStagedUploading || uploading

  // Root-level files only (no folder). When search is active, show all matching files regardless of folder.
  const filteredFiles = files.filter(f =>
    (fileSearch ? true : !f.folder_id) &&
    f.filename.toLowerCase().includes(fileSearch.toLowerCase())
  )

  const filteredPendingRows = allPendingRows.filter((row) =>
    row.filename.toLowerCase().includes(fileSearch.toLowerCase()),
  )

  const hasVisibleFileSection =
    allPendingRows.length > 0 || files.length > 0 || folders.length > 0 || isFileListBusy

  const documentCountLabel = formatCaseDocumentCountLabel(
    caseData?.num_documents ?? 0,
    files.length,
    allPendingRows,
    isFileListBusy,
  )

  const getFilesInFolder = (folderId: string) =>
    files.filter(f =>
      f.folder_id === folderId &&
      f.filename.toLowerCase().includes(fileSearch.toLowerCase())
    )

  const assistantSessions = sessions.filter((s) => isCaseAssistantChatSession(s.session_id))

  return (
    <div className="ws-shell ws-tabular-shell flex h-screen overflow-hidden">
      <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton={false} variant="tabular" />

      <div className="ws-tabular-page flex min-h-0 flex-1 flex-col overflow-hidden">
        <CaseOverviewPageHeader
          loading={loadingCase}
          caseTitle={caseData?.title}
          documentCountLabel={documentCountLabel}
          onNavigateCases={() => navigate('/cases')}
        />

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto px-4 pb-8 md:px-10">
            {/* Create new section */}
            <section className="mb-8 mt-4">
              <h2 className="mb-3 text-xs font-medium text-gray-500">Начать работу</h2>
              <div className="grid grid-cols-3 gap-3">
                <button
                  onClick={() => setShowQueryTypeModal(true)}
                  className="group flex min-h-[88px] flex-col items-start gap-2 rounded-lg border border-dashed border-gray-300 bg-white/60 p-4 text-left transition-colors hover:border-gray-400 hover:bg-[#fafbfc]"
                >
                  <div className="flex h-7 w-7 items-center justify-center rounded-md border border-gray-200 transition-colors group-hover:border-gray-400">
                    <Plus className="h-4 w-4 text-gray-500" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-gray-900">Новый запрос</p>
                    <p className="mt-0.5 text-xs leading-snug text-gray-400">
                      Выберите тип запроса и файлы
                    </p>
                  </div>
                </button>

                {/* Preset cards */}
                {PRESETS.map((preset) => (
                  <button
                    key={preset.id}
                    onClick={() => {
                      if (preset.id === 'tabular') {
                        setShowTabularHub(true)
                        return
                      }
                      navigate(preset.path(caseId!))
                    }}
                    className="flex min-h-[88px] flex-col items-start gap-2 rounded-lg border border-gray-200 bg-white p-4 text-left transition-colors hover:border-gray-300 hover:bg-[#fafbfc]"
                  >
                    <div className="flex w-full items-center justify-between">
                      <p className="text-sm font-medium text-gray-900">{preset.title}</p>
                      <ChevronRight className="h-3.5 w-3.5 text-gray-400" />
                    </div>
                    <p className="text-xs leading-snug text-gray-400">{preset.description}</p>
                  </button>
                ))}
              </div>
            </section>

            {/* Recent actions section */}
            <section className="mb-8">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-xs font-medium text-gray-500">Последние действия</h2>
                {(assistantSessions.length + reviews.length) > 5 && (
                  <button
                    onClick={() => setShowAllActions(true)}
                    className="text-xs text-gray-400 transition-colors hover:text-gray-600"
                  >
                    Все действия ({assistantSessions.length + reviews.length})
                  </button>
                )}
              </div>
              {(loadingSessions || loadingReviews) ? (
                <div className="space-y-2">
                  {[...Array(3)].map((_, i) => (
                    <div key={i} className="h-10 animate-pulse rounded-lg bg-gray-100" />
                  ))}
                </div>
              ) : (() => {
                type ActionItem =
                  | { kind: 'chat'; session_id: string; first_message: string; last_message_at: string | null; message_count: number; date: number }
                  | { kind: 'review'; id: string; name: string; status: string; date: number }

                const chatItems: ActionItem[] = assistantSessions.map(s => ({
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
                    <p className="py-4 text-sm text-gray-400">Действий пока нет</p>
                  )
                }

                return (
                  <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
                    {allItems.map((item, i) => (
                      <button
                        key={item.kind === 'chat' ? `chat-${item.session_id}` : `review-${item.id}`}
                        onClick={() => {
                          if (item.kind === 'chat') navigate(`/cases/${caseId}/chat?session=${item.session_id}`)
                          else navigate(`/cases/${caseId}/tabular-review/${item.id}`)
                        }}
                        className={`flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-gray-50 ${
                          i < allItems.length - 1 ? 'border-b border-gray-50' : ''
                        }`}
                      >
                        <div className="flex min-w-0 items-center gap-3">
                          {item.kind === 'chat' ? (
                            <MessageSquare className="h-3.5 w-3.5 shrink-0 text-gray-400" />
                          ) : (
                            <Table className="h-3.5 w-3.5 shrink-0 text-gray-400" />
                          )}
                          <span className="truncate text-sm text-gray-800">
                            {item.kind === 'chat' ? (item.first_message || 'Сессия') : item.name}
                          </span>
                        </div>
                        <div className="ml-4 flex shrink-0 items-center gap-3">
                          <span
                            className={`rounded px-1.5 py-0.5 text-xs ${
                              item.kind === 'chat'
                                ? 'bg-indigo-50 text-indigo-600'
                                : 'bg-emerald-50 text-emerald-600'
                            }`}
                          >
                            {item.kind === 'chat' ? 'Ассистент' : 'Таблица'}
                          </span>
                          <span className="text-xs text-gray-400">
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
              {(isStagedUploading || uploading) && (
                <div className="mb-3 flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm text-gray-600">
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin text-gray-400" />
                  <span>
                    {isStagedUploading
                      ? stagedUploadStatus || 'Загрузка файлов в дело…'
                      : 'Загрузка файлов…'}
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
                if (isStagedUploading || uploading || total === 0 || pendingFiles.length === 0) return null

                // Recalculate estimate from remaining pending files
                const estimatedSecs = pendingFiles.reduce((sum, f) => sum + estimateFileSecs(f.filename, f.size), 0)
                const remaining = Math.max(0, estimatedSecs - elapsedSeconds)
                const countdownStr = remaining === 0
                  ? 'завершается…'
                  : remaining < 60
                  ? `ещё ~${remaining} сек`
                  : `ещё ~${Math.ceil(remaining / 60)} мин`
                return (
                  <div className="mb-3 flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm text-gray-600">
                    <Loader2 className="h-4 w-4 shrink-0 animate-spin text-gray-400" />
                    <span>
                      Обработка файлов…{' '}
                      <span className="font-medium text-gray-900">
                        {ready} из {total} готово
                      </span>
                      <span className="text-gray-400"> · {countdownStr}</span>
                    </span>
                    <span className="ml-auto text-xs text-gray-400">
                      Вы можете работать с готовыми файлами, остальные появятся автоматически
                    </span>
                  </div>
                )
              })()}

              <MikeTableToolbar
                leading={
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-medium text-gray-700">Файлы</span>
                    <div className="flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-3 py-1">
                      <Search className="h-3 w-3 shrink-0 text-gray-400" />
                      <input
                        type="text"
                        value={fileSearch}
                        onChange={(e) => setFileSearch(e.target.value)}
                        placeholder="Поиск"
                        className="w-28 bg-transparent text-xs text-gray-700 outline-none placeholder:text-gray-400"
                      />
                    </div>
                  </div>
                }
                actions={
                  <div className="flex items-center gap-2">
                    {creatingFolder ? (
                      <>
                        <div className="flex items-center gap-1">
                          <input
                            ref={folderInputRef}
                            type="text"
                            value={newFolderName}
                            onChange={(e) => setNewFolderName(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') handleCreateFolder()
                              if (e.key === 'Escape') {
                                setCreatingFolder(false)
                                setNewFolderName('')
                                setFolderError(null)
                              }
                            }}
                            autoFocus
                            placeholder="Название папки"
                            className={`w-[140px] rounded-lg border px-2 py-1.5 text-xs outline-none ${
                              folderError ? 'border-red-300' : 'border-gray-200'
                            } bg-white text-gray-900`}
                          />
                          <button
                            type="button"
                            onClick={handleCreateFolder}
                            disabled={!newFolderName.trim()}
                            className="rounded-lg bg-gray-900 px-2 py-1.5 text-xs font-medium text-white transition-opacity disabled:opacity-40"
                          >
                            ОК
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setCreatingFolder(false)
                              setNewFolderName('')
                              setFolderError(null)
                            }}
                            className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs text-gray-500 transition-colors hover:bg-gray-50"
                          >
                            Отмена
                          </button>
                        </div>
                        {folderError && <p className="text-xs text-red-600">{folderError}</p>}
                      </>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setCreatingFolder(true)}
                        className="flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50"
                      >
                        <FolderOpen className="h-3.5 w-3.5" />
                        Создать папку
                      </button>
                    )}
                    <input
                      ref={fileInputRef}
                      type="file"
                      multiple
                      className="hidden"
                      onChange={handleUpload}
                    />
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={uploading}
                      className="flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50"
                    >
                      {uploading ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Upload className="h-3.5 w-3.5" />
                      )}
                      Загрузить
                    </button>
                    {caseId && (
                      <GoogleDriveImportButton
                        caseId={caseId}
                        variant="pill"
                        label="Google Drive"
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
                }
              />

              {loadingFiles && !hasVisibleFileSection ? (
                <div className="space-y-0 border-t border-gray-200">
                  {[...Array(4)].map((_, i) => (
                    <div key={i} className="h-10 animate-pulse border-b border-gray-50 bg-gray-50/50" />
                  ))}
                </div>
              ) : !hasVisibleFileSection ? (
                <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-gray-300 bg-white/60 py-12">
                  <p className="mb-3 text-sm text-gray-400">Файлы не загружены</p>
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
                  >
                    <Upload className="h-4 w-4" />
                    Загрузить файлы
                  </button>
                  {caseId && (
                    <GoogleDriveImportButton
                      caseId={caseId}
                      variant="pill"
                      label="Google Drive"
                      className="mt-3"
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
                <div className="overflow-hidden border-t border-gray-200 bg-white">
                  <div
                    className="grid h-8 items-center border-b border-gray-200 bg-[#fafbfc] px-2 text-xs font-medium text-gray-500"
                    style={{ gridTemplateColumns: '28px 1fr 120px 100px 80px 32px' }}
                  >
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleSelectAll}
                      className={TABLE_CHECKBOX_CLASS}
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
                          className={`grid cursor-pointer items-center px-2 py-2.5 transition-colors hover:bg-gray-50 ${
                            isSelected ? 'bg-gray-50' : 'bg-white'
                          }`}
                          style={{ gridTemplateColumns: '28px 1fr 120px 100px 80px 32px' }}
                          onClick={() => toggleFolderExpand(folder.id)}
                        >
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelect(rowId)}
                            onClick={e => e.stopPropagation()}
                            className={TABLE_CHECKBOX_CLASS}
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
                          <span className="text-xs text-gray-500">Папка</span>
                          <span className="text-xs text-gray-500">—</span>
                          <span className="text-xs text-gray-500">—</span>
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
                                    className={TABLE_CHECKBOX_CLASS}
                                  />
                                  <div
                                    className="flex items-center gap-2 min-w-0 pl-8 cursor-pointer"
                                    onClick={() => setViewerDoc({ id: file.id, filename: file.filename, file_type: file.file_type || '', created_at: file.created_at || '', classification: file.classification })}
                                  >
                                    <File className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                                    <span className="truncate text-sm text-gray-800 hover:underline">
                                      {file.filename}
                                    </span>
                                  </div>
                                  <span className="text-xs text-gray-500">{file.doc_type || file.file_type || '—'}</span>
                                  <span className="text-xs text-gray-500">{formatDate(file.created_at)}</span>
                                  <span className="text-xs text-gray-500">{formatSize(file.size)}</span>
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
                        className={`grid h-10 items-center border-b border-gray-50 px-2 transition-colors hover:bg-gray-50 ${
                          isSelected ? 'bg-gray-50' : 'bg-white'
                        }`}
                        style={{
                          gridTemplateColumns: '28px 1fr 120px 100px 80px 32px',
                          opacity: isProcessing ? 0.7 : 1,
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelect(file.id)}
                          onClick={e => e.stopPropagation()}
                          className={TABLE_CHECKBOX_CLASS}
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
                          <span className="truncate text-sm text-gray-800 hover:underline">
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
                        <span className="text-xs text-gray-500">
                          {isProcessing ? '—' : (file.doc_type ? formatDocType(file.doc_type) : file.file_type || '—')}
                        </span>
                        <span className="text-xs text-gray-500">
                          {formatDate(file.created_at)}
                        </span>
                        <span className="text-xs text-gray-500">
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

        {/* Selection action bar */}
        {selectedIds.size > 0 && (
          <div className="flex shrink-0 items-center gap-3 border-t border-gray-200 bg-white px-4 py-3 md:px-10">
            <span className="text-sm font-medium text-gray-600">Выбрано: {selectedIds.size}</span>
            <button
              type="button"
              onClick={() => {
                const fileIds = [...selectedIds].filter((id) => !id.startsWith('folder-'))
                if (fileIds.length > 0) openMoveModal(fileIds)
              }}
              disabled={[...selectedIds].every((id) => id.startsWith('folder-'))}
              className="flex items-center gap-1.5 rounded-full border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-40"
            >
              <ArrowRight className="h-3.5 w-3.5" />
              Переместить
            </button>
            <button
              type="button"
              onClick={handleDeleteSelected}
              className="flex items-center gap-1.5 rounded-full border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-50"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Удалить
            </button>
            <button
              type="button"
              onClick={() => setSelectedIds(new Set())}
              className="ml-auto p-1 text-gray-400 transition-colors hover:text-gray-600"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}
        </div>
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
                <input type="checkbox" checked={allPicked} onChange={toggleAll} className={TABLE_CHECKBOX_CLASS} />
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
                        className={TABLE_CHECKBOX_CLASS}
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

              const chatItems: ActionItem[] = assistantSessions.map(s => ({
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
