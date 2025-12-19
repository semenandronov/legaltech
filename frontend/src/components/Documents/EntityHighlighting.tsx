import React from 'react'
import { ExtractedEntity } from '../../services/api'
import './Documents.css'

interface EntityHighlightingProps {
  text: string
  entities: ExtractedEntity[]
  onEntityClick?: (entity: ExtractedEntity) => void
}

const EntityHighlighting: React.FC<EntityHighlightingProps> = ({
  text,
  entities,
  onEntityClick
}) => {
  if (!entities || entities.length === 0) {
    return <div className="entity-highlighting-text">{text}</div>
  }

  // Сортируем сущности по позиции в тексте (если есть)
  // Для простоты показываем все сущности как tooltips
  const getEntityColor = (type: string): string => {
    switch (type) {
      case 'PERSON':
        return '#3b82f6' // Blue
      case 'ORG':
        return '#10b981' // Green
      case 'DATE':
        return '#f59e0b' // Orange
      case 'AMOUNT':
        return '#ef4444' // Red
      case 'CONTRACT_TERM':
        return '#8b5cf6' // Purple
      default:
        return '#6b7280' // Gray
    }
  }

  // Простая реализация: находим и подсвечиваем текст сущностей
  let highlightedText = text
  const entitySpans: Array<{ start: number; end: number; entity: ExtractedEntity }> = []

  entities.forEach((entity) => {
    const entityText = entity.text
    const index = highlightedText.toLowerCase().indexOf(entityText.toLowerCase())
    if (index !== -1) {
      entitySpans.push({
        start: index,
        end: index + entityText.length,
        entity
      })
    }
  })

  // Сортируем по позиции
  entitySpans.sort((a, b) => a.start - b.start)

  // Создаем элементы с подсветкой
  const parts: React.ReactNode[] = []
  let lastIndex = 0

  entitySpans.forEach((span) => {
    // Добавляем текст до сущности
    if (span.start > lastIndex) {
      parts.push(
        <span key={`text-${lastIndex}`}>
          {highlightedText.substring(lastIndex, span.start)}
        </span>
      )
    }

    // Добавляем подсвеченную сущность
    const color = getEntityColor(span.entity.type)
    parts.push(
      <span
        key={`entity-${span.entity.id}`}
        className="entity-highlight"
        style={{
          backgroundColor: `${color}20`,
          color: color,
          borderBottom: `2px solid ${color}`,
          cursor: onEntityClick ? 'pointer' : 'default',
          fontWeight: 500,
          padding: '2px 4px',
          borderRadius: '3px'
        }}
        title={`${span.entity.type}: ${span.entity.text} (${Math.round(span.entity.confidence * 100)}% confidence)\nContext: ${span.entity.context}`}
        onClick={() => onEntityClick?.(span.entity)}
      >
        {highlightedText.substring(span.start, span.end)}
      </span>
    )

    lastIndex = span.end
  })

  // Добавляем оставшийся текст
  if (lastIndex < highlightedText.length) {
    parts.push(
      <span key={`text-${lastIndex}`}>
        {highlightedText.substring(lastIndex)}
      </span>
    )
  }

  return (
    <div className="entity-highlighting-container">
      <div className="entity-highlighting-text">{parts}</div>
      {entities.length > 0 && (
        <div className="entity-highlighting-legend">
          <div className="entity-legend-title">Легенда:</div>
          <div className="entity-legend-items">
            <span className="entity-legend-item" style={{ color: '#3b82f6' }}>PERSON</span>
            <span className="entity-legend-item" style={{ color: '#10b981' }}>ORG</span>
            <span className="entity-legend-item" style={{ color: '#f59e0b' }}>DATE</span>
            <span className="entity-legend-item" style={{ color: '#ef4444' }}>AMOUNT</span>
            <span className="entity-legend-item" style={{ color: '#8b5cf6' }}>CONTRACT_TERM</span>
          </div>
        </div>
      )}
    </div>
  )
}

export default EntityHighlighting
