import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import Sidebar from '../components/Layout/Sidebar'
import Header from '../components/Layout/Header'
import ProfileTab from '../components/Settings/ProfileTab'
import NotificationsTab from '../components/Settings/NotificationsTab'
import IntegrationsTab from '../components/Settings/IntegrationsTab'
import SecurityTab from '../components/Settings/SecurityTab'
import { getProfile, getNotifications, getIntegrations } from '../services/api'
import './SettingsPage.css'

const SettingsPage = () => {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('profile')
  const [profile, setProfile] = useState<any>(null)
  const [notifications, setNotifications] = useState<any>(null)
  const [integrations, setIntegrations] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadSettings()
  }, [])

  const loadSettings = async () => {
    setLoading(true)
    try {
      const [profileData, notificationsData, integrationsData] = await Promise.all([
        getProfile(),
        getNotifications(),
        getIntegrations(),
      ])
      setProfile(profileData)
      setNotifications(notificationsData)
      setIntegrations(integrationsData)
    } catch (error) {
      console.error('Ошибка при загрузке настроек:', error)
    } finally {
      setLoading(false)
    }
  }

  const tabs = [
    { id: 'profile', label: '👤 Профиль', icon: '👤' },
    { id: 'notifications', label: '🔔 Уведомления', icon: '🔔' },
    { id: 'integrations', label: '🔗 Интеграции', icon: '🔗' },
    { id: 'security', label: '🔒 Безопасность', icon: '🔒' },
  ]

  if (loading) {
    return (
      <div className="settings-page-root">
        <Sidebar />
        <div className="settings-page-content" style={{ marginLeft: '250px' }}>
          <Header />
          <main className="settings-page-main">
            <div className="settings-loading">Загрузка настроек...</div>
          </main>
        </div>
      </div>
    )
  }

  return (
    <div className="settings-page-root">
      <Sidebar />
      <div className="settings-page-content" style={{ marginLeft: '250px' }}>
        <Header />
        <main className="settings-page-main">
          <div className="settings-page-header">
            <button className="settings-back-btn" onClick={() => navigate('/')}>
              ← Назад к Dashboard
            </button>
            <h1 className="settings-page-title">Настройки</h1>
          </div>

          <div className="settings-page-tabs">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                className={`settings-tab ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                <span className="settings-tab-icon">{tab.icon}</span>
                <span className="settings-tab-label">{tab.label}</span>
              </button>
            ))}
          </div>

          <div className="settings-page-content-area">
            {activeTab === 'profile' && profile && (
              <ProfileTab profile={profile} onUpdate={loadSettings} />
            )}
            {activeTab === 'notifications' && notifications && (
              <NotificationsTab
                settings={notifications}
                onUpdate={(newSettings) => {
                  setNotifications(newSettings)
                }}
              />
            )}
            {activeTab === 'integrations' && integrations && (
              <IntegrationsTab
                settings={integrations}
                onUpdate={(newSettings) => {
                  setIntegrations(newSettings)
                }}
              />
            )}
            {activeTab === 'security' && (
              <SecurityTab onUpdate={loadSettings} />
            )}
          </div>
        </main>
      </div>
    </div>
  )
}

export default SettingsPage
