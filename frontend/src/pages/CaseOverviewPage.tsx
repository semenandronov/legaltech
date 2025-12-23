import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { getCase, getRisks, getDiscrepancies, getTimeline, startAnalysis, CaseResponse, DiscrepancyItem, TimelineEvent } from '../services/api'
import CaseHeader from '../components/CaseOverview/CaseHeader'
import CaseNavigation from '../components/CaseOverview/CaseNavigation'
import RiskCards from '../components/CaseOverview/RiskCards'
import ContradictionsSection from '../components/CaseOverview/ContradictionsSection'
import TimelineSection from '../components/CaseOverview/TimelineSection'
import Spinner from '../components/UI/Spinner'
import { Tabs, TabList, Tab, TabPanel } from '../components/UI/Tabs'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/UI/Card'
import { Button } from '../components/UI/Button'
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
      <div className="flex items-center justify-center h-screen">
        <Spinner size="lg" />
      </div>
    )
  }
  
  return (
    <div className="flex h-screen bg-primary">
      <CaseNavigation caseId={caseId!} />
      <div className="flex-1 flex flex-col overflow-hidden">
        <CaseHeader caseData={caseData} />
        <div className="flex-1 overflow-y-auto">
          <div className="p-6">
            <Tabs defaultTab="overview" className="space-y-6">
              <TabList>
                <Tab id="overview">Обзор</Tab>
                <Tab id="risks">Риски</Tab>
                <Tab id="contradictions">Противоречия</Tab>
                <Tab id="timeline">Временная линия</Tab>
              </TabList>
              
              <TabPanel id="overview" className="space-y-6">
                <Card>
                  <CardHeader>
                    <CardTitle>Обзор дела</CardTitle>
                    <CardDescription>
                      Общая информация о деле и его статусе
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      <div>
                        <div className="text-2xl font-bold text-primary">{caseData.num_documents}</div>
                        <div className="text-sm text-muted-foreground">Документов</div>
                      </div>
                      <div>
                        <div className="text-2xl font-bold text-error">{risks.length}</div>
                        <div className="text-sm text-muted-foreground">Рисков</div>
                      </div>
                      <div>
                        <div className="text-2xl font-bold text-warning">{contradictions.length}</div>
                        <div className="text-sm text-muted-foreground">Противоречий</div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </TabPanel>
              
              <TabPanel id="risks" className="space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-h2 text-primary">
                    Ключевые риски ({risks.length} выявлено)
                  </h2>
                  {risks.length === 0 && !loadingRisks && (
                    <Button 
                      variant="primary" 
                      onClick={handleStartAnalysis}
                      disabled={startingAnalysis}
                    >
                      {startingAnalysis ? 'Запуск анализа...' : 'Запустить анализ рисков'}
                    </Button>
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
                      <Button 
                        variant="primary" 
                        size="sm"
                        className="mt-2"
                        onClick={handleStartAnalysis}
                        disabled={startingAnalysis}
                      >
                        {startingAnalysis ? 'Запуск...' : 'Запустить анализ'}
                      </Button>
                    </AlertDescription>
                  </Alert>
                ) : (
                  <RiskCards risks={risks} />
                )}
              </TabPanel>
              
              <TabPanel id="contradictions" className="space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-h2 text-primary">
                    Противоречия ({contradictions.length} найдено)
                  </h2>
                  {contradictions.length === 0 && !loadingContradictions && (
                    <Button 
                      variant="primary" 
                      onClick={handleStartAnalysis}
                      disabled={startingAnalysis}
                    >
                      {startingAnalysis ? 'Запуск анализа...' : 'Запустить анализ противоречий'}
                    </Button>
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
                      <Button 
                        variant="primary" 
                        size="sm"
                        className="mt-2"
                        onClick={handleStartAnalysis}
                        disabled={startingAnalysis}
                      >
                        {startingAnalysis ? 'Запуск...' : 'Запустить анализ'}
                      </Button>
                    </AlertDescription>
                  </Alert>
                ) : (
                  <ContradictionsSection contradictions={contradictions} />
                )}
              </TabPanel>
              
              <TabPanel id="timeline" className="space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-h2 text-primary">Временная линия</h2>
                  {timelineEvents.length === 0 && !loadingTimeline && (
                    <Button 
                      variant="primary" 
                      onClick={handleStartAnalysis}
                      disabled={startingAnalysis}
                    >
                      {startingAnalysis ? 'Запуск анализа...' : 'Запустить анализ временной линии'}
                    </Button>
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
                      <Button 
                        variant="primary" 
                        size="sm"
                        className="mt-2"
                        onClick={handleStartAnalysis}
                        disabled={startingAnalysis}
                      >
                        {startingAnalysis ? 'Запуск...' : 'Запустить анализ'}
                      </Button>
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
