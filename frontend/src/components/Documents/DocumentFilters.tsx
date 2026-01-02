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

  // Все 26 типов документов, сгруппированные по категориям
  const docTypesByCategory = {
    'Процессуальные': [
      'statement_of_claim', 'application', 'response_to_claim', 'counterclaim', 
      'motion', 'appeal', 'cassation', 'supervisory_appeal', 'protocol_remarks', 'settlement_agreement'
    ],
    'Судебные акты': [
      'court_order', 'court_decision', 'court_ruling', 'court_resolution'
    ],
    'Доказательства': [
      'contract', 'act', 'certificate', 'correspondence', 'electronic_document', 
      'protocol', 'expert_opinion', 'specialist_consultation', 'witness_statement', 
      'audio_recording', 'video_recording', 'physical_evidence'
    ],
    'Прочие': ['other']
  }
  
  const docTypeLabels: Record<string, string> = {
    'statement_of_claim': 'Исковое заявление',
    'application': 'Заявление',
    'response_to_claim': 'Отзыв на иск',
    'counterclaim': 'Встречный иск',
    'motion': 'Ходатайство',
    'appeal': 'Апелляционная жалоба',
    'cassation': 'Кассационная жалоба',
    'supervisory_appeal': 'Надзорная жалоба',
    'protocol_remarks': 'Замечания на протокол',
    'settlement_agreement': 'Мировое соглашение',
    'court_order': 'Судебный приказ',
    'court_decision': 'Решение',
    'court_ruling': 'Определение',
    'court_resolution': 'Постановление',
    'contract': 'Договор',
    'act': 'Акт',
    'certificate': 'Справка',
    'correspondence': 'Деловая переписка',
    'electronic_document': 'Электронный документ',
    'protocol': 'Протокол',
    'expert_opinion': 'Заключение эксперта',
    'specialist_consultation': 'Консультация специалиста',
    'witness_statement': 'Показания свидетеля',
    'audio_recording': 'Аудиозапись',
    'video_recording': 'Видеозапись',
    'physical_evidence': 'Вещественное доказательство',
    'other': 'Другое'
  }
  
  const privilegeStatuses = ['All', 'Privileged', 'Not Privileged', 'Low Confidence', 'needs_review']
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
        <label className="document-filters-group-label">☑ Тип документа:</label>
        {Object.entries(docTypesByCategory).map(([category, types]) => (
          <details key={category} className="document-filters-category" open={category === 'Процессуальные'}>
            <summary className="document-filters-category-summary">{category}</summary>
            <div className="document-filters-checkbox-group">
              {types.map((type: string) => (
                <label key={type} className="document-filters-checkbox">
                  <input
                    type="checkbox"
                    checked={filters.docTypes.includes(type)}
                    onChange={() => handleDocTypeToggle(type)}
                  />
                  <span>{docTypeLabels[type] || type}</span>
                </label>
              ))}
            </div>
          </details>
        ))}
      </div>
      
      <div className="document-filters-group">
        <label className="document-filters-group-label">☑ Требует проверки:</label>
        <div className="document-filters-checkbox-group">
          <label className="document-filters-checkbox">
            <input
              type="checkbox"
              checked={filters.privilegeStatus.includes('needs_review')}
              onChange={() => handlePrivilegeToggle('needs_review')}
            />
            <span>Требует ручной проверки</span>
          </label>
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
