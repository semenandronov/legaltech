import { useState } from 'react'
import './Upload.css'

export interface CaseInfo {
  title: string
  description: string
  case_type: string
}

interface CaseInfoFormProps {
  onSubmit: (info: CaseInfo) => void
  onCancel: () => void
}

const CaseInfoForm = ({ onSubmit, onCancel }: CaseInfoFormProps) => {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [caseType, setCaseType] = useState('litigation')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) {
      alert('Пожалуйста, укажите название дела')
      return
    }
    onSubmit({
      title: title.trim(),
      description: description.trim(),
      case_type: caseType,
    })
  }

  return (
    <div className="upload-step-container">
      <h2 className="upload-step-title">Информация о деле</h2>
      <form onSubmit={handleSubmit} className="upload-form">
        <div className="upload-field">
          <label htmlFor="title" className="upload-label">
            Название дела *
          </label>
          <input
            id="title"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            className="upload-input"
            placeholder="Например: Иванов vs Петров - Арбитражный суд №5"
          />
        </div>

        <div className="upload-field">
          <label htmlFor="description" className="upload-label">
            Описание (опционально)
          </label>
          <textarea
            id="description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="upload-textarea"
            placeholder="Спор о невыполнении обязательств по контракту"
            rows={4}
          />
        </div>

        <div className="upload-field">
          <label htmlFor="case_type" className="upload-label">
            Тип дела *
          </label>
          <select
            id="case_type"
            value={caseType}
            onChange={(e) => setCaseType(e.target.value)}
            className="upload-select"
            required
          >
            <option value="litigation">Судебное дело</option>
            <option value="contracts">Анализ контрактов</option>
            <option value="dd">Due Diligence (M&A)</option>
            <option value="compliance">Compliance проверка</option>
            <option value="other">Другое</option>
          </select>
        </div>

        <div className="upload-form-actions">
          <button type="button" className="upload-button-secondary" onClick={onCancel}>
            Отменить
          </button>
          <button type="submit" className="upload-button-primary">
            Далее
          </button>
        </div>
      </form>
    </div>
  )
}

export default CaseInfoForm

