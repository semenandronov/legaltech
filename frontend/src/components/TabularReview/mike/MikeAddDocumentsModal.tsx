"use client"

import { useEffect, useMemo, useState } from 'react'
import { FileText, Loader2, Search, X } from 'lucide-react'
import { getCaseFolders, type FolderItem } from '@/services/api'
import { tabularReviewApi } from '@/services/tabularReviewApi'
import {
  DOCUMENT_CATEGORIES,
  type DocumentCategoryKey,
  groupDocumentsByCategory,
  type CategorizableDocument,
} from '@/utils/documentCategories'
import { FolderGroupedFilePicker } from '@/components/Documents/FolderGroupedFilePicker'
import type { PickableCaseFile } from '@/utils/groupFilesByFolder'
import { MikeModalShell } from './MikeModalShell'

interface Document extends CategorizableDocument, PickableCaseFile {
  file_type?: string
  created_at?: string
  doc_type?: string | null
}

interface MikeAddDocumentsModalProps {
  open: boolean
  onClose: () => void
  onConfirm: (selectedFileIds: string[]) => void
  reviewId: string
  caseId: string
  initialSelectedIds?: string[]
}

function shouldUseFolderPicker(files: PickableCaseFile[], folders: FolderItem[]): boolean {
  if (folders.length > 0) return true
  return files.some((file) => Boolean(file.folder_id))
}

export function MikeAddDocumentsModal({
  open,
  onClose,
  onConfirm,
  reviewId,
  caseId,
  initialSelectedIds = [],
}: MikeAddDocumentsModalProps) {
  const [documents, setDocuments] = useState<Document[]>([])
  const [folders, setFolders] = useState<FolderItem[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set(initialSelectedIds))
  const [searchQuery, setSearchQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeCategory, setActiveCategory] = useState<DocumentCategoryKey>('written_evidence')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    setSearchQuery('')
    setSelectedIds(new Set(initialSelectedIds))
    void loadDocuments()
  }, [open, reviewId, caseId, initialSelectedIds])

  async function loadDocuments() {
    try {
      setLoading(true)
      setError(null)

      const folderPromise = caseId ? getCaseFolders(caseId).catch(() => []) : Promise.resolve([])

      if (reviewId) {
        const [response, folderList] = await Promise.all([
          tabularReviewApi.getAvailableFiles(reviewId),
          folderPromise,
        ])
        setFolders(folderList)
        setDocuments(
          (response.files || []).map((doc) => ({
            id: doc.id,
            filename: doc.filename,
            file_type: doc.file_type,
            created_at: doc.created_at,
            folder_id: doc.folder_id ?? null,
            dd_doc_type: doc.dd_doc_type ?? null,
            dd_doc_type_short_label: doc.dd_doc_type_short_label ?? null,
            doc_type: null,
          })),
        )
        return
      }

      if (caseId) {
        const { getDocuments } = await import('@/services/api')
        const [data, folderList] = await Promise.all([getDocuments(caseId), folderPromise])
        setFolders(folderList)
        setDocuments(
          data.documents.map((doc) => ({
            id: doc.id,
            filename: doc.filename,
            file_type: doc.file_type,
            created_at: doc.created_at,
            folder_id: doc.folder_id ?? null,
            dd_doc_type: doc.dd_doc_type ?? null,
            dd_doc_type_short_label: doc.dd_doc_type_short_label ?? null,
            doc_type: doc.doc_type ?? null,
          })),
        )
        return
      }

      setError('Не указан caseId или reviewId')
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Ошибка при загрузке документов'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  function handleToggle(fileId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(fileId)) next.delete(fileId)
      else next.add(fileId)
      return next
    })
  }

  function handleSelectAllInCategory(docsInCategory: Document[]) {
    const idsInCategory = docsInCategory.map((doc) => doc.id)
    const allSelected = idsInCategory.every((id) => selectedIds.has(id))
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (allSelected) idsInCategory.forEach((id) => next.delete(id))
      else idsInCategory.forEach((id) => next.add(id))
      return next
    })
  }

  async function handleConfirm() {
    if (selectedIds.size === 0 || submitting) return
    setSubmitting(true)
    try {
      await Promise.resolve(onConfirm(Array.from(selectedIds)))
      onClose()
    } finally {
      setSubmitting(false)
    }
  }

  const useFolderPicker = useMemo(
    () => shouldUseFolderPicker(documents, folders),
    [documents, folders],
  )

  const searchLower = searchQuery.toLowerCase()
  const searchedDocuments = documents.filter((doc) =>
    doc.filename.toLowerCase().includes(searchLower),
  )
  const grouped = groupDocumentsByCategory(searchedDocuments)
  const docsInActiveCategory = grouped[activeCategory]
  const selectedInCategory = docsInActiveCategory.filter((doc) => selectedIds.has(doc.id)).length
  const visibleCategories = (Object.keys(DOCUMENT_CATEGORIES) as DocumentCategoryKey[]).filter(
    (key) => grouped[key].length > 0,
  )

  useEffect(() => {
    if (!open || useFolderPicker || visibleCategories.length === 0) return
    if (!visibleCategories.includes(activeCategory)) {
      setActiveCategory(visibleCategories[0]!)
    }
  }, [open, useFolderPicker, visibleCategories, activeCategory])

  return (
    <MikeModalShell
      open={open}
      onClose={onClose}
      breadcrumbs={['Табличный обзор', 'Добавить документы']}
      className="ws-mike-modal-panel--docs"
      bodyClassName="ws-mike-add-docs-body"
      footer={
        <div className="ws-mike-modal-footer-inner">
          <div className="ws-mike-modal-footer-left" />
          <div className="ws-mike-modal-footer-right">
            {selectedIds.size > 0 && (
              <span className="ws-mike-modal-footer-status">
                Выбрано: {selectedIds.size}
              </span>
            )}
            <button type="button" onClick={onClose} className="ws-mike-modal-btn-cancel">
              Отмена
            </button>
            <button
              type="button"
              onClick={() => void handleConfirm()}
              disabled={selectedIds.size === 0 || submitting}
              className="ws-mike-modal-btn-primary"
            >
              {submitting ? 'Сохранение…' : 'Подтвердить'}
            </button>
          </div>
        </div>
      }
    >
      <div className="ws-mike-add-docs-search-wrap">
        <div className="ws-mike-add-docs-search">
          <Search className="h-3.5 w-3.5 shrink-0 text-gray-400" aria-hidden />
          <input
            type="text"
            placeholder="Поиск…"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            className="ws-mike-add-docs-search-input"
            autoFocus
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              className="ws-mike-add-docs-search-clear"
              aria-label="Очистить поиск"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="ws-mike-add-docs-error" role="alert">
          {error}
        </div>
      )}

      {loading ? (
        <div className="ws-mike-add-docs-loading">
          <Loader2 className="h-6 w-6 animate-spin text-gray-400" aria-hidden />
        </div>
      ) : useFolderPicker ? (
        <FolderGroupedFilePicker
          files={documents}
          folders={folders}
          selectedIds={selectedIds}
          onSelectedIdsChange={setSelectedIds}
          searchQuery={searchQuery}
          listClassName="ws-mike-add-docs-list max-h-[min(420px,50vh)] border-0 rounded-none"
        />
      ) : (
        <>
          {visibleCategories.length > 0 && (
            <div className="ws-mike-add-docs-tabs">
              {visibleCategories.map((key) => {
                const cfg = DOCUMENT_CATEGORIES[key]
                const count = grouped[key].length
                const isActive = key === activeCategory
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setActiveCategory(key)}
                    className={`ws-mike-add-docs-tab ${isActive ? 'ws-mike-add-docs-tab--active' : ''}`}
                  >
                    {cfg.label} ({count})
                  </button>
                )
              })}
            </div>
          )}

          <div className="ws-mike-add-docs-toolbar">
            <span className="ws-mike-add-docs-count">
              Найдено: {searchedDocuments.length}
            </span>
            <button
              type="button"
              className="ws-mike-add-docs-select-all"
              onClick={() => handleSelectAllInCategory(docsInActiveCategory)}
              disabled={docsInActiveCategory.length === 0}
            >
              {selectedInCategory === docsInActiveCategory.length && docsInActiveCategory.length > 0
                ? 'Снять выбор в категории'
                : 'Выбрать все в категории'}
            </button>
          </div>

          <div className="ws-mike-add-docs-list">
            {docsInActiveCategory.length === 0 ? (
              <div className="ws-mike-add-docs-empty">
                {searchQuery ? 'Ничего не найдено' : 'Нет документов в этой категории'}
              </div>
            ) : (
              docsInActiveCategory.map((doc) => {
                const checked = selectedIds.has(doc.id)
                return (
                  <button
                    key={doc.id}
                    type="button"
                    className={`ws-mike-add-docs-row ${checked ? 'ws-mike-add-docs-row--selected' : ''}`}
                    onClick={() => handleToggle(doc.id)}
                  >
                    <span
                      className={`ws-mike-add-docs-checkbox ${checked ? 'ws-mike-add-docs-checkbox--checked' : ''}`}
                      aria-hidden
                    >
                      {checked && (
                        <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" fill="none">
                          <path
                            d="M2.5 6l2.5 2.5 4.5-5"
                            stroke="currentColor"
                            strokeWidth="1.5"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      )}
                    </span>
                    <FileText className="h-4 w-4 shrink-0 text-gray-400" aria-hidden />
                    <span className="ws-mike-add-docs-row-text">
                      <span className="ws-mike-add-docs-row-name">{doc.filename}</span>
                      {doc.file_type && (
                        <span className="ws-mike-add-docs-row-meta">{doc.file_type.toUpperCase()}</span>
                      )}
                    </span>
                  </button>
                )
              })
            )}
          </div>
        </>
      )}
    </MikeModalShell>
  )
}
