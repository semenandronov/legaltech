import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Box,
  Button,
  Typography,
  Stack,
  Paper,
  Alert,
  CircularProgress,
  Tabs,
  Tab,
  Container,
} from '@mui/material'
import {
  ArrowBack as ArrowBackIcon,
} from '@mui/icons-material'
import MainLayout from '../components/Layout/MainLayout'
import ProfileTab from '../components/Settings/ProfileTab'
import NotificationsTab from '../components/Settings/NotificationsTab'
import IntegrationsTab from '../components/Settings/IntegrationsTab'
import SecurityTab from '../components/Settings/SecurityTab'
import { getProfile, getNotifications, getIntegrations, UserProfile, NotificationSettings, IntegrationSettings } from '../services/api'

const SettingsPage = () => {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('profile')
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [notifications, setNotifications] = useState<NotificationSettings | null>(null)
  const [integrations, setIntegrations] = useState<IntegrationSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadSettings()
  }, [])

  const loadSettings = async () => {
    setLoading(true)
    setError(null)
    try {
      const [profileData, notificationsData, integrationsData] = await Promise.all([
        getProfile(),
        getNotifications(),
        getIntegrations(),
      ])
      setProfile(profileData)
      setNotifications(notificationsData)
      setIntegrations(integrationsData)
    } catch (error: unknown) {
      const errorMessage = error && typeof error === 'object' && 'response' in error
        ? (error as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'Ошибка при загрузке настроек'
        : 'Ошибка при загрузке настроек'
      setError(errorMessage)
    } finally {
      setLoading(false)
    }
  }

  const tabs = [
    { id: 'profile', label: 'Профиль', icon: '👤' },
    { id: 'notifications', label: 'Уведомления', icon: '🔔' },
    { id: 'integrations', label: 'Интеграции', icon: '🔗' },
    { id: 'security', label: 'Безопасность', icon: '🔒' },
  ]

  if (loading) {
    return (
      <MainLayout>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
          }}
        >
          <CircularProgress />
        </Box>
      </MainLayout>
    )
  }

  return (
    <MainLayout>
      <Container maxWidth="lg" sx={{ py: 3 }}>
        <Stack spacing={3}>
          {/* Header */}
          <Paper
            elevation={0}
            sx={{
              p: 2,
              borderBottom: '1px solid',
              borderColor: 'divider',
              bgcolor: 'background.paper',
            }}
          >
            <Stack direction="row" spacing={2} alignItems="center">
              <Button
                startIcon={<ArrowBackIcon />}
                onClick={() => navigate('/')}
                variant="outlined"
                size="small"
                sx={{ textTransform: 'none' }}
              >
                Назад к Dashboard
              </Button>
              <Typography variant="h5" component="h1" sx={{ fontWeight: 600 }}>
                Настройки
              </Typography>
            </Stack>
          </Paper>

          {/* Error Alert */}
          {error && (
            <Alert
              severity="error"
              action={
                <Button color="inherit" size="small" onClick={loadSettings}>
                  Обновить
                </Button>
              }
            >
              {error}
            </Alert>
          )}

          {/* Tabs */}
          <Paper elevation={0} sx={{ border: '1px solid', borderColor: 'divider' }}>
            <Tabs
              value={activeTab}
              onChange={(_, newValue) => setActiveTab(newValue)}
              variant="scrollable"
              scrollButtons="auto"
              sx={{
                borderBottom: 1,
                borderColor: 'divider',
              }}
            >
              {tabs.map((tab) => (
                <Tab
                  key={tab.id}
                  value={tab.id}
                  label={
                    <Stack direction="row" spacing={1} alignItems="center">
                      <span>{tab.icon}</span>
                      <span>{tab.label}</span>
                    </Stack>
                  }
                  sx={{ textTransform: 'none' }}
                />
              ))}
            </Tabs>

            {/* Tab Content */}
            <Box sx={{ p: 3 }}>
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
            </Box>
          </Paper>
        </Stack>
      </Container>
    </MainLayout>
  )
}

export default SettingsPage
