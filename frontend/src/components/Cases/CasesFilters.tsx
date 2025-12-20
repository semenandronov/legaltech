import { useState } from 'react'
import { Search, X } from 'lucide-react'
import Input from '../UI/Input'
import Checkbox from '../UI/Checkbox'
import Select from '../UI/Select'
import DatePicker from '../UI/DatePicker'
import Button from '../UI/Button'

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

const STATUS_OPTIONS = [
  { value: 'review', label: 'Review' },
  { value: 'investigation', label: 'Investigation' },
  { value: 'litigation', label: 'Litigation' },
  { value: 'completed', label: 'Completed' },
]

const CASE_TYPE_OPTIONS = [
  { value: 'corporate', label: 'Corporate' },
  { value: 'labor', label: 'Labor' },
  { value: 'compliance', label: 'Compliance' },
  { value: 'ip', label: 'IP' },
]

const CasesFilters = ({ onFiltersChange }: CasesFiltersProps) => {
  const [filters, setFilters] = useState<FilterState>({
    search: '',
    status: [],
    caseType: [],
    assignedTo: [],
    dateFrom: '',
    dateTo: '',
  })
  
  const handleFilterChange = (key: keyof FilterState, value: any) => {
    const newFilters = { ...filters, [key]: value }
    setFilters(newFilters)
    onFiltersChange(newFilters)
  }
  
  const handleCheckboxChange = (key: 'status' | 'caseType', value: string, checked: boolean) => {
    const currentArray = filters[key] as string[]
    const newArray = checked
      ? [...currentArray, value]
      : currentArray.filter(item => item !== value)
    handleFilterChange(key, newArray)
  }
  
  const handleReset = () => {
    const resetFilters: FilterState = {
      search: '',
      status: [],
      caseType: [],
      assignedTo: [],
      dateFrom: '',
      dateTo: '',
    }
    setFilters(resetFilters)
    onFiltersChange(resetFilters)
  }
  
  return (
    <div className="w-[280px] h-screen bg-secondary border-r border-border flex flex-col overflow-y-auto">
      {/* Search */}
      <div className="p-4 border-b border-border">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-secondary" />
          <Input
            placeholder="Поиск дел..."
            value={filters.search}
            onChange={(e) => handleFilterChange('search', e.target.value)}
            className="pl-10"
          />
        </div>
      </div>
      
      {/* Navigation */}
      <div className="p-4 border-b border-border">
        <div className="space-y-2">
          <button className="w-full text-left px-3 py-2 text-body font-medium text-primary bg-primary bg-opacity-10 rounded-md">
            ✅ Мои дела (5)
          </button>
          <button className="w-full text-left px-3 py-2 text-body text-secondary hover:text-primary hover:bg-tertiary rounded-md transition-colors">
            🤝 Общие (2)
          </button>
          <button className="w-full text-left px-3 py-2 text-body text-secondary hover:text-primary hover:bg-tertiary rounded-md transition-colors">
            🔔 Отмеченные (1)
          </button>
        </div>
      </div>
      
      {/* Filters */}
      <div className="flex-1 p-4 space-y-6">
        {/* Status */}
        <div>
          <h3 className="text-small font-semibold text-secondary mb-3 uppercase">Статус</h3>
          <div className="space-y-2">
            {STATUS_OPTIONS.map((option) => (
              <Checkbox
                key={option.value}
                label={option.label}
                checked={filters.status.includes(option.value)}
                onChange={(e) => handleCheckboxChange('status', option.value, e.target.checked)}
              />
            ))}
          </div>
        </div>
        
        {/* Case Type */}
        <div>
          <h3 className="text-small font-semibold text-secondary mb-3 uppercase">Тип дела</h3>
          <div className="space-y-2">
            {CASE_TYPE_OPTIONS.map((option) => (
              <Checkbox
                key={option.value}
                label={option.label}
                checked={filters.caseType.includes(option.value)}
                onChange={(e) => handleCheckboxChange('caseType', option.value, e.target.checked)}
              />
            ))}
          </div>
        </div>
        
        {/* Assigned To */}
        <div>
          <h3 className="text-small font-semibold text-secondary mb-3 uppercase">Назначено</h3>
          <div className="space-y-2">
            <Checkbox
              label="Вы"
              checked={filters.assignedTo.includes('me')}
              onChange={(e) => {
                const newArray = e.target.checked
                  ? [...filters.assignedTo, 'me']
                  : filters.assignedTo.filter(item => item !== 'me')
                handleFilterChange('assignedTo', newArray)
              }}
            />
            <Checkbox
              label="John Doe"
              checked={filters.assignedTo.includes('john')}
              onChange={(e) => {
                const newArray = e.target.checked
                  ? [...filters.assignedTo, 'john']
                  : filters.assignedTo.filter(item => item !== 'john')
                handleFilterChange('assignedTo', newArray)
              }}
            />
          </div>
        </div>
        
        {/* Date Range */}
        <div>
          <h3 className="text-small font-semibold text-secondary mb-3 uppercase">Последнее обновление</h3>
          <div className="space-y-3">
            <DatePicker
              label="От"
              value={filters.dateFrom}
              onChange={(e) => handleFilterChange('dateFrom', e.target.value)}
            />
            <DatePicker
              label="До"
              value={filters.dateTo}
              onChange={(e) => handleFilterChange('dateTo', e.target.value)}
            />
          </div>
        </div>
      </div>
      
      {/* Actions */}
      <div className="p-4 border-t border-border space-y-2">
        <Button variant="secondary" className="w-full" onClick={handleReset}>
          <X className="w-4 h-4 inline mr-2" />
          Сбросить фильтры
        </Button>
      </div>
    </div>
  )
}

export default CasesFilters
