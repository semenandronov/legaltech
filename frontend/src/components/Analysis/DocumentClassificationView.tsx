import React, { useState } from 'react'
import { DocumentClassification } from '../../services/api'
import ConfidenceBadge from '../Common/ConfidenceBadge'
import './Analysis.css'

interface DocumentClassificationViewProps {
  classification: DocumentClassification
}

const DocumentClassificationView: React.FC<DocumentClassificationViewProps> = ({
  classification
}) => {
  const [showReasoning, setShowReasoning] = useState(false)

  const confidence = typeof classification.confidence === 'string' 
    ? parseFloat(classification.confidence) 
    : classification.confidence || 0

  return (
    <div className="document-classification-view">
      <div className="document-classification-header">
        <h3>Document Classification</h3>
      </div>

      <div className="document-classification-content">
        <div className="document-classification-item">
          <span className="document-classification-label">📋 Тип документа:</span>
          <span className="document-classification-value">{classification.doc_type}</span>
        </div>

        <div className="document-classification-item">
          <span className="document-classification-label">📊 Релевантность:</span>
          <span className="document-classification-value">{classification.relevance_score}%</span>
          <div className="document-classification-progress">
            <div
              className="document-classification-progress-bar"
              style={{ width: `${classification.relevance_score}%` }}
            />
          </div>
        </div>

        <div className="document-classification-item">
          <span className="document-classification-label">🔒 Привилегированность:</span>
          <span className={`document-classification-value ${classification.is_privileged ? 'privileged' : ''}`}>
            {classification.is_privileged ? '✅ Да' : '❌ Нет'}
            {classification.privilege_type !== 'none' && ` (${classification.privilege_type})`}
          </span>
        </div>

        {classification.key_topics && classification.key_topics.length > 0 && (
          <div className="document-classification-item">
            <span className="document-classification-label">📌 Ключевые темы:</span>
            <div className="document-classification-topics">
              {classification.key_topics.map((topic, idx) => (
                <span key={idx} className="document-classification-topic-tag">
                  {topic}
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="document-classification-item">
          <span className="document-classification-label">Confidence:</span>
          <ConfidenceBadge confidence={confidence * 100} />
        </div>

        {classification.reasoning && (
          <div className="document-classification-item">
            <button
              className="document-classification-reasoning-toggle"
              onClick={() => setShowReasoning(!showReasoning)}
            >
              {showReasoning ? '▼' : '▶'} Reasoning
            </button>
            {showReasoning && (
              <div className="document-classification-reasoning">
                {classification.reasoning}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default DocumentClassificationView
