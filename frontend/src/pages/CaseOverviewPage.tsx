import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { getCase } from '../services/api'
import { CaseResponse } from '../services/api'
import CaseHeader from '../components/CaseOverview/CaseHeader'
import CaseNavigation from '../components/CaseOverview/CaseNavigation'
import RiskCards from '../components/CaseOverview/RiskCards'
import ContradictionsSection from '../components/CaseOverview/ContradictionsSection'
import TimelineSection from '../components/CaseOverview/TimelineSection'
import IssueMap from '../components/CaseOverview/IssueMap'
import QuickStats from '../components/CaseOverview/QuickStats'
import Spinner from '../components/UI/Spinner'

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
  
  const [issues] = useState([
    { tag: 'Liability', count: 8 },
    { tag: 'Confidentiality', count: 5 },
    { tag: 'Payment', count: 6 },
    { tag: 'IP Rights', count: 3 },
    { tag: 'Disputes', count: 2 },
    { tag: 'Compliance', count: 4 },
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
          <div className="p-6 space-y-8">
            {/* Key Risks */}
            <section>
              <h2 className="text-h2 text-primary mb-4">
                Ключевые риски ({risks.length} выявлено)
              </h2>
              <RiskCards risks={risks} />
            </section>
            
            {/* Contradictions */}
            <section>
              <h2 className="text-h2 text-primary mb-4">
                Противоречия ({contradictions.length} найдено)
              </h2>
              <ContradictionsSection contradictions={contradictions} />
            </section>
            
            {/* Timeline */}
            <section>
              <h2 className="text-h2 text-primary mb-4">Временная линия</h2>
              <TimelineSection events={timelineEvents} />
            </section>
            
            {/* Issue Map */}
            <section>
              <h2 className="text-h2 text-primary mb-4">Карта вопросов</h2>
              <IssueMap issues={issues} />
            </section>
          </div>
        </div>
      </div>
      <QuickStats
        totalDocuments={caseData.num_documents}
        totalChunks={1234}
        lastIndexed="2ч назад"
        indexStatus="active"
        risksIdentified={risks.length}
        contradictions={contradictions.length}
        teamMembers={2}
      />
    </div>
  )
}

export default CaseOverviewPage
