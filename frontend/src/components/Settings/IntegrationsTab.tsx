import { useState } from 'react'
import { updateIntegrations, IntegrationSettings } from '../../services/api'
import { logger } from '../../lib/logger'
import './Settings.css'

interface IntegrationsTabProps {
  settings: IntegrationSettings
  onUpdate: (newSettings: IntegrationSettings) => void
}

const IntegrationsTab = ({ settings, onUpdate }: IntegrationsTabProps) => {
  const [formSettings, setFormSettings] = useState(settings)
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)
  const [connectError, setConnectError] = useState<string | null>(null)

  const handleConnect = async (service: string) => {
    // In future, implement OAuth flow
    setConnectError(`Интеграция с ${service} будет доступна в будущих версиях`)
    setTimeout(() => setConnectError(null), 5000)
  }

  const handleDisconnect = async (service: string) => {
    setLoading(true)
    try {
      const newSettings: IntegrationSettings = { ...formSettings }
      if (service === 'google_drive' && newSettings.google_drive) {
        newSettings.google_drive = { ...newSettings.google_drive, enabled: false, connected_account: null }
      } else if (service === 'slack' && newSettings.slack) {
        newSettings.slack = { ...newSettings.slack, enabled: false, workspace: null, webhook_url: null }
      }
      await updateIntegrations(newSettings)
      setFormSettings(newSettings)
      onUpdate(newSettings)
      setSuccess(true)
      setTimeout(() => setSuccess(false), 3000)
    } catch (error) {
      logger.error('Ошибка при отключении интеграции:', error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="settings-tab-content">
      <h2 className="settings-section-title">Интеграции</h2>
      {connectError && (
        <div className="settings-error" style={{ marginBottom: '16px' }}>{connectError}</div>
      )}
      <div className="settings-integrations-list">
        <div className="settings-integration-item">
          <div className="settings-integration-info">
            <div className="settings-integration-name">Google Drive</div>
            <div className="settings-integration-status">
              {(formSettings.google_drive as { enabled?: boolean })?.enabled ? (
                <>
                  <span className="settings-integration-status-badge connected">
                    ✅ Подключен
                  </span>
                  {(formSettings.google_drive as { connected_account?: string | null })?.connected_account && (
                    <span className="settings-integration-account">
                      ({(formSettings.google_drive as { connected_account?: string | null }).connected_account})
                    </span>
                  )}
                </>
              ) : (
                <span className="settings-integration-status-badge">❌ Не подключен</span>
              )}
            </div>
          </div>
          <div className="settings-integration-actions">
            {(formSettings.google_drive as { enabled?: boolean })?.enabled ? (
              <button
                className="settings-integration-btn disconnect"
                onClick={() => handleDisconnect('google_drive')}
                disabled={loading}
              >
                Отключить
              </button>
            ) : (
              <button
                className="settings-integration-btn connect"
                onClick={() => handleConnect('google_drive')}
              >
                Подключить
              </button>
            )}
          </div>
        </div>

        <div className="settings-integration-item">
          <div className="settings-integration-info">
            <div className="settings-integration-name">Slack</div>
            <div className="settings-integration-status">
              {(formSettings.slack as { enabled?: boolean })?.enabled ? (
                <>
                  <span className="settings-integration-status-badge connected">
                    ✅ Подключен
                  </span>
                  {(formSettings.slack as { workspace?: string | null })?.workspace && (
                    <span className="settings-integration-account">
                      (workspace: {(formSettings.slack as { workspace?: string | null }).workspace})
                    </span>
                  )}
                </>
              ) : (
                <span className="settings-integration-status-badge">❌ Не подключен</span>
              )}
            </div>
          </div>
          <div className="settings-integration-actions">
            {(formSettings.slack as { enabled?: boolean })?.enabled ? (
              <button
                className="settings-integration-btn disconnect"
                onClick={() => handleDisconnect('slack')}
                disabled={loading}
              >
                Отключить
              </button>
            ) : (
              <button
                className="settings-integration-btn connect"
                onClick={() => handleConnect('slack')}
              >
                Подключить
              </button>
            )}
          </div>
        </div>
      </div>

      {success && (
        <div className="settings-success">Настройки интеграций обновлены!</div>
      )}
    </div>
  )
}

export default IntegrationsTab
