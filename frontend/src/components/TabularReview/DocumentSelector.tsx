import React, { useState, useEffect } from "react"
import Modal from "@/components/UI/Modal"
import { Button } from "@/components/UI/Button"
import Input from "@/components/UI/Input"
import { Badge } from "@/components/UI/Badge"
import Checkbox from "@/components/UI/Checkbox"
import { Search, FileText } from "lucide-react"
import { tabularReviewApi } from "@/services/tabularReviewApi"
import Spinner from "@/components/UI/Spinner"
import {
  DOCUMENT_CATEGORIES,
  type DocumentCategoryKey,
  groupDocumentsByCategory,
  type CategorizableDocument,
} from "@/utils/documentCategories"

interface Document extends CategorizableDocument {
  id: string
  filename: string
  file_type?: string
  created_at?: string
  doc_type?: string | null
}

interface DocumentSelectorProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: (selectedFileIds: string[]) => void
  reviewId: string
  initialSelectedIds?: string[]
  caseId: string
}

export const DocumentSelector: React.FC<DocumentSelectorProps> = ({
  isOpen,
  onClose,
  onConfirm,
  reviewId,
  initialSelectedIds = [],
  caseId,
}) => {
  const [documents, setDocuments] = useState<Document[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set(initialSelectedIds))
  const [searchQuery, setSearchQuery] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeCategory, setActiveCategory] = useState<DocumentCategoryKey>("written_evidence")

  useEffect(() => {
    if (isOpen) {
      loadDocuments()
      setSelectedIds(new Set(initialSelectedIds))
    }
  }, [isOpen, reviewId, initialSelectedIds, caseId])

  const loadDocuments = async () => {
    try {
      setLoading(true)
      setError(null)
      
      if (reviewId) {
        // If reviewId exists, use tabular review API
        const response = await tabularReviewApi.getAvailableFiles(reviewId)
        setDocuments(response.files || [])
      } else if (caseId) {
        // If no reviewId but caseId exists, get files from case API
        const { getDocuments } = await import('@/services/api')
        const data = await getDocuments(caseId)
        setDocuments(data.documents.map((doc: any) => ({
          id: doc.id,
          filename: doc.filename,
          file_type: doc.file_type,
          created_at: doc.created_at,
          doc_type: doc.doc_type ?? null
        })))
      } else {
        setError("Не указан caseId или reviewId")
      }
    } catch (err: any) {
      setError(err.message || "Ошибка при загрузке документов")
    } finally {
      setLoading(false)
    }
  }

  const handleToggle = (fileId: string) => {
    setSelectedIds((prev) => {
      const newSet = new Set(prev)
      if (newSet.has(fileId)) {
        newSet.delete(fileId)
      } else {
        newSet.add(fileId)
      }
      return newSet
    })
  }

  const handleSelectAll = (docsInCategory: Document[]) => {
    const idsInCategory = docsInCategory.map(d => d.id)
    const allSelected = idsInCategory.every(id => selectedIds.has(id))
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (allSelected) {
        idsInCategory.forEach(id => next.delete(id))
      } else {
        idsInCategory.forEach(id => next.add(id))
      }
      return next
    })
  }

  const handleConfirm = () => {
    onConfirm(Array.from(selectedIds))
    onClose()
  }

  const searchLower = searchQuery.toLowerCase()
  const searchedDocuments = documents.filter(doc =>
    doc.filename.toLowerCase().includes(searchLower),
  )
  const grouped = groupDocumentsByCategory(searchedDocuments)
  const docsInActiveCategory = grouped[activeCategory]
  const selectedInCategory = docsInActiveCategory.filter(d => selectedIds.has(d.id)).length

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Выбор документов" size="lg">
      <div className="space-y-4">
        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="Поиск по документам..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10"
          />
        </div>

        {/* Category Tabs */}
        <div className="border-b flex flex-wrap gap-2">
          {(Object.keys(DOCUMENT_CATEGORIES) as DocumentCategoryKey[]).map(key => {
            const cfg = DOCUMENT_CATEGORIES[key]
            const count = grouped[key].length
            if (count === 0) return null
            const isActive = key === activeCategory
            return (
              <button
                key={key}
                onClick={() => setActiveCategory(key)}
                className={`px-3 py-1 text-sm rounded-t-md border-b-2 transition-colors ${
                  isActive 
                    ? "border-accent text-text-primary font-medium" 
                    : "border-transparent text-text-secondary hover:text-text-primary"
                }`}
              >
                {cfg.label} ({count})
              </button>
            )
          })}
        </div>

        {/* Info */}
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">
            Найдено: {searchedDocuments.length} документов
          </span>
          <div className="flex items-center gap-2">
            <Badge variant="secondary">
              В категории выбрано: {selectedInCategory}
            </Badge>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => handleSelectAll(docsInActiveCategory)}
              disabled={docsInActiveCategory.length === 0}
            >
              {selectedInCategory === docsInActiveCategory.length
                ? "Снять все в категории"
                : "Выбрать все в категории"}
            </Button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="bg-destructive/10 text-destructive p-3 rounded-md text-sm">
            {error}
          </div>
        )}

        {/* Loading */}
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Spinner size="lg" />
          </div>
        ) : (
          /* Documents List */
          <div className="border rounded-md max-h-[400px] overflow-y-auto">
            {docsInActiveCategory.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground">
                {searchQuery ? "Документы не найдены" : "Нет документов в этой категории"}
              </div>
            ) : (
              <div className="divide-y">
                {docsInActiveCategory.map((doc) => (
                  <div
                    key={doc.id}
                    className="flex items-center gap-3 p-3 hover:bg-muted/50 cursor-pointer"
                    onClick={() => handleToggle(doc.id)}
                  >
                    <Checkbox
                      checked={selectedIds.has(doc.id)}
                      onChange={(e) => {
                        e.stopPropagation()
                        handleToggle(doc.id)
                      }}
                    />
                    <FileText className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="font-medium truncate">{doc.filename}</div>
                      {doc.file_type && (
                        <div className="text-xs text-muted-foreground">
                          {doc.file_type.toUpperCase()}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center justify-end gap-2 pt-4 border-t">
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={handleConfirm} disabled={selectedIds.size === 0}>
            Подтвердить ({selectedIds.size})
          </Button>
        </div>
      </div>
    </Modal>
  )
}

