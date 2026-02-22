import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Folder, FileText, MoreHorizontal, Search, FolderPlus, Upload,
  ChevronRight, Trash2, Pencil, MessageSquare, Table, FileEdit,
  BookOpen, Workflow, Loader2, Check, X, ArrowRight,
} from 'lucide-react'
import { createDocumentFromFile } from '../services/documentEditorApi'
import { Drawer } from '@mui/material'
import { toast } from 'sonner'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import DocumentUploadModal from '../components/Documents/DocumentUploadModal'
import DocumentViewer from '../components/Documents/DocumentViewer'
import { DocumentWithMetadata } from '../components/Documents/DocumentsList'
import {
  getCaseFolders, createFolder, renameFolder, deleteFolder, moveFileToFolder,
  deleteFileFromCase, FolderItem, getDocuments,
} from '../services/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface DocumentFile {
  id: string
  filename: string
  file_type?: string
  folder_id?: string | null
  created_at?: string
  doc_type?: string
  classification?: any
  status?: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function flattenFolders(folders: FolderItem[]): FolderItem[] {
  const result: FolderItem[] = []
  const add = (list: FolderItem[]) => {
    for (const f of list) {
      result.push(f)
      if (f.children?.length) add(f.children)
    }
  }
  add(folders)
  return result
}

function getBreadcrumb(folders: FolderItem[], folderId: string | null): FolderItem[] {
  if (!folderId) return []
  const folder = folders.find(f => f.id === folderId)
  if (!folder) return []
  return [...getBreadcrumb(folders, folder.parent_id), folder]
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

function toViewerDoc(file: DocumentFile): DocumentWithMetadata {
  return {
    id: file.id,
    filename: file.filename,
    file_type: file.file_type || '',
    created_at: file.created_at || '',
    classification: file.classification,
  }
}

const NAV_ITEMS = (caseId: string) => [
  { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
  { id: 'documents', label: 'Документы', icon: FileText, path: `/cases/${caseId}/documents` },
  { id: 'editor', label: 'Редактор', icon: FileEdit, path: `/cases/${caseId}/editor` },
  { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: `/cases/${caseId}/tabular-review` },
  { id: 'playbooks', label: 'Playbooks', icon: BookOpen, path: `/cases/${caseId}/playbooks` },
  { id: 'workflows', label: 'Workflows', icon: Workflow, path: `/cases/${caseId}/workflows` },
]

// ── Component ─────────────────────────────────────────────────────────────────

const DocumentsPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()

  const [allDocuments, setAllDocuments] = useState<DocumentFile[]>([])
  const [allFolders, setAllFolders] = useState<FolderItem[]>([])
  const [loading, setLoading] = useState(true)
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  // Selection
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  // Modals
  const [showUpload, setShowUpload] = useState(false)
  const [showCreateFolder, setShowCreateFolder] = useState(false)
  const [newFolderName, setNewFolderName] = useState('')
  const [creatingFolder, setCreatingFolder] = useState(false)
  const [renameTarget, setRenameTarget] = useState<FolderItem | null>(null)
  const [renameName, setRenameName] = useState('')
  const [showMoveModal, setShowMoveModal] = useState(false)
  const [moveFileIds, setMoveFileIds] = useState<string[]>([])
  const [moveDestFolderId, setMoveDestFolderId] = useState<string | null | undefined>(undefined)

  // Dropdown menu
  const [activeMenu, setActiveMenu] = useState<string | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  // Document viewer
  const [viewerDoc, setViewerDoc] = useState<DocumentWithMetadata | null>(null)

  // Open in editor
  const [openInEditorLoading, setOpenInEditorLoading] = useState<string | null>(null)

  // ── Data loading ───────────────────────────────────────────────────────────

  const loadAll = useCallback(async () => {
    if (!caseId) return
    setLoading(true)
    try {
      const [docsData, foldersTree] = await Promise.all([
        getDocuments(caseId),
        getCaseFolders(caseId).catch(() => [] as FolderItem[]),
      ])
      setAllDocuments(
        docsData.documents.map((d: any) => ({
          id: d.id,
          filename: d.filename,
          file_type: d.file_type,
          folder_id: d.folder_id ?? null,
          created_at: d.created_at,
          doc_type: d.doc_type || d.classification?.doc_type,
          classification: d.classification,
          status: d.status,
        }))
      )
      setAllFolders(flattenFolders(foldersTree))
    } catch {
      toast.error('Не удалось загрузить файлы')
    } finally {
      setLoading(false)
    }
  }, [caseId])

  useEffect(() => { loadAll() }, [loadAll])

  // Close menu on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setActiveMenu(null)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // ── Derived state ──────────────────────────────────────────────────────────

  const breadcrumb = getBreadcrumb(allFolders, currentFolderId)

  const currentFolders = allFolders
    .filter(f => f.parent_id === currentFolderId)
    .filter(f => !searchQuery || f.name.toLowerCase().includes(searchQuery.toLowerCase()))

  const currentFiles = allDocuments
    .filter(f => (f.folder_id ?? null) === currentFolderId)
    .filter(f => !searchQuery || f.filename.toLowerCase().includes(searchQuery.toLowerCase()))

  const allCurrentIds = [
    ...currentFolders.map(f => `folder-${f.id}`),
    ...currentFiles.map(f => f.id),
  ]
  const allSelected = allCurrentIds.length > 0 && allCurrentIds.every(id => selectedIds.has(id))

  // ── Selection ──────────────────────────────────────────────────────────────

  const toggleSelectAll = () => {
    if (allSelected) setSelectedIds(new Set())
    else setSelectedIds(new Set(allCurrentIds))
  }

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // ── CRUD ───────────────────────────────────────────────────────────────────

  const handleCreateFolder = async () => {
    if (!caseId || !newFolderName.trim()) return
    setCreatingFolder(true)
    try {
      await createFolder(caseId, newFolderName.trim(), currentFolderId)
      toast.success('Папка создана')
      setNewFolderName('')
      setShowCreateFolder(false)
      await loadAll()
    } catch {
      toast.error('Не удалось создать папку')
    } finally {
      setCreatingFolder(false)
    }
  }

  const handleRenameFolder = async () => {
    if (!caseId || !renameTarget || !renameName.trim()) return
    try {
      await renameFolder(caseId, renameTarget.id, renameName.trim())
      toast.success('Папка переименована')
      setRenameTarget(null)
      await loadAll()
    } catch {
      toast.error('Не удалось переименовать')
    }
  }

  const handleDeleteFolder = async (folderId: string) => {
    if (!caseId) return
    try {
      await deleteFolder(caseId, folderId)
      toast.success('Папка удалена')
      setActiveMenu(null)
      await loadAll()
    } catch {
      toast.error('Не удалось удалить папку')
    }
  }

  const handleDeleteFile = async (fileId: string) => {
    if (!caseId) return
    try {
      await deleteFileFromCase(caseId, fileId)
      toast.success('Файл удалён')
      setActiveMenu(null)
      await loadAll()
    } catch {
      toast.error('Не удалось удалить файл')
    }
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

  const openMoveModal = (fileIds: string[]) => {
    setMoveFileIds(fileIds)
    setMoveDestFolderId(undefined)
    setShowMoveModal(true)
    setActiveMenu(null)
  }

  const handleMoveFiles = async () => {
    if (!caseId || moveFileIds.length === 0) return
    try {
      await Promise.all(
        moveFileIds.map(id => moveFileToFolder(caseId, id, moveDestFolderId ?? null))
      )
      toast.success(`Перемещено ${moveFileIds.length} файл(ов)`)
      setShowMoveModal(false)
      setSelectedIds(new Set())
      setMoveFileIds([])
      await loadAll()
    } catch {
      toast.error('Не удалось переместить')
    }
  }

  const handleDeleteSelected = async () => {
    if (!caseId) return
    const fileIds = [...selectedIds].filter(id => !id.startsWith('folder-'))
    const folderIds = [...selectedIds]
      .filter(id => id.startsWith('folder-'))
      .map(id => id.replace('folder-', ''))
    try {
      await Promise.all([
        ...fileIds.map(id => deleteFileFromCase(caseId, id)),
        ...folderIds.map(id => deleteFolder(caseId, id)),
      ])
      toast.success('Удалено')
      setSelectedIds(new Set())
      await loadAll()
    } catch {
      toast.error('Ошибка при удалении')
    }
  }

  // ── Loading ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex h-screen bg-bg-primary">
        {caseId && <UnifiedSidebar navItems={NAV_ITEMS(caseId)} title="Legal AI" />}
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
        </div>
      </div>
    )
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-screen bg-bg-primary overflow-hidden">
      {caseId && <UnifiedSidebar navItems={NAV_ITEMS(caseId)} title="Legal AI" />}

      <div className="flex-1 flex flex-col overflow-hidden">

        {/* ── Header ── */}
        <div className="px-8 py-5 border-b border-gray-100 bg-white shrink-0">
          {/* Breadcrumb */}
          <div className="flex items-center gap-1 text-sm text-gray-500 mb-4">
            <button
              onClick={() => { setCurrentFolderId(null); setSelectedIds(new Set()) }}
              className={`hover:text-gray-800 transition-colors ${!currentFolderId ? 'text-gray-800 font-medium' : ''}`}
            >
              Документы
            </button>
            {breadcrumb.map((f) => (
              <span key={f.id} className="flex items-center gap-1">
                <ChevronRight className="w-3.5 h-3.5 text-gray-300" />
                <button
                  onClick={() => { setCurrentFolderId(f.id); setSelectedIds(new Set()) }}
                  className={`hover:text-gray-800 transition-colors ${currentFolderId === f.id ? 'text-gray-800 font-medium' : ''}`}
                >
                  {f.name}
                </button>
              </span>
            ))}
          </div>

          {/* Title + actions */}
          <div className="flex items-center justify-between gap-4">
            <h1 className="text-xl font-semibold text-gray-900 shrink-0">
              {currentFolderId ? breadcrumb[breadcrumb.length - 1]?.name : 'Документы'}
              <span className="ml-2 text-sm text-gray-400 font-normal">
                {currentFolders.length + currentFiles.length} файл(ов)
              </span>
            </h1>
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                <input
                  type="text"
                  placeholder="Поиск..."
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  className="pl-9 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-gray-400 w-44 bg-gray-50"
                />
              </div>
              <button
                onClick={() => setShowCreateFolder(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors text-gray-700"
              >
                <FolderPlus className="w-4 h-4" />
                Создать папку
              </button>
              <button
                onClick={() => setShowUpload(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-800 transition-colors"
              >
                <Upload className="w-4 h-4" />
                Загрузить файлы
              </button>
            </div>
          </div>
        </div>

        {/* ── Table ── */}
        <div className="flex-1 overflow-auto">
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="w-10 px-4 py-3">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleSelectAll}
                    className="rounded border-gray-300 cursor-pointer"
                  />
                </th>
                <th className="text-left px-3 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Название</th>
                <th className="text-left px-3 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider w-52">Тип документа</th>
                <th className="text-left px-3 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider w-28">Дата</th>
                <th className="text-left px-3 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider w-20">Формат</th>
                <th className="w-12 px-3 py-3"></th>
              </tr>
            </thead>
            <tbody>

              {/* ── Folder rows ── */}
              {currentFolders.map(folder => {
                const rowId = `folder-${folder.id}`
                const isSelected = selectedIds.has(rowId)
                const menuOpen = activeMenu === rowId
                return (
                  <tr
                    key={folder.id}
                    className={`border-b border-gray-50 transition-colors ${isSelected ? 'bg-blue-50/60' : 'hover:bg-gray-50'}`}
                  >
                    <td className="w-10 px-4 py-3" onClick={e => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSelect(rowId)}
                        className="rounded border-gray-300 cursor-pointer"
                      />
                    </td>
                    <td
                      className="px-3 py-3 cursor-pointer"
                      onClick={() => { setCurrentFolderId(folder.id); setSelectedIds(new Set()) }}
                    >
                      <div className="flex items-center gap-2.5">
                        <Folder className="w-4 h-4 text-amber-400 shrink-0" />
                        <span className="text-sm font-medium text-gray-900">{folder.name}</span>
                        {folder.file_count > 0 && (
                          <span className="text-xs text-gray-400 font-normal">({folder.file_count})</span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-3"><span className="text-sm text-gray-300">—</span></td>
                    <td className="px-3 py-3"><span className="text-sm text-gray-300">—</span></td>
                    <td className="px-3 py-3">
                      <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">Папка</span>
                    </td>
                    <td className="px-3 py-3 relative" onClick={e => e.stopPropagation()}>
                      <button
                        onClick={() => setActiveMenu(menuOpen ? null : rowId)}
                        className="p-1.5 rounded-lg hover:bg-gray-200 transition-colors"
                      >
                        <MoreHorizontal className="w-4 h-4 text-gray-400" />
                      </button>
                      {menuOpen && (
                        <div
                          ref={menuRef}
                          className="absolute right-10 top-0 z-50 bg-white border border-gray-100 rounded-xl shadow-lg py-1 w-44"
                        >
                          <button
                            onClick={() => { setRenameTarget(folder); setRenameName(folder.name); setActiveMenu(null) }}
                            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 text-left"
                          >
                            <Pencil className="w-3.5 h-3.5 shrink-0" />
                            Переименовать
                          </button>
                          <button
                            onClick={() => handleDeleteFolder(folder.id)}
                            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 hover:bg-red-50 text-left"
                          >
                            <Trash2 className="w-3.5 h-3.5 shrink-0" />
                            Удалить
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}

              {/* ── File rows ── */}
              {currentFiles.map(file => {
                const isSelected = selectedIds.has(file.id)
                const menuOpen = activeMenu === file.id
                return (
                  <tr
                    key={file.id}
                    className={`border-b border-gray-50 transition-colors ${isSelected ? 'bg-blue-50/60' : 'hover:bg-gray-50'}`}
                  >
                    <td className="w-10 px-4 py-3" onClick={e => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSelect(file.id)}
                        className="rounded border-gray-300 cursor-pointer"
                      />
                    </td>
                    <td
                      className="px-3 py-3 cursor-pointer"
                      onClick={() => setViewerDoc(toViewerDoc(file))}
                    >
                      <div className="flex items-center gap-2.5">
                        <FileText className="w-4 h-4 text-gray-400 shrink-0" />
                        <span className="text-sm text-gray-900 hover:text-blue-600 transition-colors">{file.filename}</span>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      {file.doc_type ? (
                        <span className="inline-flex items-center gap-1.5 text-xs text-gray-600">
                          <span className="w-1.5 h-1.5 rounded-full bg-gray-400 shrink-0" />
                          {file.doc_type}
                        </span>
                      ) : (
                        <span className="text-sm text-gray-300">—</span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <span className="text-sm text-gray-500">{formatDate(file.created_at)}</span>
                    </td>
                    <td className="px-3 py-3">
                      <span className="text-xs font-medium text-gray-400 uppercase">
                        {file.file_type || '—'}
                      </span>
                    </td>
                    <td className="px-3 py-3 relative" onClick={e => e.stopPropagation()}>
                      <button
                        onClick={() => setActiveMenu(menuOpen ? null : file.id)}
                        className="p-1.5 rounded-lg hover:bg-gray-200 transition-colors"
                      >
                        <MoreHorizontal className="w-4 h-4 text-gray-400" />
                      </button>
                      {menuOpen && (
                        <div
                          ref={menuRef}
                          className="absolute right-10 top-0 z-50 bg-white border border-gray-100 rounded-xl shadow-lg py-1 w-48"
                        >
                          <button
                            onClick={() => { setViewerDoc(toViewerDoc(file)); setActiveMenu(null) }}
                            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 text-left"
                          >
                            <FileText className="w-3.5 h-3.5 shrink-0" />
                            Просмотр
                          </button>
                          <button
                            onClick={() => handleOpenInEditor(file)}
                            disabled={openInEditorLoading === file.id}
                            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 text-left disabled:opacity-50"
                          >
                            {openInEditorLoading === file.id
                              ? <Loader2 className="w-3.5 h-3.5 shrink-0 animate-spin" />
                              : <FileEdit className="w-3.5 h-3.5 shrink-0" />
                            }
                            Открыть в редакторе
                          </button>
                          <button
                            onClick={() => openMoveModal([file.id])}
                            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 text-left"
                          >
                            <ArrowRight className="w-3.5 h-3.5 shrink-0" />
                            Переместить
                          </button>
                          <div className="border-t border-gray-100 my-1" />
                          <button
                            onClick={() => handleDeleteFile(file.id)}
                            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 hover:bg-red-50 text-left"
                          >
                            <Trash2 className="w-3.5 h-3.5 shrink-0" />
                            Удалить
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}

              {/* ── Empty state ── */}
              {currentFolders.length === 0 && currentFiles.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-20 text-center">
                    <Folder className="w-10 h-10 text-gray-200 mx-auto mb-3" />
                    <p className="text-sm text-gray-400">
                      {searchQuery
                        ? 'Ничего не найдено'
                        : 'Нет файлов. Загрузите файлы или создайте папку.'}
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* ── Selection action bar ── */}
        {selectedIds.size > 0 && (
          <div className="shrink-0 border-t border-gray-200 bg-white px-8 py-3 flex items-center gap-3">
            <span className="text-sm text-gray-500 font-medium">
              Выбрано: {selectedIds.size}
            </span>
            <button
              onClick={() => {
                const fileIds = [...selectedIds].filter(id => !id.startsWith('folder-'))
                if (fileIds.length > 0) openMoveModal(fileIds)
                else toast('Выберите файлы (не папки) для перемещения')
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors text-gray-700"
            >
              <ArrowRight className="w-3.5 h-3.5" />
              Переместить
            </button>
            <button
              onClick={handleDeleteSelected}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-red-200 text-red-600 rounded-lg hover:bg-red-50 transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Удалить
            </button>
            <button
              onClick={() => setSelectedIds(new Set())}
              className="ml-auto p-1.5 text-gray-400 hover:text-gray-600 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>

      {/* ══════════════════════════ MODALS ══════════════════════════ */}

      {/* Create folder */}
      {showCreateFolder && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl w-96 p-6">
            <h2 className="text-base font-semibold text-gray-900 mb-1">Новая папка</h2>
            <p className="text-sm text-gray-400 mb-4">
              {currentFolderId
                ? `Внутри «${breadcrumb[breadcrumb.length - 1]?.name}»`
                : 'Создать в корне'}
            </p>
            <input
              autoFocus
              type="text"
              placeholder="Название папки"
              value={newFolderName}
              onChange={e => setNewFolderName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleCreateFolder() }}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-gray-400 mb-4"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => { setShowCreateFolder(false); setNewFolderName('') }}
                className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 rounded-lg transition-colors"
              >
                Отмена
              </button>
              <button
                onClick={handleCreateFolder}
                disabled={!newFolderName.trim() || creatingFolder}
                className="px-4 py-2 text-sm bg-gray-900 text-white rounded-lg disabled:opacity-50 hover:bg-gray-800 transition-colors"
              >
                {creatingFolder ? 'Создание...' : 'Создать'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Rename folder */}
      {renameTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl w-96 p-6">
            <h2 className="text-base font-semibold text-gray-900 mb-4">Переименовать папку</h2>
            <input
              autoFocus
              type="text"
              value={renameName}
              onChange={e => setRenameName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleRenameFolder() }}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-gray-400 mb-4"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setRenameTarget(null)}
                className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 rounded-lg transition-colors"
              >
                Отмена
              </button>
              <button
                onClick={handleRenameFolder}
                disabled={!renameName.trim()}
                className="px-4 py-2 text-sm bg-gray-900 text-white rounded-lg disabled:opacity-50 hover:bg-gray-800 transition-colors"
              >
                Сохранить
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Move files modal */}
      {showMoveModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl w-96 p-6">
            <h2 className="text-base font-semibold text-gray-900 mb-1">Переместить в папку</h2>
            <p className="text-sm text-gray-400 mb-4">{moveFileIds.length} файл(ов)</p>
            <div className="border border-gray-100 rounded-xl overflow-y-auto max-h-64 mb-4">
              <button
                onClick={() => setMoveDestFolderId(null)}
                className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-sm transition-colors ${moveDestFolderId === null ? 'bg-blue-50 text-blue-700' : 'text-gray-700 hover:bg-gray-50'}`}
              >
                <Folder className="w-4 h-4 shrink-0" />
                <span className="flex-1 text-left">Корень (без папки)</span>
                {moveDestFolderId === null && <Check className="w-3.5 h-3.5 shrink-0" />}
              </button>
              {allFolders.map(f => (
                <button
                  key={f.id}
                  onClick={() => setMoveDestFolderId(f.id)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-sm border-t border-gray-50 transition-colors ${moveDestFolderId === f.id ? 'bg-blue-50 text-blue-700' : 'text-gray-700 hover:bg-gray-50'}`}
                >
                  <Folder className="w-4 h-4 shrink-0 text-amber-400" />
                  <span className="flex-1 text-left truncate">{f.name}</span>
                  {moveDestFolderId === f.id && <Check className="w-3.5 h-3.5 shrink-0" />}
                </button>
              ))}
              {allFolders.length === 0 && (
                <p className="px-3 py-4 text-sm text-gray-400 text-center">
                  Папок нет. Сначала создайте папку.
                </p>
              )}
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowMoveModal(false)}
                className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 rounded-lg transition-colors"
              >
                Отмена
              </button>
              <button
                onClick={handleMoveFiles}
                disabled={moveDestFolderId === undefined}
                className="px-4 py-2 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-800 transition-colors disabled:opacity-40"
              >
                Переместить
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Upload modal */}
      {showUpload && caseId && (
        <DocumentUploadModal
          isOpen={showUpload}
          caseId={caseId}
          onClose={() => setShowUpload(false)}
          onUploadComplete={() => { loadAll(); setShowUpload(false) }}
        />
      )}

      {/* Document viewer drawer */}
      <Drawer anchor="right" open={!!viewerDoc} onClose={() => setViewerDoc(null)}>
        <div style={{ width: 600, height: '100%', display: 'flex', flexDirection: 'column' }}>
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 shrink-0">
            <span className="font-medium text-sm text-gray-900 truncate max-w-xs">
              {viewerDoc?.filename}
            </span>
            <button
              onClick={() => setViewerDoc(null)}
              className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors ml-3 shrink-0"
            >
              <X className="w-4 h-4 text-gray-500" />
            </button>
          </div>
          <div className="flex-1 overflow-auto">
            {viewerDoc && caseId && (
              <DocumentViewer document={viewerDoc} caseId={caseId} />
            )}
          </div>
        </div>
      </Drawer>
    </div>
  )
}

export default DocumentsPage
