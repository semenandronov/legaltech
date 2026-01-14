import React from 'react'
import { Brain, Scale } from 'lucide-react'
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
  webSearch: _webSearch, // Неиспользуется, но оставлен для совместимости интерфейса
  deepThink,
  legalResearch,
  onWebSearchChange,
  onDeepThinkChange,
  onLegalResearchChange,
  className = '',
}) => {
  // Обработчик для глубокого размышления - выключает другие функции
  const handleDeepThinkChange = (checked: boolean) => {
    if (checked) {
      // Если включаем глубокое размышление, выключаем остальные
      onLegalResearchChange(false)
      onWebSearchChange(false)
    }
    onDeepThinkChange(checked)
  }

  // Обработчик для ГАРАНТ - выключает другие функции
  const handleLegalResearchChange = (checked: boolean) => {
    if (checked) {
      // Если включаем ГАРАНТ, выключаем остальные
      onDeepThinkChange(false)
      onWebSearchChange(false)
    }
    onLegalResearchChange(checked)
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
  ]

  return (
    <TooltipProvider delayDuration={200}>
      <div className={`flex items-center gap-6 px-4 py-2.5 bg-gray-50 border-t border-gray-200 ${className}`}>
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
    </TooltipProvider>
  )
}
