import React, { useState } from 'react'
import { Search, Brain, Scale, ChevronUp, ChevronDown } from 'lucide-react'
import { Switch } from '../UI/switch'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '../UI/tooltip'

interface SettingsPanelProps {
  webSearch: boolean
  deepThink: boolean
  legalResearch: boolean
  onWebSearchChange: (value: boolean) => void
  onDeepThinkChange: (value: boolean) => void
  onLegalResearchChange: (value: boolean) => void
  className?: string
}

export const SettingsPanel: React.FC<SettingsPanelProps> = ({
  webSearch,
  deepThink,
  legalResearch,
  onWebSearchChange,
  onDeepThinkChange,
  onLegalResearchChange,
  className = '',
}) => {
  const [isExpanded, setIsExpanded] = useState(false)

  const settings = [
    {
      id: 'webSearch',
      label: 'Веб-поиск',
      description: 'Используйте веб для глубокого исследования любой темы',
      icon: Search,
      value: webSearch,
      onChange: onWebSearchChange,
      impact: 'Увеличивает время ответа на 5-10 секунд',
    },
    {
      id: 'deepThink',
      label: 'Глубокое размышление',
      description: 'Используйте более глубокий анализ для сложных вопросов',
      icon: Brain,
      value: deepThink,
      onChange: onDeepThinkChange,
      impact: 'Использует более мощную модель, увеличивает время ответа',
    },
    {
      id: 'legalResearch',
      label: 'Юридическое исследование',
      description: 'Найдите ответы на свои вопросы в курируемых юридических источниках',
      icon: Scale,
      value: legalResearch,
      onChange: onLegalResearchChange,
      impact: 'Early access - экспериментальная функция',
      badge: 'Early',
    },
  ]

  const activeCount = settings.filter(s => s.value).length

  return (
    <TooltipProvider>
      <div className={`bg-white border-t border-gray-200 ${className}`}>
        {/* Compact view */}
        <div className="px-6 py-2">
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex items-center justify-between w-full text-sm text-gray-600 hover:text-gray-900 transition-colors"
          >
            <div className="flex items-center gap-2">
              <span className="font-medium">
                Настройки функций {activeCount > 0 && `(${activeCount} активно)`}
              </span>
            </div>
            {isExpanded ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
          </button>
        </div>

        {/* Expanded view */}
        {isExpanded && (
          <div className="px-6 pb-4 space-y-3 border-t border-gray-100">
            {settings.map((setting) => {
              const Icon = setting.icon
              return (
                <div
                  key={setting.id}
                  className="flex items-center justify-between p-3 rounded-lg hover:bg-gray-50 transition-colors"
                >
                  <div className="flex items-center gap-3 flex-1">
                    <div className="p-2 rounded-lg bg-gray-100">
                      <Icon className="w-4 h-4 text-gray-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-900">
                          {setting.label}
                        </span>
                        {setting.badge && (
                          <span className="px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 rounded">
                            {setting.badge}
                          </span>
                        )}
                      </div>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <p className="text-xs text-gray-600 truncate mt-0.5">
                            {setting.description}
                          </p>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p className="max-w-xs">{setting.description}</p>
                          {setting.impact && (
                            <p className="text-xs text-gray-400 mt-1">{setting.impact}</p>
                          )}
                        </TooltipContent>
                      </Tooltip>
                    </div>
                  </div>
                  <Switch
                    checked={setting.value}
                    onCheckedChange={setting.onChange}
                    className="ml-4"
                  />
                </div>
              )
            })}
          </div>
        )}

        {/* Compact indicators when collapsed */}
        {!isExpanded && activeCount > 0 && (
          <div className="px-6 pb-2">
            <div className="flex items-center gap-2 flex-wrap">
              {settings
                .filter(s => s.value)
                .map((setting) => {
                  const Icon = setting.icon
                  return (
                    <div
                      key={setting.id}
                      className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-blue-50 text-blue-700 text-xs"
                      title={setting.label}
                    >
                      <Icon className="w-3 h-3" />
                      <span className="font-medium">{setting.label}</span>
                    </div>
                  )
                })}
            </div>
          </div>
        )}
      </div>
    </TooltipProvider>
  )
}


