import { useState } from 'react'
import { updateNotifications, NotificationSettings } from '../../services/api'
import './Settings.css'

interface NotificationsTabProps {
  settings: NotificationSettings
  onUpdate: (newSettings: NotificationSettings) => void
}

const NotificationsTab = ({ settings, onUpdate }: NotificationsTabProps) => {
  const [formSettings, setFormSettings] = useState(settings)
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleToggle = (key: string) => {
    setFormSettings((prev) => ({ ...prev, [key]: !prev[key as keyof NotificationSettings] }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setSuccess(false)
    setError(null)

    try {
      await updateNotifications(formSettings)
      setSuccess(true)
      onUpdate(formSettings)
      setTimeout(() => setSuccess(false), 3000)
    } catch (error: unknown) {
      const errorMessage = error && typeof error === 'object' && 'response' in error
        ? (error as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'Ошибка при обновлении уведомлений'
        : 'Ошибка при обновлении уведомлений'
      setError(errorMessage)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="settings-tab-content">
      <h2 className="settings-section-title">Уведомления</h2>
      <form onSubmit={handleSubmit} className="settings-form">
        <div className="settings-field">
          <label className="settings-label">Email уведомления</label>
          <div className="settings-checkboxes">
            <label className="settings-checkbox">
              <input
                type="checkbox"
                checked={formSettings.email_on_analysis_complete ?? false}
                onChange={() => handleToggle('email_on_analysis_complete')}
              />
              <span>Когда анализ завершен</span>
            </label>
            <label className="settings-checkbox">
              <input
                type="checkbox"
                checked={formSettings.email_on_critical_discrepancies ?? false}
                onChange={() => handleToggle('email_on_critical_discrepancies')}
              />
              <span>Когда найдены критичные противоречия</span>
            </label>
            <label className="settings-checkbox">
              <input
                type="checkbox"
                checked={formSettings.weekly_digest ?? false}
                onChange={() => handleToggle('weekly_digest')}
              />
              <span>Еженедельный дайджест активности</span>
            </label>
            <label className="settings-checkbox">
              <input
                type="checkbox"
                checked={formSettings.reminders_for_important_dates ?? false}
                onChange={() => handleToggle('reminders_for_important_dates')}
              />
              <span>Напоминания о важных датах в делах</span>
            </label>
            <label className="settings-checkbox">
              <input
                type="checkbox"
                checked={formSettings.news_and_updates ?? false}
                onChange={() => handleToggle('news_and_updates')}
              />
              <span>Новости и обновления LEGALCHAIN</span>
            </label>
          </div>
        </div>

        {error && <div className="settings-error">{error}</div>}
        {success && (
          <div className="settings-success">Настройки уведомлений обновлены!</div>
        )}

        <div className="settings-form-actions">
          <button type="submit" className="settings-save-btn" disabled={loading}>
            {loading ? 'Сохранение...' : 'Сохранить'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default NotificationsTab
