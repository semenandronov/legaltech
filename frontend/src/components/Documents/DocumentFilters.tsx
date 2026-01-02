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

  // Полный набор типов документов арбитражных судов РФ (на основе АПК РФ)
  const docTypesByCategory = {
    'Судебные акты': [
      'court_order', 'court_decision', 'court_ruling', 'court_resolution'
    ],
    'Инициирующие дело': [
      'statement_of_claim', 'order_application', 'bankruptcy_application'
    ],
    'Ответные документы': [
      'response_to_claim', 'counterclaim', 'third_party_application', 'third_party_objection'
    ],
    'Ходатайства': [
      'motion', 'motion_evidence', 'motion_security', 'motion_cancel_security', 
      'motion_recusation', 'motion_reinstatement'
    ],
    'Обжалование': [
      'appeal', 'cassation', 'supervisory_appeal'
    ],
    'Специальные производства': [
      'arbitral_annulment', 'arbitral_enforcement', 'creditor_registry', 
      'administrative_challenge', 'admin_penalty_challenge'
    ],
    'Урегулирование': [
      'settlement_agreement', 'protocol_remarks'
    ],
    'Досудебные': [
      'pre_claim', 'written_explanation'
    ],
    'Приложения': [
      'power_of_attorney', 'egrul_extract', 'state_duty'
    ],
    'Доказательства - Письменные': [
      'contract', 'act', 'certificate', 'correspondence', 'electronic_document', 
      'protocol', 'expert_opinion', 'specialist_consultation', 'witness_statement'
    ],
    'Доказательства - Мультимедиа': [
      'audio_recording', 'video_recording', 'physical_evidence'
    ],
    'Прочие': ['other']
  }
  
  const docTypeLabels: Record<string, string> = {
    // Судебные акты
    'court_order': 'Судебный приказ',
    'court_decision': 'Решение',
    'court_ruling': 'Определение',
    'court_resolution': 'Постановление',
    
    // Инициирующие дело
    'statement_of_claim': 'Исковое заявление',
    'order_application': 'Заявление о выдаче судебного приказа',
    'bankruptcy_application': 'Заявление о признании должника банкротом',
    
    // Ответные документы
    'response_to_claim': 'Отзыв на исковое заявление',
    'counterclaim': 'Встречный иск',
    'third_party_application': 'Заявление о вступлении третьего лица в дело',
    'third_party_objection': 'Возражения третьего лица',
    
    // Ходатайства
    'motion': 'Ходатайство',
    'motion_evidence': 'Ходатайство о доказательствах',
    'motion_security': 'Ходатайство об обеспечительных мерах',
    'motion_cancel_security': 'Ходатайство об отмене обеспечения иска',
    'motion_recusation': 'Ходатайство об отводе судьи',
    'motion_reinstatement': 'Ходатайство о восстановлении пропущенного срока',
    
    // Обжалование
    'appeal': 'Апелляционная жалоба',
    'cassation': 'Кассационная жалоба',
    'supervisory_appeal': 'Надзорная жалоба',
    
    // Специальные производства
    'arbitral_annulment': 'Заявление об отмене решения третейского суда',
    'arbitral_enforcement': 'Заявление о выдаче исполнительного листа на решение третейского суда',
    'creditor_registry': 'Заявление о включении требования в реестр требований кредиторов',
    'administrative_challenge': 'Заявление об оспаривании ненормативного правового акта',
    'admin_penalty_challenge': 'Заявление об оспаривании решения административного органа',
    
    // Урегулирование
    'settlement_agreement': 'Мировое соглашение',
    'protocol_remarks': 'Замечания на протокол судебного заседания',
    
    // Досудебные
    'pre_claim': 'Претензия (досудебное требование)',
    'written_explanation': 'Письменное объяснение по делу',
    
    // Приложения
    'power_of_attorney': 'Доверенность',
    'egrul_extract': 'Выписка из ЕГРЮЛ/ЕГРИП',
    'state_duty': 'Документ об уплате государственной пошлины',
    
    // Доказательства - Письменные
    'contract': 'Договор',
    'act': 'Акт',
    'certificate': 'Справка',
    'correspondence': 'Деловая переписка',
    'electronic_document': 'Электронный документ',
    'protocol': 'Протокол',
    'expert_opinion': 'Заключение эксперта',
    'specialist_consultation': 'Консультация специалиста',
    'witness_statement': 'Показания свидетеля',
    
    // Доказательства - Мультимедиа
    'audio_recording': 'Аудиозапись',
    'video_recording': 'Видеозапись',
    'physical_evidence': 'Вещественное доказательство',
    
    // Прочие
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
