import { useState } from 'react'
import { Search } from 'lucide-react'
import Input from '../UI/Input'

interface CasesFiltersProps {
  onFiltersChange: (filters: FilterState) => void
}

export interface FilterState {
  search: string
  status: string[]
  caseType: string[]
  assignedTo: string[]
  dateFrom: string
  dateTo: string
}

const CasesFilters = ({ onFiltersChange }: CasesFiltersProps) => {
  const [search, setSearch] = useState('')
  
  const handleSearchChange = (value: string) => {
    setSearch(value)
    onFiltersChange({
      search: value,
      status: [],
      caseType: [],
      assignedTo: [],
      dateFrom: '',
      dateTo: '',
    })
  }
  
  return (
    <div className="w-full h-full bg-white/80 backdrop-blur-subtle flex flex-col overflow-y-auto slide-in-left">
      {/* Search */}
      <div className="p-6 border-b border-[#E5E8EB]/50">
        <h3 className="text-sm font-medium text-[#666B78] mb-4 uppercase tracking-wider">Фильтры</h3>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-[#9CA3AF]" />
          <Input
            placeholder="Поиск дел..."
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="pl-10 bg-white border-[#E5E8EB] focus:border-[#00D4FF] focus:ring-2 focus:ring-[#00D4FF]/20 transition-all"
          />
        </div>
      </div>
      
      {/* Additional filters can be added here */}
      <div className="p-6 space-y-4">
        {/* Placeholder for future filters */}
      </div>
    </div>
  )
}

export default CasesFilters
