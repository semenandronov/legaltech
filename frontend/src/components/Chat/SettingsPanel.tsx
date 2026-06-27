import React from 'react'
import { Scale, FileText, Gavel } from 'lucide-react'
import { Switch } from '../UI/switch'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '../UI/tooltip'
import {
  canEnableCourtPractice,
  canEnableLegalResearch,
} from '../../lib/chatInstrumentPolicy'
import { productFeatures } from '../../lib/productFeatures'

interface SettingsPanelProps {
  webSearch: boolean
  legalResearch: boolean
  courtPractice: boolean
  draftMode: boolean
  onWebSearchChange: (value: boolean) => void
  onLegalResearchChange: (value: boolean) => void
  onCourtPracticeChange: (value: boolean) => void
  onDraftModeChange: (value: boolean) => void
  className?: string
  variant?: 'default' | 'compact'
  style?: React.CSSProperties
  hideDraft?: boolean
}

export const SettingsPanel: React.FC<SettingsPanelProps> = ({
  webSearch: _webSearch,
  legalResearch,
  courtPractice,
  draftMode,
  onWebSearchChange: _onWebSearchChange,
  onLegalResearchChange,
  onCourtPracticeChange,
  onDraftModeChange,
  className = '',
  variant = 'default',
  style,
  hideDraft = false,
}) => {
  const handleLegalResearchChange = (checked: boolean) => {
    onLegalResearchChange(checked)
  }

  const handleCourtPracticeChange = (checked: boolean) => {
    onCourtPracticeChange(checked)
  }

  const handleDraftModeChange = (checked: boolean) => {
    onDraftModeChange(checked)
  }

  const allSettings = [
    {
      id: 'legalResearch',
      label: 'Справочник',
      description:
        'Общий правовой справочник (НПА). Только в режиме Ask; при включении Draft отключается.',
      icon: Scale,
      value: legalResearch,
      onChange: handleLegalResearchChange,
      disabled: !canEnableLegalResearch(draftMode),
      enabled: productFeatures.legalCorpus,
    },
    {
      id: 'courtPractice',
      label: 'Суд. практика',
      description:
        'Поиск по загруженной базе судебных актов (КАД). Ответ со ссылками на номера дел.',
      icon: Gavel,
      value: courtPractice,
      onChange: handleCourtPracticeChange,
      disabled: !canEnableCourtPractice(draftMode),
      enabled: productFeatures.courtPractice,
    },
    {
      id: 'draftMode',
      label: 'Режим Draft',
      description:
        'Создание документов через ИИ. При включении справочник и другие инструменты отключаются.',
      icon: FileText,
      value: draftMode,
      onChange: handleDraftModeChange,
      disabled: false,
      enabled: productFeatures.draftMode,
    },
  ].filter((setting) => setting.enabled)

  let settings = hideDraft
    ? allSettings.filter((s) => s.id !== 'draftMode')
    : allSettings
  if (draftMode) {
    settings = settings.filter((s) => s.id === 'draftMode')
  }

  if (settings.length === 0) {
    return null
  }

  return (
    <TooltipProvider delayDuration={200}>
      {variant === 'compact' ? (
        <div className={`flex items-center gap-1 ${className}`} style={style} role="group" aria-label="Настройки чата">
          {settings.map((setting) => {
            const Icon = setting.icon
            const disabled = Boolean(setting.disabled)
            return (
              <Tooltip key={setting.id}>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => !disabled && setting.onChange(!setting.value)}
                    onKeyDown={(e) => {
                      if (disabled) return
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setting.onChange(!setting.value)
                      }
                    }}
                    aria-pressed={setting.value}
                    aria-label={`${setting.label}: ${setting.value ? 'включено' : 'выключено'}`}
                    className={`flex items-center justify-center w-8 h-8 rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 ${
                      disabled
                        ? 'opacity-40 cursor-not-allowed'
                        : setting.value
                          ? 'bg-secondary text-accent-muted border border-border'
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
                    {disabled && (
                      <p className="text-xs text-amber-200 mt-1">Недоступно в режиме Draft.</p>
                    )}
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
            const disabled = Boolean(setting.disabled)
            return (
              <Tooltip key={setting.id}>
                <TooltipTrigger asChild>
                  <div
                    className={`flex items-center gap-2 group ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
                  >
                    <Icon
                      className={`w-5 h-5 transition-colors ${
                        setting.value ? 'text-accent-muted' : 'text-gray-400 group-hover:text-gray-600'
                      }`}
                    />
                    <Switch
                      checked={setting.value}
                      onCheckedChange={setting.onChange}
                      disabled={disabled}
                      className="scale-90"
                    />
                  </div>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs z-50">
                  <div>
                    <p className="font-semibold text-sm mb-1">{setting.label}</p>
                    <p className="text-xs text-gray-300 whitespace-normal">{setting.description}</p>
                    {disabled && (
                      <p className="text-xs text-amber-200 mt-1">Недоступно в режиме Draft.</p>
                    )}
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
