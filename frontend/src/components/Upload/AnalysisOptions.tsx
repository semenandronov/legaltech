import { useState } from 'react'
import './Upload.css'

export interface AnalysisOptions {
  timeline: boolean
  discrepancies: boolean
  key_facts: boolean
  summary: boolean
  risk_analysis: boolean
}

interface AnalysisOptionsProps {
  onSubmit: (options: AnalysisOptions) => void
  onBack: () => void
}

const AnalysisOptions = ({ onSubmit, onBack }: AnalysisOptionsProps) => {
  const [options, setOptions] = useState<AnalysisOptions>({
    timeline: true,
    discrepancies: true,
    key_facts: true,
    summary: true,
    risk_analysis: false,
  })

  const handleToggle = (key: keyof AnalysisOptions) => {
    setOptions((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    // At least one option must be selected
    if (!Object.values(options).some((v) => v)) {
      alert('Выберите хотя бы один тип анализа')
      return
    }
    onSubmit(options)
  }

  return (
    <div className="upload-step-container">
      <h2 className="upload-step-title">Выбери тип анализа</h2>
      <form onSubmit={handleSubmit} className="upload-form">
        <div className="analysis-options-list">
          <label className="analysis-option">
            <input
              type="checkbox"
              checked={options.timeline}
              onChange={() => handleToggle('timeline')}
            />
            <div className="analysis-option-content">
              <div className="analysis-option-title">📅 Таймлайн</div>
              <div className="analysis-option-description">
                Все даты и события в хронологическом порядке
              </div>
            </div>
          </label>

          <label className="analysis-option">
            <input
              type="checkbox"
              checked={options.discrepancies}
              onChange={() => handleToggle('discrepancies')}
            />
            <div className="analysis-option-content">
              <div className="analysis-option-title">⚠️ Противоречия</div>
              <div className="analysis-option-description">
                Найди все несоответствия между документами
              </div>
            </div>
          </label>

          <label className="analysis-option">
            <input
              type="checkbox"
              checked={options.key_facts}
              onChange={() => handleToggle('key_facts')}
            />
            <div className="analysis-option-content">
              <div className="analysis-option-title">🎯 Ключевые факты</div>
              <div className="analysis-option-description">
                Выдели главное: стороны, суммы, даты, суть спора
              </div>
            </div>
          </label>

          <label className="analysis-option">
            <input
              type="checkbox"
              checked={options.summary}
              onChange={() => handleToggle('summary')}
            />
            <div className="analysis-option-content">
              <div className="analysis-option-title">📊 Summary</div>
              <div className="analysis-option-description">
                Краткое резюме дела
              </div>
            </div>
          </label>

          <label className="analysis-option">
            <input
              type="checkbox"
              checked={options.risk_analysis}
              onChange={() => handleToggle('risk_analysis')}
            />
            <div className="analysis-option-content">
              <div className="analysis-option-title">📈 Риск-оценка</div>
              <div className="analysis-option-description">
                Оцени серьезность и риски (дополнительная опция)
              </div>
            </div>
          </label>
        </div>

        <div className="upload-form-actions">
          <button type="button" className="upload-button-secondary" onClick={onBack}>
            Назад
          </button>
          <button type="submit" className="upload-button-primary">
            Далее
          </button>
        </div>
      </form>
    </div>
  )
}

export default AnalysisOptions

