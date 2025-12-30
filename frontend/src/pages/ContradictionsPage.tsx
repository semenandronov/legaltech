import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { getDiscrepancies, DiscrepancyItem } from '../services/api'
import MainLayout from '../components/Layout/MainLayout'
import CaseNavigation from '../components/CaseOverview/CaseNavigation'
import ContradictionsSection from '../components/CaseOverview/ContradictionsSection'
import Modal from '../components/UI/Modal'
import { Card } from '../components/UI/Card'
import { Badge } from '../components/UI/Badge'
import Spinner from '../components/UI/Spinner'

const ContradictionsPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const [contradictions, setContradictions] = useState<DiscrepancyItem[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedContradiction, setSelectedContradiction] = useState<DiscrepancyItem | null>(null)
  
  useEffect(() => {
    if (caseId) {
      loadContradictions()
    }
  }, [caseId])
  
  const loadContradictions = async () => {
    if (!caseId) return
    setLoading(true)
    try {
      const data = await getDiscrepancies(caseId)
      setContradictions(data.discrepancies)
    } catch (error) {
      console.error('Ошибка при загрузке противоречий:', error)
    } finally {
      setLoading(false)
    }
  }
  
  const formatContradictions = (discrepancies: DiscrepancyItem[]) => {
    return discrepancies.map(d => ({
      id: d.id,
      type: d.type,
      description: d.description,
      document1: d.source_documents[0] || '',
      document2: d.source_documents[1] || '',
      status: 'review' as const,
      severity: d.severity,
    }))
  }
  
  if (loading) {
    return (
      <MainLayout>
        <div className="flex items-center justify-center h-full">
          <Spinner size="lg" />
        </div>
      </MainLayout>
    )
  }
  
  const formattedContradictions = formatContradictions(contradictions)
  
  return (
    <MainLayout>
      <div className="flex h-full">
        {caseId && <CaseNavigation caseId={caseId} />}
        <div className="flex-1 overflow-y-auto p-6">
          <h1 className="text-h1 text-primary mb-6">
            Противоречия ({contradictions.length} найдено)
          </h1>
          <ContradictionsSection
            contradictions={formattedContradictions}
            onResolve={(id) => console.log('Resolve', id)}
            onIgnore={(id) => console.log('Ignore', id)}
            onViewDocument={(document) => {
              const contradiction = contradictions.find(c => c.source_documents.includes(document))
              if (contradiction) setSelectedContradiction(contradiction)
            }}
          />
        </div>
      </div>
      
      {selectedContradiction && (
        <Modal
          isOpen={!!selectedContradiction}
          onClose={() => setSelectedContradiction(null)}
          title="Детали противоречия"
          size="xl"
        >
          <div className="space-y-4">
            <div>
              <Badge variant={selectedContradiction.severity === 'HIGH' ? 'destructive' : selectedContradiction.severity === 'MEDIUM' ? 'secondary' : 'default'}>
                {selectedContradiction.severity}
              </Badge>
              <h3 className="text-h3 text-primary mt-2">{selectedContradiction.type}</h3>
              <p className="text-body text-primary mt-2">{selectedContradiction.description}</p>
            </div>
            
            <div className="grid grid-cols-2 gap-4">
              {selectedContradiction.source_documents.map((doc, index) => (
                <Card key={index}>
                  <h4 className="text-body font-medium text-primary mb-2">Документ {index + 1}</h4>
                  <p className="text-body text-secondary">{doc}</p>
                </Card>
              ))}
            </div>
            
            {selectedContradiction.details && (
              <Card>
                <h4 className="text-body font-medium text-primary mb-2">Детали</h4>
                <pre className="text-small text-primary whitespace-pre-wrap">
                  {JSON.stringify(selectedContradiction.details, null, 2)}
                </pre>
              </Card>
            )}
          </div>
        </Modal>
      )}
    </MainLayout>
  )
}

export default ContradictionsPage
