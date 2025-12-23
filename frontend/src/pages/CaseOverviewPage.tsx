import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { getCase } from '../services/api'
import { CaseResponse } from '../services/api'
import CaseHeader from '../components/CaseOverview/CaseHeader'
import CaseNavigation from '../components/CaseOverview/CaseNavigation'
import RiskCards from '../components/CaseOverview/RiskCards'
import ContradictionsSection from '../components/CaseOverview/ContradictionsSection'
import TimelineSection from '../components/CaseOverview/TimelineSection'
import Spinner from '../components/UI/Spinner'
import { Tabs, TabList, Tab, TabPanel } from '../components/UI/Tabs'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/UI/Card'

const CaseOverviewPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const [caseData, setCaseData] = useState<CaseResponse | null>(null)
  const [loading, setLoading] = useState(true)
  
  // Mock data - в реальном приложении должно приходить с API
  const [risks] = useState([
    {
      id: '1',
      level: 'high-risk' as const,
      title: 'Limit of Liability',
      description: 'Condition found in contract page 3, section 4.2',
      location: 'contract_main.docx, page 3',
      document: 'contract_main.docx',
      page: 3,
      section: '4.2',
      analysis: 'Limitation not allowed by law 152-FZ',
    },
    {
      id: '2',
      level: 'medium-risk' as const,
      title: 'Penalty Clause',
      description: 'Penalty clause exceeds reasonable limits',
      location: 'letter_counterparty.pdf',
      document: 'letter_counterparty.pdf',
      analysis: 'Penalty sanctions exceed reasonable limits',
    },
  ])
  
  const [contradictions] = useState([
    {
      id: '1',
      type: 'Payment Terms Mismatch',
      description: 'Different payment timelines specified',
      document1: 'contract_main.docx',
      document2: 'addendum_spec.docx',
      location1: 'Page 3, Section 4',
      location2: 'Page 1, Section 2',
      status: 'review' as const,
    },
  ])
  
  const [timelineEvents] = useState([
    {
      id: '1',
      date: '2025-01-15',
      type: 'Case created',
      description: 'Дело создано',
      icon: 'calendar' as const,
    },
    {
      id: '2',
      date: '2025-01-20',
      type: 'Contract signed',
      description: 'Контракт подписан',
      icon: 'check' as const,
    },
    {
      id: '3',
      date: '2025-02-01',
      type: 'Payment due',
      description: 'Срок платежа',
      icon: 'alert' as const,
    },
  ])
  
  
  useEffect(() => {
    if (caseId) {
      loadCase()
    }
  }, [caseId])
  
  const loadCase = async () => {
    if (!caseId) return
    setLoading(true)
    try {
      const data = await getCase(caseId)
      setCaseData(data)
    } catch (error) {
      console.error('Ошибка при загрузке дела:', error)
    } finally {
      setLoading(false)
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
                <h2 className="text-h2 text-primary">
                  Ключевые риски ({risks.length} выявлено)
                </h2>
                <RiskCards risks={risks} />
              </TabPanel>
              
              <TabPanel id="contradictions" className="space-y-4">
                <h2 className="text-h2 text-primary">
                  Противоречия ({contradictions.length} найдено)
                </h2>
                <ContradictionsSection contradictions={contradictions} />
              </TabPanel>
              
              <TabPanel id="timeline" className="space-y-4">
                <h2 className="text-h2 text-primary">Временная линия</h2>
                <TimelineSection events={timelineEvents} />
              </TabPanel>
            </Tabs>
          </div>
        </div>
      </div>
    </div>
  )
}

export default CaseOverviewPage
