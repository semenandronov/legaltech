import React, { useState } from 'react'
import { PrivilegeCheck } from '../../services/api'
import ConfidenceBadge from '../Common/ConfidenceBadge'
import './Analysis.css'

interface PrivilegeCheckViewProps {
  privilegeCheck: PrivilegeCheck
}

const PrivilegeCheckView: React.FC<PrivilegeCheckViewProps> = ({
  privilegeCheck
}) => {
  const [showReasoning, setShowReasoning] = useState(true)

  const confidence = typeof privilegeCheck.confidence === 'string'
    ? parseFloat(privilegeCheck.confidence)
    : privilegeCheck.confidence || 0

  const isHighConfidence = confidence >= 95
  const isCritical = privilegeCheck.is_privileged && !isHighConfidence

  return (
    <div className={`privilege-check-view ${isCritical ? 'critical' : ''}`}>
      <div className="privilege-check-header">
        <h3>🔒 Privilege Check</h3>
        {isCritical && (
          <span className="privilege-check-warning-badge">
            ⚠️ LOW CONFIDENCE
          </span>
        )}
      </div>

      <div className="privilege-check-content">
        <div className="privilege-check-status">
          <span className="privilege-check-status-label">Статус:</span>
          <span className={`privilege-check-status-value ${privilegeCheck.is_privileged ? 'privileged' : 'not-privileged'}`}>
            {privilegeCheck.is_privileged ? '✅ ПРИВИЛЕГИРОВАН' : '❌ НЕ ПРИВИЛЕГИРОВАН'}
          </span>
        </div>

        <div className="privilege-check-item">
          <span className="privilege-check-label">Тип привилегии:</span>
          <span className="privilege-check-value">{privilegeCheck.privilege_type}</span>
        </div>

        <div className="privilege-check-item">
          <span className="privilege-check-label">Confidence:</span>
          <ConfidenceBadge confidence={confidence} />
          {!isHighConfidence && (
            <span className="privilege-check-warning">
              ⚠️ Ниже 95% - требуется human review!
            </span>
          )}
        </div>

        {privilegeCheck.reasoning && privilegeCheck.reasoning.length > 0 && (
          <div className="privilege-check-item">
            <button
              className="privilege-check-reasoning-toggle"
              onClick={() => setShowReasoning(!showReasoning)}
            >
              {showReasoning ? '▼' : '▶'} Reasoning Factors
            </button>
            {showReasoning && (
              <ul className="privilege-check-reasoning-list">
                {privilegeCheck.reasoning.map((reason, idx) => (
                  <li key={idx}>{reason}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="privilege-check-item">
          <span className="privilege-check-label">Withhold Recommendation:</span>
          <span className={`privilege-check-value ${privilegeCheck.withhold_recommendation ? 'withhold' : ''}`}>
            {privilegeCheck.withhold_recommendation ? '✅ Да' : '❌ Нет'}
          </span>
        </div>

        {privilegeCheck.requires_human_review && (
          <div className="privilege-check-warning-box">
            <div className="privilege-check-warning-icon">⚠️</div>
            <div className="privilege-check-warning-text">
              <strong>ВСЕГДА требуется human review для финального решения!</strong>
              <p>Это критично для e-discovery. AI может ошибиться, что приведет к разглашению конфиденциального документа.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default PrivilegeCheckView
