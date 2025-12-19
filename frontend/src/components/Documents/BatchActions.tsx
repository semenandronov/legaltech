import React from 'react'
import './Documents.css'

interface BatchActionsProps {
  selectedCount: number
  onConfirmAll?: () => void
  onRejectAll?: () => void
  onWithholdAll?: () => void
  onAutoReview?: () => void
  onExportSelected?: () => void
  onViewToggle?: () => void
}

const BatchActions: React.FC<BatchActionsProps> = ({
  selectedCount,
  onConfirmAll,
  onRejectAll,
  onWithholdAll,
  onAutoReview,
  onExportSelected,
  onViewToggle
}) => {
  if (selectedCount === 0) {
    return null
  }

  return (
    <div className="batch-actions-panel">
      <div className="batch-actions-info">
        {selectedCount} selected
      </div>
      <div className="batch-actions-buttons">
        {onConfirmAll && (
          <button
            className="batch-action-btn primary"
            onClick={onConfirmAll}
            aria-label="Подтвердить все выбранные"
          >
            ✅ Confirm All
          </button>
        )}
        {onRejectAll && (
          <button
            className="batch-action-btn"
            onClick={onRejectAll}
            aria-label="Отклонить все выбранные"
          >
            ❌ Reject All
          </button>
        )}
        {onWithholdAll && (
          <button
            className="batch-action-btn"
            onClick={onWithholdAll}
            aria-label="Заблокировать все выбранные"
          >
            🔒 Withhold All
          </button>
        )}
        {onAutoReview && (
          <button
            className="batch-action-btn"
            onClick={onAutoReview}
            aria-label="Автоматический review"
          >
            🚀 Auto-Review
          </button>
        )}
        {onExportSelected && (
          <button
            className="batch-action-btn"
            onClick={onExportSelected}
            aria-label="Экспортировать выбранные"
          >
            📤 Export Selected
          </button>
        )}
        {onViewToggle && (
          <button
            className="batch-action-btn"
            onClick={onViewToggle}
            aria-label="Переключить вид"
          >
            👁️ View as Grid/List
          </button>
        )}
      </div>
    </div>
  )
}

export default BatchActions
