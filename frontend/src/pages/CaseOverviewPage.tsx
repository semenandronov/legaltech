import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { MessageSquare, FileText, Table } from 'lucide-react'
import { getCase, getRisks, getDiscrepancies, getTimeline, startAnalysis, CaseResponse, DiscrepancyItem, TimelineEvent } from '../services/api'
import CaseHeader from '../components/CaseOverview/CaseHeader'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import RiskCards from '../components/CaseOverview/RiskCards'
import ContradictionsSection from '../components/CaseOverview/ContradictionsSection'
import TimelineSection from '../components/CaseOverview/TimelineSection'
import Spinner from '../components/UI/Spinner'
import { Tabs, TabList, Tab, TabPanel } from '../components/UI/Tabs'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/UI/Card'
import { Alert, AlertDescription, AlertTitle } from '../components/UI/alert'
import { logger } from '@/lib/logger'

const CaseOverviewPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const [caseData, setCaseData] = useState<CaseResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [risks, setRisks] = useState<any[]>([])
  const [contradictions, setContradictions] = useState<any[]>([])
  const [timelineEvents, setTimelineEvents] = useState<any[]>([])
  const [loadingRisks, setLoadingRisks] = useState(false)
  const [loadingContradictions, setLoadingContradictions] = useState(false)
  const [loadingTimeline, setLoadingTimeline] = useState(false)
  const [startingAnalysis, setStartingAnalysis] = useState(false)
  
  useEffect(() => {
    if (caseId) {
      loadCase()
      loadAnalysisData()
    }
  }, [caseId])
  
  const loadCase = async () => {
    if (!caseId) return
    setLoading(true)
    try {
      const data = await getCase(caseId)
      setCaseData(data)
    } catch (error) {
      logger.error('Ошибка при загрузке дела:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleStartAnalysis = async () => {
    if (!caseId || startingAnalysis) return
    setStartingAnalysis(true)
    try {
      await startAnalysis(caseId, ['timeline', 'discrepancies', 'risk_analysis'])
      // Перезагружаем данные через 3 секунды
      setTimeout(() => {
        loadAnalysisData()
      }, 3000)
    } catch (error) {
      logger.error('Ошибка при запуске анализа:', error)
    } finally {
      setStartingAnalysis(false)
    }
  }

  const loadAnalysisData = async () => {
    if (!caseId) return
    
    // Загружаем риски
    setLoadingRisks(true)
    try {
      const risksData = await getRisks(caseId)
      // Преобразуем данные из API в формат компонента
      if (risksData.discrepancies && typeof risksData.discrepancies === 'object' && Object.keys(risksData.discrepancies).length > 0) {
        const formattedRisks = Object.entries(risksData.discrepancies).map(([key, value]: [string, any]) => {
          const severity = value.severity || 'MEDIUM'
          return {
            id: key,
            level: (severity === 'HIGH' ? 'high-risk' : severity === 'MEDIUM' ? 'medium-risk' : 'low-risk') as 'high-risk' | 'medium-risk' | 'low-risk',
            title: value.title || value.type || key,
            description: value.description || '',
            location: value.location || '',
            document: value.document || value.source_document || '',
            page: value.page || value.source_page,
            section: value.section,
            analysis: value.analysis || value.reasoning || '',
          }
        })
        setRisks(formattedRisks)
      } else {
        setRisks([])
      }
    } catch (error: any) {
      // Если анализ еще не выполнен, это нормально
      if (error?.response?.status !== 404) {
        logger.error('Ошибка при загрузке рисков:', error)
      }
      setRisks([])
    } finally {
      setLoadingRisks(false)
    }

    // Загружаем противоречия
    setLoadingContradictions(true)
    try {
      const discrepanciesData = await getDiscrepancies(caseId)
      if (discrepanciesData.discrepancies && discrepanciesData.discrepancies.length > 0) {
        const formattedContradictions = discrepanciesData.discrepancies.map((item: DiscrepancyItem) => ({
          id: item.id,
          type: item.type,
          description: item.description,
          document1: item.source_documents?.[0] || '',
          document2: item.source_documents?.[1] || '',
          location1: (item.details as any)?.location1 || '',
          location2: (item.details as any)?.location2 || '',
          status: 'review' as const,
        }))
        setContradictions(formattedContradictions)
      } else {
        setContradictions([])
      }
    } catch (error: any) {
      // Если анализ еще не выполнен, это нормально
      if (error?.response?.status !== 404) {
        logger.error('Ошибка при загрузке противоречий:', error)
      }
      setContradictions([])
    } finally {
      setLoadingContradictions(false)
    }

    // Загружаем временную линию
    setLoadingTimeline(true)
    try {
      const timelineData = await getTimeline(caseId)
      if (timelineData.events && timelineData.events.length > 0) {
        const formattedEvents = timelineData.events.map((event: TimelineEvent) => {
          // Определяем иконку по типу события
          let icon: 'calendar' | 'alert' | 'file' | 'check' = 'calendar'
          if (event.event_type) {
            const type = event.event_type.toLowerCase()
            if (type.includes('alert') || type.includes('warning') || type.includes('due')) {
              icon = 'alert'
            } else if (type.includes('check') || type.includes('signed') || type.includes('completed')) {
              icon = 'check'
            } else if (type.includes('file') || type.includes('document')) {
              icon = 'file'
            }
          }
          return {
            id: event.id,
            date: event.date,
            type: event.event_type || '',
            description: event.description,
            icon,
          }
        })
        setTimelineEvents(formattedEvents)
      } else {
        setTimelineEvents([])
      }
    } catch (error: any) {
      // Если анализ еще не выполнен, это нормально
      if (error?.response?.status !== 404) {
        logger.error('Ошибка при загрузке временной линии:', error)
      }
      setTimelineEvents([])
    } finally {
      setLoadingTimeline(false)
    }
  }
  
  if (loading || !caseData) {
    return (
      <div className="flex items-center justify-center h-screen bg-gradient-to-br from-[#F8F9FA] via-white to-[#F0F4F8]">
        <Spinner size="lg" />
      </div>
    )
  }

  const navItems = [
    { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
    { id: 'documents', label: 'Документы', icon: FileText, path: `/cases/${caseId}/documents` },
    { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: `/cases/${caseId}/tabular-review` },
  ]
  
  return (
    <div className="flex h-screen bg-gradient-to-br from-[#F8F9FA] via-white to-[#F0F4F8]">
      <UnifiedSidebar navItems={navItems} title="Legal AI" />
      <div className="flex-1 flex flex-col overflow-hidden">
        <CaseHeader caseData={caseData} />
        <div className="flex-1 overflow-y-auto content-background">
          <div className="p-8 fade-in-up">
            <Tabs defaultTab="overview" className="space-y-6">
              <TabList>
                <Tab id="overview">Обзор</Tab>
                <Tab id="risks">Риски</Tab>
                <Tab id="contradictions">Противоречия</Tab>
                <Tab id="timeline">Временная линия</Tab>
              </TabList>
              
              <TabPanel id="overview" className="space-y-6">
                <Card className="hoverable">
                  <CardHeader>
                    <CardTitle className="font-display text-h2">Обзор дела</CardTitle>
                    <CardDescription className="text-body text-[#6B7280]">
                      Общая информация о деле и его статусе
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
                      <div className="p-4 rounded-lg bg-gradient-to-br from-[#00D4FF]/10 to-[#7C3AED]/10 border border-[#00D4FF]/20">
                        <div className="text-3xl font-display font-bold text-[#00D4FF]">{caseData.num_documents}</div>
                        <div className="text-sm text-[#6B7280] mt-1">Документов</div>
                      </div>
                      <div className="p-4 rounded-lg bg-gradient-to-br from-[#EF4444]/10 to-[#DC2626]/10 border border-[#EF4444]/20">
                        <div className="text-3xl font-display font-bold text-[#EF4444]">{risks.length}</div>
                        <div className="text-sm text-[#6B7280] mt-1">Рисков</div>
                      </div>
                      <div className="p-4 rounded-lg bg-gradient-to-br from-[#F59E0B]/10 to-[#D97706]/10 border border-[#F59E0B]/20">
                        <div className="text-3xl font-display font-bold text-[#F59E0B]">{contradictions.length}</div>
                        <div className="text-sm text-[#6B7280] mt-1">Противоречий</div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </TabPanel>
              
              <TabPanel id="risks" className="space-y-6">
                <div className="flex items-center justify-between">
                  <h2 className="font-display text-h1 text-[#1F2937]">
                    Ключевые риски ({risks.length} выявлено)
                  </h2>
                  {risks.length === 0 && !loadingRisks && (
                    <button
                      onClick={handleStartAnalysis}
                      disabled={startingAnalysis}
                      className="px-6 py-3 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {startingAnalysis ? 'Запуск анализа...' : 'Запустить анализ рисков'}
                    </button>
                  )}
                </div>
                {loadingRisks ? (
                  <div className="flex items-center justify-center py-8">
                    <Spinner size="lg" />
                  </div>
                ) : risks.length === 0 ? (
                  <Alert>
                    <AlertTitle>Анализ не выполнен</AlertTitle>
                    <AlertDescription>
                      Для выявления рисков необходимо запустить анализ документов.
                      <button
                        onClick={handleStartAnalysis}
                        disabled={startingAnalysis}
                        className="mt-3 px-4 py-2 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white text-sm font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {startingAnalysis ? 'Запуск...' : 'Запустить анализ'}
                      </button>
                    </AlertDescription>
                  </Alert>
                ) : (
                  <RiskCards risks={risks} />
                )}
              </TabPanel>
              
              <TabPanel id="contradictions" className="space-y-6">
                <div className="flex items-center justify-between">
                  <h2 className="font-display text-h1 text-[#1F2937]">
                    Противоречия ({contradictions.length} найдено)
                  </h2>
                  {contradictions.length === 0 && !loadingContradictions && (
                    <button
                      onClick={handleStartAnalysis}
                      disabled={startingAnalysis}
                      className="px-6 py-3 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {startingAnalysis ? 'Запуск анализа...' : 'Запустить анализ противоречий'}
                    </button>
                  )}
                </div>
                {loadingContradictions ? (
                  <div className="flex items-center justify-center py-8">
                    <Spinner size="lg" />
                  </div>
                ) : contradictions.length === 0 ? (
                  <Alert>
                    <AlertTitle>Анализ не выполнен</AlertTitle>
                    <AlertDescription>
                      Для поиска противоречий необходимо запустить анализ документов.
                      <button
                        onClick={handleStartAnalysis}
                        disabled={startingAnalysis}
                        className="mt-3 px-4 py-2 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white text-sm font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {startingAnalysis ? 'Запуск...' : 'Запустить анализ'}
                      </button>
                    </AlertDescription>
                  </Alert>
                ) : (
                  <ContradictionsSection contradictions={contradictions} />
                )}
              </TabPanel>
              
              <TabPanel id="timeline" className="space-y-6">
                <div className="flex items-center justify-between">
                  <h2 className="font-display text-h1 text-[#1F2937]">Временная линия</h2>
                  {timelineEvents.length === 0 && !loadingTimeline && (
                    <button
                      onClick={handleStartAnalysis}
                      disabled={startingAnalysis}
                      className="px-6 py-3 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {startingAnalysis ? 'Запуск анализа...' : 'Запустить анализ временной линии'}
                    </button>
                  )}
                </div>
                {loadingTimeline ? (
                  <div className="flex items-center justify-center py-8">
                    <Spinner size="lg" />
                  </div>
                ) : timelineEvents.length === 0 ? (
                  <Alert>
                    <AlertTitle>Анализ не выполнен</AlertTitle>
                    <AlertDescription>
                      Для построения временной линии необходимо запустить анализ документов.
                      <button
                        onClick={handleStartAnalysis}
                        disabled={startingAnalysis}
                        className="mt-3 px-4 py-2 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white text-sm font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {startingAnalysis ? 'Запуск...' : 'Запустить анализ'}
                      </button>
                    </AlertDescription>
                  </Alert>
                ) : (
                  <TimelineSection events={timelineEvents} />
                )}
              </TabPanel>
            </Tabs>
          </div>
        </div>
      </div>
    </div>
  )
}

export default CaseOverviewPage
