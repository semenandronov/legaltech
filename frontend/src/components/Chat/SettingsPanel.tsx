import React from 'react'
import { Brain, Scale, FileText } from 'lucide-react'
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
  draftMode: boolean
  onWebSearchChange: (value: boolean) => void
  onDeepThinkChange: (value: boolean) => void
  onLegalResearchChange: (value: boolean) => void
  onDraftModeChange: (value: boolean) => void
  className?: string
  variant?: 'default' | 'compact'
  style?: React.CSSProperties
}

export const SettingsPanel: React.FC<SettingsPanelProps> = ({
  webSearch: _webSearch, // Неиспользуется, но оставлен для совместимости интерфейса
  deepThink,
  legalResearch,
  draftMode,
  onWebSearchChange,
  onDeepThinkChange,
  onLegalResearchChange,
  onDraftModeChange,
  className = '',
  variant = 'default',
  style,
}) => {
  // Обработчик для глубокого размышления - выключает другие функции
  const handleDeepThinkChange = (checked: boolean) => {
    if (checked) {
      // Если включаем глубокое размышление, выключаем остальные
      onLegalResearchChange(false)
      onWebSearchChange(false)
      onDraftModeChange(false)
    }
    onDeepThinkChange(checked)
  }

  // Обработчик для ГАРАНТ - выключает другие функции
  const handleLegalResearchChange = (checked: boolean) => {
    if (checked) {
      // Если включаем ГАРАНТ, выключаем остальные
      onDeepThinkChange(false)
      onWebSearchChange(false)
      onDraftModeChange(false)
    }
    onLegalResearchChange(checked)
  }

  // Обработчик для режима Draft - выключает другие функции
  const handleDraftModeChange = (checked: boolean) => {
    if (checked) {
      // Если включаем режим Draft, выключаем остальные
      onDeepThinkChange(false)
      onLegalResearchChange(false)
      onWebSearchChange(false)
    }
    onDraftModeChange(checked)
  }

  const settings = [
    // Веб-поиск отключен - убран из списка
    {
      id: 'deepThink',
      label: 'Глубокое размышление',
      description: 'Используйте более глубокий анализ для сложных вопросов. Использует более мощную модель, увеличивает время ответа.',
      icon: Brain,
      value: deepThink,
      onChange: handleDeepThinkChange,
    },
    {
      id: 'legalResearch',
      label: 'ГАРАНТ',
      description: 'Поиск в базе ГАРАНТ: законы, кодексы, судебные решения, правовые позиции. ИИ анализирует результаты и отвечает на ваш вопрос с учетом найденных документов.',
      icon: Scale,
      value: legalResearch,
      onChange: handleLegalResearchChange,
    },
    {
      id: 'draftMode',
      label: 'Режим Draft',
      description: 'Создание документов через ИИ. Опишите нужный документ, и ИИ создаст его для редактирования в редакторе.',
      icon: FileText,
      value: draftMode,
      onChange: handleDraftModeChange,
    },
  ]

  return (
    <TooltipProvider delayDuration={200}>
      {variant === 'compact' ? (
        <div className={`flex items-center gap-1 ${className}`} style={style} role="group" aria-label="Настройки чата">
          {settings.map((setting) => {
            const Icon = setting.icon
            return (
              <Tooltip key={setting.id}>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={() => setting.onChange(!setting.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setting.onChange(!setting.value)
                      }
                    }}
                    aria-pressed={setting.value}
                    aria-label={`${setting.label}: ${setting.value ? 'включено' : 'выключено'}`}
                    className={`flex items-center justify-center w-8 h-8 rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 ${
                      setting.value
                        ? 'bg-blue-50 text-blue-600 border border-blue-200'
                        : 'bg-transparent text-gray-400 hover:text-gray-600 hover:bg-gray-100'
                    }`}
                  >
                    <Icon className="w-4 h-4" aria-hidden="true" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs z-50">
                  <div>
                    <p className="font-semibold text-sm mb-1">{setting.label}</p>
                    <p className="text-xs text-gray-300 whitespace-normal">{setting.description}</p>
                  </div>
                </TooltipContent>
              </Tooltip>
            )
          })}
        </div>
      ) : (
        <div className={`flex items-center gap-6 px-4 py-2.5 bg-gray-50 border-t border-gray-200 ${className}`} style={style}>
          {settings.map((setting) => {
            const Icon = setting.icon
            return (
              <Tooltip key={setting.id}>
                <TooltipTrigger asChild>
                  <div className="flex items-center gap-2 cursor-pointer group">
                    <Icon 
                      className={`w-5 h-5 transition-colors ${
                        setting.value 
                          ? 'text-blue-600' 
                          : 'text-gray-400 group-hover:text-gray-600'
                      }`} 
                    />
                    <Switch
                      checked={setting.value}
                      onCheckedChange={setting.onChange}
                      className="scale-90"
                    />
                  </div>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs z-50">
                  <div>
                    <p className="font-semibold text-sm mb-1">{setting.label}</p>
                    <p className="text-xs text-gray-300 whitespace-normal">{setting.description}</p>
                  </div>
                </TooltipContent>
              </Tooltip>
            )
          })}
        </div>
      )}
    </TooltipProvider>
  )
}
