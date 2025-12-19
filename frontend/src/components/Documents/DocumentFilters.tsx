import React, { useState } from 'react'
import './Documents.css'

export interface DocumentFiltersState {
  searchQuery: string
  docTypes: string[]
  privilegeStatus: string[]
  relevanceRange: [number, number]
  confidenceLevels: string[]
  statuses: string[]
}

interface DocumentFiltersProps {
  filters: DocumentFiltersState
  onFiltersChange: (filters: DocumentFiltersState) => void
  onClearFilters: () => void
  onSaveView?: (name: string) => void
}

const DocumentFilters: React.FC<DocumentFiltersProps> = ({
  filters,
  onFiltersChange,
  onClearFilters,
  onSaveView
}) => {
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [viewName, setViewName] = useState('')

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onFiltersChange({
      ...filters,
      searchQuery: e.target.value
    })
  }

  const handleDocTypeToggle = (type: string) => {
    const newTypes = filters.docTypes.includes(type)
      ? filters.docTypes.filter(t => t !== type)
      : [...filters.docTypes, type]
    onFiltersChange({
      ...filters,
      docTypes: newTypes
    })
  }

  const handlePrivilegeToggle = (status: string) => {
    const newStatuses = filters.privilegeStatus.includes(status)
      ? filters.privilegeStatus.filter(s => s !== status)
      : [...filters.privilegeStatus, status]
    onFiltersChange({
      ...filters,
      privilegeStatus: newStatuses
    })
  }

  const handleRelevanceChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = parseInt(e.target.value)
    onFiltersChange({
      ...filters,
      relevanceRange: [value, filters.relevanceRange[1]]
    })
  }

  const handleConfidenceToggle = (level: string) => {
    const newLevels = filters.confidenceLevels.includes(level)
      ? filters.confidenceLevels.filter(l => l !== level)
      : [...filters.confidenceLevels, level]
    onFiltersChange({
      ...filters,
      confidenceLevels: newLevels
    })
  }

  const handleStatusToggle = (status: string) => {
    const newStatuses = filters.statuses.includes(status)
      ? filters.statuses.filter(s => s !== status)
      : [...filters.statuses, status]
    onFiltersChange({
      ...filters,
      statuses: newStatuses
    })
  }

  const handleSaveView = () => {
    if (viewName.trim() && onSaveView) {
      onSaveView(viewName.trim())
      setViewName('')
      setShowSaveDialog(false)
    }
  }

  const docTypes = ['Contract', 'Letter', 'Report', 'Email', 'Other']
  const privilegeStatuses = ['All', 'Privileged', 'Not Privileged', 'Low Confidence']
  const confidenceLevels = ['>95%', '80-95%', '<80%']
  const statuses = ['New', 'Reviewed', 'Flagged']

  return (
    <div className="document-filters">
      <div className="document-filters-header">
        <h3 className="document-filters-title">🎛️ FILTERS</h3>
      </div>

      <div className="document-filters-search">
        <input
          type="text"
          className="document-filters-search-input"
          placeholder="🔍 Search documents..."
          value={filters.searchQuery}
          onChange={handleSearchChange}
          aria-label="Поиск документов"
        />
      </div>

      <div className="document-filters-group">
        <label className="document-filters-group-label">☑ Type:</label>
        <div className="document-filters-checkbox-group">
          {docTypes.map(type => (
            <label key={type} className="document-filters-checkbox">
              <input
                type="checkbox"
                checked={filters.docTypes.includes(type)}
                onChange={() => handleDocTypeToggle(type)}
              />
              <span>{type}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="document-filters-group">
        <label className="document-filters-group-label">☑ Privilege:</label>
        <div className="document-filters-checkbox-group">
          {privilegeStatuses.map(status => (
            <label key={status} className="document-filters-checkbox">
              <input
                type="checkbox"
                checked={filters.privilegeStatus.includes(status)}
                onChange={() => handlePrivilegeToggle(status)}
              />
              <span>{status}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="document-filters-group">
        <label className="document-filters-group-label">
          ☑ Relevance: {filters.relevanceRange[0]}% - {filters.relevanceRange[1]}%
        </label>
        <div className="document-filters-slider">
          <input
            type="range"
            min="0"
            max="100"
            value={filters.relevanceRange[0]}
            onChange={handleRelevanceChange}
            className="document-filters-slider-input"
            aria-label="Диапазон релевантности"
          />
        </div>
      </div>

      <div className="document-filters-group">
        <label className="document-filters-group-label">☑ Confidence:</label>
        <div className="document-filters-checkbox-group">
          {confidenceLevels.map(level => (
            <label key={level} className="document-filters-checkbox">
              <input
                type="checkbox"
                checked={filters.confidenceLevels.includes(level)}
                onChange={() => handleConfidenceToggle(level)}
              />
              <span>{level}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="document-filters-group">
        <label className="document-filters-group-label">☑ Status:</label>
        <div className="document-filters-checkbox-group">
          {statuses.map(status => (
            <label key={status} className="document-filters-checkbox">
              <input
                type="checkbox"
                checked={filters.statuses.includes(status)}
                onChange={() => handleStatusToggle(status)}
              />
              <span>{status}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="document-filters-actions">
        <button
          className="document-filters-clear-btn"
          onClick={onClearFilters}
          aria-label="Очистить все фильтры"
        >
          ✨ Clear All Filters
        </button>
        {onSaveView && (
          <button
            className="document-filters-save-btn"
            onClick={() => setShowSaveDialog(true)}
            aria-label="Сохранить фильтры как View"
          >
            💾 Save as View
          </button>
        )}
      </div>

      {showSaveDialog && (
        <div className="document-filters-save-dialog">
          <input
            type="text"
            placeholder="Название View..."
            value={viewName}
            onChange={(e) => setViewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                handleSaveView()
              } else if (e.key === 'Escape') {
                setShowSaveDialog(false)
              }
            }}
            autoFocus
          />
          <div>
            <button onClick={handleSaveView}>Сохранить</button>
            <button onClick={() => setShowSaveDialog(false)}>Отмена</button>
          </div>
        </div>
      )}
    </div>
  )
}

export default DocumentFilters
