import React, { useState, useEffect } from 'react'
import { DocumentItem, DocumentClassification, PrivilegeCheck } from '../../services/api'
import StatusIcon, { DocumentStatus } from '../Common/StatusIcon'
import ConfidenceBadge from '../Common/ConfidenceBadge'
import BatchActions from './BatchActions'
import useKeyboardShortcuts from '../../hooks/useKeyboardShortcuts'
import './Documents.css'

export interface DocumentWithMetadata extends DocumentItem {
  classification?: DocumentClassification
  privilegeCheck?: PrivilegeCheck
  confidence?: number
  status?: 'reviewed' | 'privileged' | 'rejected' | 'processing' | 'flagged' | 'bookmarked'
}

interface DocumentsListProps {
  documents: DocumentWithMetadata[]
  selectedDocuments: Set<string>
  onSelectDocument: (fileId: string, selected: boolean) => void
  onSelectAll: () => void
  onSelectVisible: () => void
  onDocumentClick: (fileId: string) => void
  onBatchAction?: (action: string, fileIds: string[]) => void
  sortBy?: 'date' | 'name' | 'relevance'
  onSortChange?: (sortBy: 'date' | 'name' | 'relevance') => void
  loadMore?: () => void
  hasMore?: boolean
}

const DocumentsList: React.FC<DocumentsListProps> = ({
  documents,
  selectedDocuments,
  onSelectDocument,
  onSelectAll,
  onSelectVisible,
  onDocumentClick,
  onBatchAction,
  sortBy = 'date',
  onSortChange,
  loadMore,
  hasMore = false
}) => {
  const [visibleRange, setVisibleRange] = useState(50)

  const getDocumentStatus = (doc: DocumentWithMetadata): DocumentStatus | undefined => {
    if (doc.privilegeCheck?.is_privileged || doc.classification?.is_privileged) {
      return 'privileged'
    }
    return doc.status as DocumentStatus | undefined
  }

  const getConfidenceClass = (confidence?: number) => {
    if (!confidence) return ''
    if (confidence > 90) return 'high'
    if (confidence > 60) return 'medium'
    return 'low'
  }

  const getConfidenceDisplay = (confidence?: number) => {
    if (!confidence) return '--'
    return `${Math.round(confidence)}%`
  }

  const visibleDocuments = documents.slice(0, visibleRange)
  const selectedCount = selectedDocuments.size

  useEffect(() => {
    if (hasMore && visibleRange >= documents.length && loadMore) {
      loadMore()
    }
  }, [visibleRange, documents.length, hasMore, loadMore])

  // Keyboard shortcuts для batch actions
  useKeyboardShortcuts({
    onSelectAll: () => {
      if (selectedDocuments.size === documents.length) {
        setSelectedDocuments(new Set())
      } else {
        setSelectedDocuments(new Set(documents.map(d => d.id)))
      }
    },
    enabled: documents.length > 0
  })

  return (
    <div className="documents-list">
      <div className="documents-list-header">
        <div className="documents-list-header-info">
          {documents.length} matching filters
        </div>
        <div className="documents-list-sort">
          <span className="documents-list-sort-label">🎯 SORT:</span>
          <select
            className="documents-list-sort-select"
            value={sortBy}
            onChange={(e) => onSortChange?.(e.target.value as 'date' | 'name' | 'relevance')}
            aria-label="Сортировка документов"
          >
            <option value="date">Date</option>
            <option value="name">A-Z</option>
            <option value="relevance">Rel%</option>
          </select>
        </div>
      </div>

      <div className="documents-list-items">
        {visibleDocuments.map((doc) => {
          const isSelected = selectedDocuments.has(doc.id)
          const confidence = doc.confidence || doc.classification?.confidence || 0
          const relevanceScore = doc.classification?.relevance_score || 0
          const isPrivileged = doc.privilegeCheck?.is_privileged || doc.classification?.is_privileged || false

          return (
            <div
              key={doc.id}
              className={`document-item ${isSelected ? 'selected' : ''}`}
              onClick={() => onDocumentClick(doc.id)}
            >
              <input
                type="checkbox"
                className="document-item-checkbox"
                checked={isSelected}
                onChange={(e) => {
                  e.stopPropagation()
                  onSelectDocument(doc.id, !isSelected)
                }}
                onClick={(e) => e.stopPropagation()}
                aria-label={`Выбрать документ ${doc.filename}`}
              />
              
              <div className="document-item-content">
                <div className="document-item-header">
                  <StatusIcon status={getDocumentStatus(doc) || 'confirmed'} size="small" />
                  <span className="document-item-name">{doc.filename}</span>
                  {relevanceScore > 0 && (
                    <span className={`document-item-confidence ${getConfidenceClass(confidence)}`}>
                      {relevanceScore}% <ConfidenceBadge confidence={confidence} showIcon={false} size="small" />
                    </span>
                  )}
                </div>
                
                <div className="document-item-meta">
                  {doc.classification?.doc_type && (
                    <span>{doc.classification.doc_type}</span>
                  )}
                  {doc.created_at && (
                    <span>{new Date(doc.created_at).toLocaleDateString('ru-RU')}</span>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      <BatchActions
        selectedCount={selectedCount}
        onConfirmAll={() => onBatchAction?.('confirm', Array.from(selectedDocuments))}
        onRejectAll={() => onBatchAction?.('reject', Array.from(selectedDocuments))}
        onWithholdAll={() => onBatchAction?.('withhold', Array.from(selectedDocuments))}
        onAutoReview={() => onBatchAction?.('auto-review', Array.from(selectedDocuments))}
        onExportSelected={() => onBatchAction?.('export', Array.from(selectedDocuments))}
      />

      {documents.length > visibleRange && (
        <div className="documents-list-load-more">
          <button
            className="documents-list-load-more-btn"
            onClick={() => setVisibleRange(prev => prev + 50)}
          >
            ─── LOAD MORE (50) ───
          </button>
        </div>
      )}

      {documents.length === 0 && (
        <div className="documents-list-empty">
          <p>Нет документов, соответствующих фильтрам</p>
        </div>
      )}
    </div>
  )
}

export default DocumentsList
