import React, { useState, useEffect } from "react"
import Modal from "@/components/UI/Modal"
import { Button } from "@/components/UI/Button"
import Input from "@/components/UI/Input"
import { Badge } from "@/components/UI/Badge"
import Checkbox from "@/components/UI/Checkbox"
import { Search, FileText } from "lucide-react"
import { tabularReviewApi } from "@/services/tabularReviewApi"
import Spinner from "@/components/UI/Spinner"

interface Document {
  id: string
  filename: string
  file_type?: string
  created_at?: string
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
  caseId: _caseId,
}) => {
  const [documents, setDocuments] = useState<Document[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set(initialSelectedIds))
  const [searchQuery, setSearchQuery] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (isOpen && reviewId) {
      loadDocuments()
      setSelectedIds(new Set(initialSelectedIds))
    }
  }, [isOpen, reviewId, initialSelectedIds])

  const loadDocuments = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await tabularReviewApi.getAvailableFiles(reviewId)
      setDocuments(response.files || [])
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

  const handleSelectAll = () => {
    if (selectedIds.size === filteredDocuments.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(filteredDocuments.map((d) => d.id)))
    }
  }

  const handleConfirm = () => {
    onConfirm(Array.from(selectedIds))
    onClose()
  }

  const filteredDocuments = documents.filter((doc) =>
    doc.filename.toLowerCase().includes(searchQuery.toLowerCase())
  )

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

        {/* Info */}
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">
            Найдено: {filteredDocuments.length} документов
          </span>
          <div className="flex items-center gap-2">
            <Badge variant="secondary">
              Выбрано: {selectedIds.size}
            </Badge>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleSelectAll}
            >
              {selectedIds.size === filteredDocuments.length ? "Снять все" : "Выбрать все"}
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
            {filteredDocuments.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground">
                {searchQuery ? "Документы не найдены" : "Нет доступных документов"}
              </div>
            ) : (
              <div className="divide-y">
                {filteredDocuments.map((doc) => (
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

