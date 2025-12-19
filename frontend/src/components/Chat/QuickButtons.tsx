import React from 'react'
import './Chat.css'

interface QuickButtonsProps {
  onClassifyAll?: () => void
  onFindPrivilege?: () => void
  onTimeline?: () => void
  onStatistics?: () => void
  onExtractEntities?: () => void
}

const QuickButtons: React.FC<QuickButtonsProps> = ({
  onClassifyAll,
  onFindPrivilege,
  onTimeline,
  onStatistics,
  onExtractEntities
}) => {
  return (
    <div className="chat-quick-buttons">
      <div className="chat-quick-buttons-title">📌 Quick Start:</div>
      <div className="chat-quick-buttons-grid">
        {onClassifyAll && (
          <button
            className="chat-quick-button"
            onClick={onClassifyAll}
            aria-label="Классифицировать все документы"
          >
            [Classify All]
          </button>
        )}
        {onFindPrivilege && (
          <button
            className="chat-quick-button"
            onClick={onFindPrivilege}
            aria-label="Найти привилегированные документы"
          >
            [Find Privilege]
          </button>
        )}
        {onTimeline && (
          <button
            className="chat-quick-button"
            onClick={onTimeline}
            aria-label="Показать таймлайн"
          >
            [Timeline]
          </button>
        )}
        {onStatistics && (
          <button
            className="chat-quick-button"
            onClick={onStatistics}
            aria-label="Показать статистику"
          >
            [Statistics]
          </button>
        )}
        {onExtractEntities && (
          <button
            className="chat-quick-button"
            onClick={onExtractEntities}
            aria-label="Извлечь сущности"
          >
            [Extract Entities]
          </button>
        )}
      </div>
    </div>
  )
}

export default QuickButtons
