import { useState } from 'react'
import './Upload.css'

export interface CaseInfo {
  title: string
  description: string
}

interface CaseInfoFormProps {
  onSubmit: (info: CaseInfo) => void
  onCancel: () => void
}

const CaseInfoForm = ({ onSubmit, onCancel }: CaseInfoFormProps) => {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')

  const [error, setError] = useState<string | null>(null)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!title.trim()) {
      setError('Пожалуйста, укажите название дела')
      return
    }
    onSubmit({
      title: title.trim(),
      description: description.trim(),
    })
  }

  return (
      <div className="upload-step-container">
      <h2 className="upload-step-title">Информация о деле</h2>
      {error && <div className="auth-error" style={{ marginBottom: '16px' }}>{error}</div>}
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

