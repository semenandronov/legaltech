import { useState } from 'react'
import { updatePassword } from '../../services/api'
import './Settings.css'

interface SecurityTabProps {
  onUpdate: () => void
}

const SecurityTab = ({ onUpdate }: SecurityTabProps) => {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccess(false)

    if (newPassword !== confirmPassword) {
      setError('Пароли не совпадают')
      return
    }

    if (newPassword.length < 8) {
      setError('Новый пароль должен быть не менее 8 символов')
      return
    }

    setLoading(true)

    try {
      await updatePassword({
        current_password: currentPassword,
        new_password: newPassword,
      })
      setSuccess(true)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setTimeout(() => setSuccess(false), 3000)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка при изменении пароля')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="settings-tab-content">
      <h2 className="settings-section-title">Безопасность</h2>
      <form onSubmit={handleSubmit} className="settings-form">
        <div className="settings-field">
          <label htmlFor="currentPassword" className="settings-label">
            Текущий пароль
          </label>
          <input
            id="currentPassword"
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            required
            className="settings-input"
            placeholder="••••••••"
          />
        </div>

        <div className="settings-field">
          <label htmlFor="newPassword" className="settings-label">
            Новый пароль (минимум 8 символов)
          </label>
          <input
            id="newPassword"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
            minLength={8}
            className="settings-input"
            placeholder="••••••••"
          />
        </div>

        <div className="settings-field">
          <label htmlFor="confirmPassword" className="settings-label">
            Подтвердите новый пароль
          </label>
          <input
            id="confirmPassword"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            minLength={8}
            className="settings-input"
            placeholder="••••••••"
          />
        </div>

        {error && <div className="settings-error">{error}</div>}
        {success && (
          <div className="settings-success">Пароль успешно изменен!</div>
        )}

        <div className="settings-form-actions">
          <button type="submit" className="settings-save-btn" disabled={loading}>
            {loading ? 'Изменение...' : 'Изменить пароль'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default SecurityTab
