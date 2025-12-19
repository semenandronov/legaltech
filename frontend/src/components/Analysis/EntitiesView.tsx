import React, { useState } from 'react'
import { ExtractedEntity } from '../../services/api'
import ConfidenceBadge from '../Common/ConfidenceBadge'
import './Analysis.css'

interface EntitiesViewProps {
  entities: ExtractedEntity[]
  onEntityClick?: (entity: ExtractedEntity) => void
}

const EntitiesView: React.FC<EntitiesViewProps> = ({
  entities,
  onEntityClick
}) => {
  const [filterType, setFilterType] = useState<string>('all')
  const [sortBy, setSortBy] = useState<'confidence' | 'type' | 'text'>('confidence')

  // Группируем по типу
  const entitiesByType: Record<string, ExtractedEntity[]> = {}
  entities.forEach(entity => {
    if (!entitiesByType[entity.type]) {
      entitiesByType[entity.type] = []
    }
    entitiesByType[entity.type].push(entity)
  })

  // Фильтруем
  const filteredEntities = filterType === 'all'
    ? entities
    : entities.filter(e => e.type === filterType)

  // Сортируем
  const sortedEntities = [...filteredEntities].sort((a, b) => {
    if (sortBy === 'confidence') {
      return b.confidence - a.confidence
    }
    if (sortBy === 'type') {
      return a.type.localeCompare(b.type)
    }
    return a.text.localeCompare(b.text)
  })

  const entityTypes = ['all', ...Object.keys(entitiesByType)]

  const getEntityIcon = (type: string): string => {
    switch (type) {
      case 'PERSON':
        return '👤'
      case 'ORG':
        return '🏢'
      case 'DATE':
        return '📅'
      case 'AMOUNT':
        return '💰'
      case 'CONTRACT_TERM':
        return '📝'
      default:
        return '📄'
    }
  }

  return (
    <div className="entities-view">
      <div className="entities-view-header">
        <h3>Extracted Entities</h3>
        <div className="entities-view-controls">
          <select
            className="entities-view-filter"
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            aria-label="Фильтр по типу сущности"
          >
            {entityTypes.map(type => (
              <option key={type} value={type}>
                {type === 'all' ? 'All Types' : `${getEntityIcon(type)} ${type}`}
              </option>
            ))}
          </select>
          <select
            className="entities-view-sort"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as 'confidence' | 'type' | 'text')}
            aria-label="Сортировка сущностей"
          >
            <option value="confidence">By Confidence</option>
            <option value="type">By Type</option>
            <option value="text">By Text</option>
          </select>
        </div>
      </div>

      <div className="entities-view-stats">
        <div className="entities-view-stat">
          <span className="entities-view-stat-label">Total:</span>
          <span className="entities-view-stat-value">{entities.length}</span>
        </div>
        {Object.entries(entitiesByType).map(([type, typeEntities]) => (
          <div key={type} className="entities-view-stat">
            <span className="entities-view-stat-label">
              {getEntityIcon(type)} {type}:
            </span>
            <span className="entities-view-stat-value">{typeEntities.length}</span>
          </div>
        ))}
      </div>

      <div className="entities-view-table">
        <table>
          <thead>
            <tr>
              <th>Type</th>
              <th>Text</th>
              <th>Confidence</th>
              <th>Context</th>
            </tr>
          </thead>
          <tbody>
            {sortedEntities.map((entity) => (
              <tr
                key={entity.id}
                className="entities-view-row"
                onClick={() => onEntityClick?.(entity)}
                style={{ cursor: onEntityClick ? 'pointer' : 'default' }}
              >
                <td>
                  <span className="entities-view-type">
                    {getEntityIcon(entity.type)} {entity.type}
                  </span>
                </td>
                <td className="entities-view-text">{entity.text}</td>
                <td>
                  <ConfidenceBadge confidence={entity.confidence * 100} size="small" />
                </td>
                <td className="entities-view-context" title={entity.context}>
                  {entity.context?.substring(0, 50)}
                  {entity.context && entity.context.length > 50 ? '...' : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {sortedEntities.length === 0 && (
        <div className="entities-view-empty">
          Нет сущностей, соответствующих фильтру
        </div>
      )}
    </div>
  )
}

export default EntitiesView
