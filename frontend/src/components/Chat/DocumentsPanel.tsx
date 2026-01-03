import React, { useState, useEffect } from 'react'
import { X, FileText, Search, GripVertical } from 'lucide-react'
import { getDocuments, type DocumentItem } from '@/services/api'
import { ScrollArea } from '../UI/scroll-area'
import Input from '../UI/Input'

interface DocumentsPanelProps {
  isOpen: boolean
  onClose: () => void
  caseId: string
  onDocumentClick?: (document: DocumentItem) => void
}

export const DocumentsPanel: React.FC<DocumentsPanelProps> = ({
  isOpen,
  onClose,
  caseId,
  onDocumentClick,
}) => {
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [filteredDocuments, setFilteredDocuments] = useState<DocumentItem[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [draggedDocument, setDraggedDocument] = useState<DocumentItem | null>(null)

  useEffect(() => {
    if (isOpen && caseId) {
      loadDocuments()
    }
  }, [isOpen, caseId])

  useEffect(() => {
    if (searchQuery.trim()) {
      const filtered = documents.filter((doc) =>
        doc.filename.toLowerCase().includes(searchQuery.toLowerCase())
      )
      setFilteredDocuments(filtered)
    } else {
      setFilteredDocuments(documents)
    }
  }, [searchQuery, documents])

  const loadDocuments = async () => {
    if (!caseId) return
    setIsLoading(true)
    try {
      const data = await getDocuments(caseId)
      setDocuments(data.documents || [])
      setFilteredDocuments(data.documents || [])
    } catch (error) {
      console.error('Error loading documents:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleDocumentClick = (document: DocumentItem) => {
    onDocumentClick?.(document)
  }

  const handleDragStart = (e: React.DragEvent, document: DocumentItem) => {
    setDraggedDocument(document)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', document.filename)
  }

  const handleDragEnd = () => {
    setDraggedDocument(null)
  }

  if (!isOpen) return null

  return (
    <div className="absolute inset-y-0 right-0 w-80 bg-white border-l border-gray-200 shadow-xl z-30 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
        <h2 className="text-lg font-semibold text-gray-900">Документы</h2>
        <button
          onClick={onClose}
          className="p-1.5 hover:bg-gray-100 rounded-lg transition-colors"
          title="Закрыть"
        >
          <X className="w-5 h-5 text-gray-500" />
        </button>
      </div>

      {/* Search */}
      <div className="px-4 py-3 border-b border-gray-200">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
          <Input
            type="text"
            placeholder="Поиск документов..."
            value={searchQuery}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {/* Documents List */}
      <ScrollArea className="flex-1">
        <div className="p-2">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="text-sm text-gray-500">Загрузка...</div>
            </div>
          ) : filteredDocuments.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <FileText className="w-12 h-12 text-gray-300 mb-2" />
              <p className="text-sm text-gray-500">
                {searchQuery ? 'Документы не найдены' : 'Нет документов'}
              </p>
            </div>
          ) : (
            <div className="space-y-1">
              {filteredDocuments.map((document) => (
                <div
                  key={document.id}
                  draggable
                  onDragStart={(e) => handleDragStart(e, document)}
                  onDragEnd={handleDragEnd}
                  onClick={() => handleDocumentClick(document)}
                  className={`
                    flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-colors
                    ${draggedDocument?.id === document.id 
                      ? 'bg-blue-50 border-2 border-blue-300' 
                      : 'hover:bg-gray-50 border border-transparent'
                    }
                  `}
                >
                  <div className="flex-shrink-0">
                    <FileText className="w-5 h-5 text-gray-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {document.filename}
                    </p>
                    <p className="text-xs text-gray-500">
                      {document.file_type}
                    </p>
                  </div>
                  <div className="flex-shrink-0">
                    <GripVertical className="w-4 h-4 text-gray-400" />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </ScrollArea>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-gray-200 bg-gray-50">
        <p className="text-xs text-gray-500 text-center">
          Перетащите документ в чат для добавления
        </p>
      </div>
    </div>
  )
}

