import { useState } from 'react'
import { updateProfile } from '../../services/api'
import './Settings.css'

interface ProfileTabProps {
  profile: any
  onUpdate: () => void
}

const ProfileTab = ({ profile, onUpdate }: ProfileTabProps) => {
  const [fullName, setFullName] = useState(profile.full_name || '')
  const [company, setCompany] = useState(profile.company || '')
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setSuccess(false)

    try {
      await updateProfile({
        full_name: fullName,
        company: company,
      })
      setSuccess(true)
      onUpdate()
      setTimeout(() => setSuccess(false), 3000)
    } catch (error) {
      console.error('Ошибка при обновлении профиля:', error)
      alert('Ошибка при обновлении профиля')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="settings-tab-content">
      <h2 className="settings-section-title">Профиль</h2>
      <form onSubmit={handleSubmit} className="settings-form">
        <div className="settings-field">
          <label htmlFor="email" className="settings-label">
            Email
          </label>
          <input
            id="email"
            type="email"
            value={profile.email}
            disabled
            className="settings-input"
          />
          <p className="settings-hint">Email нельзя изменить</p>
        </div>

        <div className="settings-field">
          <label htmlFor="fullName" className="settings-label">
            ФИО
          </label>
          <input
            id="fullName"
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className="settings-input"
            placeholder="Иванов Иван Иванович"
          />
        </div>

        <div className="settings-field">
          <label htmlFor="company" className="settings-label">
            Компания
          </label>
          <input
            id="company"
            type="text"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            className="settings-input"
            placeholder="ООО Компания"
          />
        </div>

        <div className="settings-field">
          <label className="settings-label">Специализация</label>
          <div className="settings-checkboxes">
            <label className="settings-checkbox">
              <input type="checkbox" defaultChecked />
              <span>Судебные дела</span>
            </label>
            <label className="settings-checkbox">
              <input type="checkbox" defaultChecked />
              <span>Контрактное право</span>
            </label>
            <label className="settings-checkbox">
              <input type="checkbox" />
              <span>M&A</span>
            </label>
            <label className="settings-checkbox">
              <input type="checkbox" />
              <span>Налоговое право</span>
            </label>
          </div>
        </div>

        {success && (
          <div className="settings-success">Профиль успешно обновлен!</div>
        )}

        <div className="settings-form-actions">
          <button type="submit" className="settings-save-btn" disabled={loading}>
            {loading ? 'Сохранение...' : 'Сохранить изменения'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default ProfileTab
