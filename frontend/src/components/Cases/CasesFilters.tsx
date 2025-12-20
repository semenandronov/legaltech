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
    <div className="w-[280px] h-screen bg-secondary border-r border-border flex flex-col overflow-y-auto">
      {/* Search */}
      <div className="p-4 border-b border-border">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-secondary" />
          <Input
            placeholder="Поиск дел..."
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="pl-10"
          />
        </div>
      </div>
    </div>
  )
}

export default CasesFilters
