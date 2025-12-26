import { useState } from 'react'
import { Badge } from '@/components/UI/Badge'
import { Button } from '@/components/UI/Button'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/UI/popover'
import { Checkbox } from '@/components/UI/Checkbox'
import { ScrollArea } from '@/components/UI/scroll-area'
import { 
  Globe, 
  Database, 
  FileText, 
  Building2,
  Plus,
  Check,
  X
} from 'lucide-react'
import { cn } from '@/lib/utils'

export interface DataSource {
  id: string
  name: string
  description: string
  icon: 'globe' | 'database' | 'file' | 'building' | 'custom'
  enabled: boolean
  configured: boolean
  category: 'vault' | 'web' | 'legal' | 'custom'
}

interface SourceSelectorProps {
  sources: DataSource[]
  selectedSources: string[]
  onSourcesChange: (sources: string[]) => void
  className?: string
}

const SOURCE_ICONS = {
  globe: Globe,
  database: Database,
  file: FileText,
  building: Building2,
  custom: Database,
}

const CATEGORY_LABELS = {
  vault: 'Документы',
  web: 'Интернет',
  legal: 'Правовые базы',
  custom: 'Кастомные',
}

const CATEGORY_COLORS = {
  vault: 'bg-blue-500/10 text-blue-600 border-blue-500/20',
  web: 'bg-green-500/10 text-green-600 border-green-500/20',
  legal: 'bg-purple-500/10 text-purple-600 border-purple-500/20',
  custom: 'bg-orange-500/10 text-orange-600 border-orange-500/20',
}

// Default available sources
export const DEFAULT_SOURCES: DataSource[] = [
  {
    id: 'vault',
    name: 'Документы дела',
    description: 'Поиск в загруженных документах',
    icon: 'file',
    enabled: true,
    configured: true,
    category: 'vault',
  },
  {
    id: 'web_search',
    name: 'Веб-поиск',
    description: 'Поиск в интернете',
    icon: 'globe',
    enabled: true,
    configured: true,
    category: 'web',
  },
  {
    id: 'garant',
    name: 'Гарант',
    description: 'Правовая информационная система',
    icon: 'building',
    enabled: false,
    configured: false,
    category: 'legal',
  },
  {
    id: 'consultant_plus',
    name: 'КонсультантПлюс',
    description: 'Справочная правовая система',
    icon: 'building',
    enabled: false,
    configured: false,
    category: 'legal',
  },
]

export function SourceSelector({
  sources = DEFAULT_SOURCES,
  selectedSources,
  onSourcesChange,
  className,
}: SourceSelectorProps) {
  const [isOpen, setIsOpen] = useState(false)

  const toggleSource = (sourceId: string) => {
    const source = sources.find(s => s.id === sourceId)
    if (!source || !source.configured) return

    if (selectedSources.includes(sourceId)) {
      // Don't allow deselecting vault
      if (sourceId === 'vault') return
      onSourcesChange(selectedSources.filter(id => id !== sourceId))
    } else {
      onSourcesChange([...selectedSources, sourceId])
    }
  }

  const selectedSourcesData = sources.filter(s => selectedSources.includes(s.id))
  const groupedSources = sources.reduce((acc, source) => {
    if (!acc[source.category]) {
      acc[source.category] = []
    }
    acc[source.category].push(source)
    return acc
  }, {} as Record<string, DataSource[]>)

  return (
    <div className={cn("flex flex-wrap gap-2", className)}>
      {/* Selected sources as badges */}
      {selectedSourcesData.map((source) => {
        const Icon = SOURCE_ICONS[source.icon]
        return (
          <Badge
            key={source.id}
            variant="outline"
            className={cn(
              "flex items-center gap-1.5 px-2 py-1 cursor-pointer hover:bg-muted/50 transition-colors",
              CATEGORY_COLORS[source.category]
            )}
            onClick={() => toggleSource(source.id)}
          >
            <Icon className="h-3 w-3" />
            <span>{source.name}</span>
            {source.id !== 'vault' && (
              <X className="h-3 w-3 ml-1 opacity-50 hover:opacity-100" />
            )}
          </Badge>
        )
      })}

      {/* Add source button */}
      <Popover open={isOpen} onOpenChange={setIsOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs gap-1"
          >
            <Plus className="h-3 w-3" />
            Источники
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-80 p-0" align="start">
          <div className="p-3 border-b">
            <h4 className="font-medium text-sm">Источники данных</h4>
            <p className="text-xs text-muted-foreground mt-1">
              Выберите источники для поиска информации
            </p>
          </div>
          <ScrollArea className="max-h-[300px]">
            <div className="p-2">
              {Object.entries(groupedSources).map(([category, categorySources]) => (
                <div key={category} className="mb-3">
                  <div className="text-xs font-medium text-muted-foreground px-2 py-1">
                    {CATEGORY_LABELS[category as keyof typeof CATEGORY_LABELS]}
                  </div>
                  {categorySources.map((source) => {
                    const Icon = SOURCE_ICONS[source.icon]
                    const isSelected = selectedSources.includes(source.id)
                    const isDisabled = !source.configured || source.id === 'vault'
                    
                    return (
                      <div
                        key={source.id}
                        className={cn(
                          "flex items-center gap-3 px-2 py-2 rounded-md cursor-pointer",
                          "hover:bg-muted/50 transition-colors",
                          isDisabled && "opacity-50 cursor-not-allowed"
                        )}
                        onClick={() => !isDisabled && toggleSource(source.id)}
                      >
                        <Checkbox
                          checked={isSelected}
                          disabled={isDisabled}
                          className="data-[state=checked]:bg-primary"
                        />
                        <div className={cn(
                          "p-1.5 rounded",
                          CATEGORY_COLORS[source.category]
                        )}>
                          <Icon className="h-3.5 w-3.5" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium flex items-center gap-2">
                            {source.name}
                            {!source.configured && (
                              <Badge variant="outline" className="text-[10px] px-1 py-0">
                                Не настроен
                              </Badge>
                            )}
                          </div>
                          <div className="text-xs text-muted-foreground truncate">
                            {source.description}
                          </div>
                        </div>
                        {isSelected && source.id !== 'vault' && (
                          <Check className="h-4 w-4 text-primary" />
                        )}
                      </div>
                    )
                  })}
                </div>
              ))}
            </div>
          </ScrollArea>
        </PopoverContent>
      </Popover>
    </div>
  )
}

export default SourceSelector

