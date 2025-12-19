import React, { useState, useEffect } from 'react'
import { DocumentWithMetadata } from './DocumentsList'
import { ExtractedEntity, getRelatedDocuments, RelatedDocument } from '../../services/api'
import './Documents.css'

interface AIAnalysisPanelProps {
  document: DocumentWithMetadata | null
  entities?: ExtractedEntity[]
  caseId?: string
  onConfirm?: () => void
  onReject?: () => void
  onWithhold?: () => void
  onFlag?: () => void
  onBookmark?: () => void
  onAddComment?: () => void
  onRelatedDocumentClick?: (fileId: string) => void
}

const AIAnalysisPanel: React.FC<AIAnalysisPanelProps> = ({
  document,
  entities = [],
  caseId,
  onConfirm,
  onReject,
  onWithhold,
  onFlag,
  onBookmark,
  onAddComment,
  onRelatedDocumentClick
}) => {
  const [showReasoning, setShowReasoning] = useState(false)
  const [relatedDocuments, setRelatedDocuments] = useState<RelatedDocument[]>([])
  const [loadingRelated, setLoadingRelated] = useState(false)

  useEffect(() => {
    if (document?.id && caseId) {
      loadRelatedDocuments()
    }
  }, [document?.id, caseId])

  const loadRelatedDocuments = async () => {
    if (!document?.id || !caseId) return
    try {
      setLoadingRelated(true)
      const response = await getRelatedDocuments(caseId, document.id, 5)
      setRelatedDocuments(response.related_documents || [])
    } catch (err) {
      console.error('Ошибка при загрузке связанных документов:', err)
    } finally {
      setLoadingRelated(false)
    }
  }

  if (!document) {
    return null
  }

  const classification = document.classification
  const privilegeCheck = document.privilegeCheck
  const relevanceScore = classification?.relevance_score || 0
  const confidence = document.confidence || 0

  const getConfidenceBadge = (conf: number) => {
    if (conf > 90) return { text: `${Math.round(conf)}% ✅`, class: 'high' }
    if (conf > 60) return { text: `${Math.round(conf)}% ⚠️`, class: 'medium' }
    return { text: `${Math.round(conf)}% ❌`, class: 'low' }
  }

  const confidenceBadge = getConfidenceBadge(confidence)

  // Группируем сущности по типу
  const entitiesByType: Record<string, ExtractedEntity[]> = {}
  entities.forEach(entity => {
    if (!entitiesByType[entity.type]) {
      entitiesByType[entity.type] = []
    }
    entitiesByType[entity.type].push(entity)
  })

  return (
    <div className="ai-analysis-panel">
      <div className="ai-analysis-header">
        <h4>🤖 AI ANALYSIS</h4>
      </div>

      <div className="ai-analysis-content">
        {classification && (
          <>
            <div className="ai-analysis-item">
              <span className="ai-analysis-label">📋 Тип:</span>
              <span className="ai-analysis-value">{classification.doc_type}</span>
            </div>

            <div className="ai-analysis-item">
              <span className="ai-analysis-label">📊 Релевантность:</span>
              <span className="ai-analysis-value">{relevanceScore}%</span>
              <div className="ai-analysis-progress">
                <div
                  className="ai-analysis-progress-bar"
                  style={{ width: `${relevanceScore}%` }}
                />
              </div>
            </div>
          </>
        )}

        {privilegeCheck && (
          <div className="ai-analysis-item privilege-item">
            <span className="ai-analysis-label">🔒 Привилегия:</span>
            <span className={`ai-analysis-value ${privilegeCheck.is_privileged ? 'privileged' : ''}`}>
              {privilegeCheck.is_privileged ? '✅ ' : '❌ '}
              {privilegeCheck.confidence}% confident
            </span>
            {privilegeCheck.reasoning && privilegeCheck.reasoning.length > 0 && (
              <div className="ai-analysis-reasoning">
                <button
                  className="ai-analysis-reasoning-toggle"
                  onClick={() => setShowReasoning(!showReasoning)}
                >
                  {showReasoning ? '▼' : '▶'} Reasoning
                </button>
                {showReasoning && (
                  <ul className="ai-analysis-reasoning-list">
                    {privilegeCheck.reasoning.map((reason, idx) => (
                      <li key={idx}>{reason}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {privilegeCheck.requires_human_review && (
              <div className="ai-analysis-warning">
                ⚠️ ВСЕГДА требуется human review для финального решения!
              </div>
            )}
          </div>
        )}

        {entities.length > 0 && (
          <div className="ai-analysis-item">
            <span className="ai-analysis-label">🏷️ Entities:</span>
            <div className="ai-analysis-entities">
              {Object.entries(entitiesByType).map(([type, typeEntities]) => (
                <div key={type} className="ai-analysis-entity-group">
                  <span className="ai-analysis-entity-type">
                    {type === 'PERSON' && '👤'}
                    {type === 'ORG' && '🏢'}
                    {type === 'DATE' && '📅'}
                    {type === 'AMOUNT' && '💰'}
                    {type === 'CONTRACT_TERM' && '📝'}
                    {type}:
                  </span>
                  <div className="ai-analysis-entity-items">
                    {typeEntities.slice(0, 5).map((entity) => (
                      <span
                        key={entity.id}
                        className="ai-analysis-entity-item"
                        title={`${entity.text} (${Math.round(entity.confidence * 100)}% confidence)\nContext: ${entity.context}`}
                      >
                        {entity.text}
                      </span>
                    ))}
                    {typeEntities.length > 5 && (
                      <span className="ai-analysis-entity-more">
                        +{typeEntities.length - 5} more
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {classification?.key_topics && classification.key_topics.length > 0 && (
          <div className="ai-analysis-item">
            <span className="ai-analysis-label">📌 Key Topics:</span>
            <div className="ai-analysis-topics">
              {classification.key_topics.map((topic, idx) => (
                <span key={idx} className="ai-analysis-topic-tag">
                  {topic}
                </span>
              ))}
            </div>
          </div>
        )}

        {relatedDocuments.length > 0 && (
          <div className="ai-analysis-item">
            <span className="ai-analysis-label">🔗 Related Docs:</span>
            <div className="ai-analysis-related-docs">
              {relatedDocuments.map((relatedDoc) => (
                <button
                  key={relatedDoc.file_id}
                  className="ai-analysis-related-doc-item"
                  onClick={() => onRelatedDocumentClick?.(relatedDoc.file_id)}
                  title={`Открыть ${relatedDoc.filename}`}
                >
                  <span className="ai-analysis-related-doc-name">
                    {relatedDoc.filename}
                  </span>
                  <span className="ai-analysis-related-doc-score">
                    {relatedDoc.relevance_score}% relevant
                  </span>
                  {relatedDoc.classification && (
                    <span className="ai-analysis-related-doc-type">
                      {relatedDoc.classification.doc_type}
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        {loadingRelated && (
          <div className="ai-analysis-item">
            <span className="ai-analysis-label">🔗 Related Docs:</span>
            <div className="ai-analysis-loading">Загрузка связанных документов...</div>
          </div>
        )}

        <div className="ai-analysis-actions">
          <button
            className="ai-analysis-action-btn primary"
            onClick={onConfirm}
            aria-label="Подтвердить документ"
          >
            ✅ Confirm
          </button>
          <button
            className="ai-analysis-action-btn"
            onClick={onReject}
            aria-label="Отклонить документ"
          >
            ❌ Reject
          </button>
          <button
            className="ai-analysis-action-btn"
            onClick={onWithhold}
            aria-label="Заблокировать документ"
          >
            🔒 Withhold
          </button>
          <button
            className="ai-analysis-action-btn"
            onClick={onFlag}
            aria-label="Пометить для адвоката"
          >
            🚩 Flag
          </button>
          <button
            className="ai-analysis-action-btn"
            onClick={onAddComment}
            aria-label="Добавить комментарий"
          >
            💬 Add Comment
          </button>
          <button
            className="ai-analysis-action-btn"
            onClick={onBookmark}
            aria-label="Добавить в закладки"
          >
            📌 Bookmark
          </button>
        </div>

        <div className="ai-analysis-confidence">
          <span className="ai-analysis-confidence-label">Confidence:</span>
          <span className={`ai-analysis-confidence-badge ${confidenceBadge.class}`}>
            {confidenceBadge.text}
          </span>
        </div>
      </div>
    </div>
  )
}

export default AIAnalysisPanel
