import { FileText, ExternalLink } from 'lucide-react'
import { Card } from '../UI/Card'

interface Risk {
  id: string
  level: 'high-risk' | 'medium-risk' | 'low-risk'
  title: string
  description: string
  location: string
  document: string
  page?: number
  section?: string
  analysis?: string
}

interface RiskCardsProps {
  risks: Risk[]
  onViewDocument?: (document: string, page?: number) => void
}

const RiskCards = ({ risks, onViewDocument }: RiskCardsProps) => {
  if (risks.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-body text-[#6B7280]">Риски не выявлены</p>
      </div>
    )
  }

  const getRiskStyles = (level: string) => {
    switch (level) {
      case 'high-risk':
        return {
          border: 'border-l-4 border-[#EF4444]',
          badge: 'bg-gradient-to-r from-[#EF4444]/20 to-[#DC2626]/20 text-[#EF4444] border border-[#EF4444]/30',
          icon: '🔴'
        }
      case 'medium-risk':
        return {
          border: 'border-l-4 border-[#F59E0B]',
          badge: 'bg-gradient-to-r from-[#F59E0B]/20 to-[#D97706]/20 text-[#F59E0B] border border-[#F59E0B]/30',
          icon: '🟡'
        }
      default:
        return {
          border: 'border-l-4 border-[#10B981]',
          badge: 'bg-gradient-to-r from-[#10B981]/20 to-[#059669]/20 text-[#10B981] border border-[#10B981]/30',
          icon: '🟢'
        }
    }
  }
  
  return (
    <div className="space-y-4">
      {risks.map((risk, index) => {
        const styles = getRiskStyles(risk.level)
        return (
          <Card 
            key={risk.id} 
            className={`${styles.border} hoverable`}
            style={{ animationDelay: `${index * 0.05}s` }}
          >
            <div className="space-y-4">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <span className={`px-3 py-1 rounded-full text-xs font-medium ${styles.badge}`}>
                    {styles.icon} {risk.level === 'high-risk' ? 'High' : risk.level === 'medium-risk' ? 'Medium' : 'Low'}
                  </span>
                  <h3 className="font-display text-h3 text-[#1F2937]">{risk.title}</h3>
                </div>
              </div>
              
              <p className="text-body text-[#374151]">{risk.description}</p>
              
              <div className="flex items-center gap-2 text-sm text-[#6B7280]">
                <FileText className="w-4 h-4" />
                <span>
                  {risk.location}
                  {risk.section && `, ${risk.section}`}
                </span>
              </div>
              
              {risk.analysis && (
                <div className="bg-gradient-to-r from-[#F3F4F6] to-[#E5E7EB] rounded-lg p-4 border border-[#E5E7EB]">
                  <p className="text-sm text-[#6B7280] italic">"{risk.analysis}"</p>
                </div>
              )}
              
              <div className="flex items-center gap-2 pt-3 border-t border-[#E5E7EB]">
                <button
                  onClick={() => onViewDocument?.(risk.document, risk.page)}
                  className="px-4 py-2 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white text-sm font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300 flex items-center gap-2"
                >
                  <ExternalLink className="w-4 h-4" />
                  Открыть в документе
                </button>
              </div>
            </div>
          </Card>
        )
      })}
    </div>
  )
}

export default RiskCards
