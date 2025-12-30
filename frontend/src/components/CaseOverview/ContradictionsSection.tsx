import { AlertTriangle, CheckCircle, XCircle } from 'lucide-react'
import { Card } from '../UI/Card'

interface Contradiction {
  id: string
  type: string
  description: string
  document1: string
  document2: string
  location1?: string
  location2?: string
  status: 'review' | 'resolved' | 'ignored'
  resolvedBy?: string
  resolvedAt?: string
  resolution?: string
}

interface ContradictionsSectionProps {
  contradictions: Contradiction[]
  onResolve?: (id: string) => void
  onIgnore?: (id: string) => void
  onViewDocument?: (document: string) => void
}

const ContradictionsSection = ({
  contradictions,
  onResolve,
  onIgnore,
  onViewDocument,
}: ContradictionsSectionProps) => {
  if (contradictions.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-body text-[#6B7280]">Противоречия не найдены</p>
      </div>
    )
  }
  
  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'resolved':
        return (
          <span className="px-3 py-1 rounded-full text-xs font-medium bg-gradient-to-r from-[#10B981]/20 to-[#059669]/20 text-[#10B981] border border-[#10B981]/30 flex items-center gap-1">
            <CheckCircle className="w-3 h-3" /> Resolved
          </span>
        )
      case 'ignored':
        return (
          <span className="px-3 py-1 rounded-full text-xs font-medium bg-gradient-to-r from-[#6B7280]/20 to-[#4B5563]/20 text-[#6B7280] border border-[#6B7280]/30 flex items-center gap-1">
            <XCircle className="w-3 h-3" /> Ignored
          </span>
        )
      default:
        return (
          <span className="px-3 py-1 rounded-full text-xs font-medium bg-gradient-to-r from-[#F59E0B]/20 to-[#D97706]/20 text-[#F59E0B] border border-[#F59E0B]/30 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" /> Review
          </span>
        )
    }
  }
  
  return (
    <div className="space-y-4">
      {contradictions.map((contradiction, index) => (
        <Card 
          key={contradiction.id} 
          className="border-l-4 border-l-[#F59E0B] hoverable"
          style={{ animationDelay: `${index * 0.05}s` }}
        >
          <div className="space-y-4">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <AlertTriangle className="w-5 h-5 text-[#F59E0B]" />
                <h3 className="font-display text-h3 text-[#1F2937]">{contradiction.type}</h3>
              </div>
              {getStatusBadge(contradiction.status)}
            </div>
            
            <p className="text-body text-[#374151]">{contradiction.description}</p>
            
            <div className="bg-gradient-to-r from-[#F3F4F6] to-[#E5E7EB] rounded-lg p-4 border border-[#E5E7EB] space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-[#1F2937]">Документ 1:</span>
                <button
                  onClick={() => onViewDocument?.(contradiction.document1)}
                  className="text-sm text-[#00D4FF] hover:text-[#7C3AED] underline transition-colors"
                >
                  {contradiction.document1}
                </button>
                {contradiction.location1 && (
                  <span className="text-sm text-[#6B7280]">({contradiction.location1})</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-[#1F2937]">Документ 2:</span>
                <button
                  onClick={() => onViewDocument?.(contradiction.document2)}
                  className="text-sm text-[#00D4FF] hover:text-[#7C3AED] underline transition-colors"
                >
                  {contradiction.document2}
                </button>
                {contradiction.location2 && (
                  <span className="text-sm text-[#6B7280]">({contradiction.location2})</span>
                )}
              </div>
            </div>
            
            {contradiction.status === 'resolved' && contradiction.resolution && (
              <div className="bg-gradient-to-r from-[#10B981]/10 to-[#059669]/10 border border-[#10B981]/30 rounded-lg p-4">
                <p className="text-sm text-[#1F2937]">
                  <strong>Разрешено:</strong> {contradiction.resolution}
                </p>
                {contradiction.resolvedBy && (
                  <p className="text-xs text-[#6B7280] mt-1">
                    {contradiction.resolvedBy} • {contradiction.resolvedAt && new Date(contradiction.resolvedAt).toLocaleDateString('ru-RU')}
                  </p>
                )}
              </div>
            )}
            
            {contradiction.status === 'review' && (
              <div className="flex items-center gap-2 pt-3 border-t border-[#E5E7EB]">
                <button
                  onClick={() => onResolve?.(contradiction.id)}
                  className="px-4 py-2 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white text-sm font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300"
                >
                  Отметить как решённое
                </button>
                <button
                  onClick={() => onIgnore?.(contradiction.id)}
                  className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] transition-all duration-300"
                >
                  Игнорировать
                </button>
              </div>
            )}
          </div>
        </Card>
      ))}
    </div>
  )
}

export default ContradictionsSection
