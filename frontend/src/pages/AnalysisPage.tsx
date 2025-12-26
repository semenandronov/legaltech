import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Box,
  Button,
  Tabs,
  Tab,
  Alert,
  CircularProgress,
  Typography,
  Stack,
} from '@mui/material'
import { ArrowBack as ArrowBackIcon } from '@mui/icons-material'
import MainLayout from '../components/Layout/MainLayout'
import TimelineTab from '../components/Analysis/TimelineTab'
import DiscrepanciesTab from '../components/Analysis/DiscrepanciesTab'
import KeyFactsTab from '../components/Analysis/KeyFactsTab'
import SummaryTab from '../components/Analysis/SummaryTab'
import RiskAnalysisTab from '../components/Analysis/RiskAnalysisTab'
import RelationshipGraphTab from '../components/Analysis/RelationshipGraphTab'
import { startAnalysis, getAnalysisStatus } from '../services/api'
import './AnalysisPage.css'

const AnalysisPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('timeline')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    if (caseId) {
      loadStatus()
    }
  }, [caseId])

  if (!caseId) {
    return (
      <MainLayout>
        <Box sx={{ p: 3 }}>
          <Typography>Дело не найдено</Typography>
        </Box>
      </MainLayout>
    )
  }

  const loadStatus = async () => {
    if (!caseId) return
    try {
      await getAnalysisStatus(caseId)
      // Status loaded, can be used in future
    } catch (error: any) {
      console.error('Ошибка при загрузке статуса анализа:', error)
      // Не показываем ошибку при загрузке статуса, это не критично
    }
  }

  const handleStartAnalysis = async (types: string[]) => {
    if (!caseId) return
    setLoading(true)
    setError(null)
    setSuccess(false)
    try {
      await startAnalysis(caseId, types)
      setSuccess(true)
      setTimeout(() => setSuccess(false), 3000)
      // Poll for status updates
      setTimeout(() => loadStatus(), 2000)
    } catch (error: any) {
      console.error('Ошибка при запуске анализа:', error)
      setError(error.response?.data?.detail || 'Ошибка при запуске анализа')
    } finally {
      setLoading(false)
    }
  }

  const tabs = [
    { id: 'timeline', label: '📅 Таймлайн', icon: '📅' },
    { id: 'discrepancies', label: '⚠️ Противоречия', icon: '⚠️' },
    { id: 'key_facts', label: '🎯 Ключевые факты', icon: '🎯' },
    { id: 'summary', label: '📊 Резюме', icon: '📊' },
    { id: 'risks', label: '📈 Анализ рисков', icon: '📈' },
    { id: 'relationship', label: '🔗 Граф связей', icon: '🔗' },
  ]

  const handleTabChange = (_event: React.SyntheticEvent, newValue: string) => {
    setActiveTab(newValue)
  }

  return (
    <MainLayout>
      <Box sx={{ p: 3 }}>
        {/* Header */}
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={2}
          sx={{ mb: 3 }}
          justifyContent="space-between"
          alignItems={{ xs: 'flex-start', sm: 'center' }}
        >
          <Stack direction="row" spacing={2} alignItems="center">
            <Button
              startIcon={<ArrowBackIcon />}
              onClick={() => navigate('/')}
              variant="outlined"
              size="small"
            >
              Назад к Dashboard
            </Button>
            <Typography variant="h4" fontWeight={600}>
              Анализ дела
            </Typography>
          </Stack>

          <Stack direction="row" spacing={2} alignItems="center">
            {error && (
              <Alert severity="error" sx={{ py: 0.5 }}>
                {error}
              </Alert>
            )}
            {success && (
              <Alert severity="success" sx={{ py: 0.5 }}>
                Анализ запущен
              </Alert>
            )}
            <Button
              variant="contained"
              onClick={() =>
                handleStartAnalysis([
                  'timeline',
                  'discrepancies',
                  'key_facts',
                  'summary',
                  'risk_analysis',
                ])
              }
              disabled={loading}
              startIcon={loading ? <CircularProgress size={16} /> : null}
            >
              {loading ? 'Запуск...' : 'Запустить полный анализ'}
            </Button>
          </Stack>
        </Stack>

        {/* Tabs */}
        <Tabs
          value={activeTab}
          onChange={handleTabChange}
          variant="scrollable"
          scrollButtons="auto"
          sx={{ mb: 3, borderBottom: 1, borderColor: 'divider' }}
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
            />
          ))}
        </Tabs>

        {/* Content */}
        <Box>
          {activeTab === 'timeline' && caseId && <TimelineTab caseId={caseId} />}
          {activeTab === 'discrepancies' && caseId && (
            <DiscrepanciesTab caseId={caseId} />
          )}
          {activeTab === 'key_facts' && caseId && <KeyFactsTab caseId={caseId} />}
          {activeTab === 'summary' && caseId && <SummaryTab caseId={caseId} />}
          {activeTab === 'risks' && caseId && <RiskAnalysisTab caseId={caseId} />}
          {activeTab === 'relationship' && caseId && (
            <RelationshipGraphTab caseId={caseId} />
          )}
        </Box>
      </Box>
    </MainLayout>
  )
}

export default AnalysisPage

