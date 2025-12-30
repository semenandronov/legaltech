import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Settings, HelpCircle, User } from 'lucide-react'
import { CaseResponse } from '../../services/api'
import Breadcrumbs from '../UI/Breadcrumbs'

interface CaseHeaderProps {
  caseData: CaseResponse
}

const CaseHeader = ({ caseData }: CaseHeaderProps) => {
  const navigate = useNavigate()
  
  const breadcrumbs = [
    { label: 'Дела', href: '/cases' },
    { label: caseData.title || 'Дело', href: undefined },
  ]
  
  return (
    <div className="border-b border-[#E5E7EB] bg-white/80 backdrop-blur-sm">
      <div className="px-8 py-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/cases')}
              className="p-2 rounded-lg hover:bg-[#F3F4F6] transition-colors duration-200 text-[#6B7280] hover:text-[#1F2937]"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
            <Breadcrumbs items={breadcrumbs} />
          </div>
          <div className="flex items-center gap-2">
            <button className="p-2 rounded-lg hover:bg-[#F3F4F6] transition-colors duration-200 text-[#6B7280] hover:text-[#1F2937]">
              <Settings className="w-5 h-5" />
            </button>
            <button className="p-2 rounded-lg hover:bg-[#F3F4F6] transition-colors duration-200 text-[#6B7280] hover:text-[#1F2937]">
              <HelpCircle className="w-5 h-5" />
            </button>
            <button className="p-2 rounded-lg hover:bg-[#F3F4F6] transition-colors duration-200 text-[#6B7280] hover:text-[#1F2937]">
              <User className="w-5 h-5" />
            </button>
          </div>
        </div>
        
        <div className="space-y-2">
          <h1 className="font-display text-h1 text-[#1F2937]">
            {caseData.title || 'Без названия'}
          </h1>
          
          {caseData.description && (
            <p className="text-body text-[#6B7280]">{caseData.description}</p>
          )}
        </div>
      </div>
    </div>
  )
}

export default CaseHeader
