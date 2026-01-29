import React from 'react'
import {
  PromptInput,
  PromptInputBody,
  PromptInputTextarea,
  PromptInputSubmit,
} from '../ai-elements/prompt-input'
import { SettingsPanel } from '../Chat/SettingsPanel'

interface EditorPromptInputProps {
  onSubmit: (message: { text: string; files: any[] }, event: React.FormEvent<HTMLFormElement>) => void | Promise<void>
  isLoading: boolean
  documentId?: string
  deepThink: boolean
  legalResearch: boolean
  onDeepThinkChange: (value: boolean) => void
  onLegalResearchChange: (value: boolean) => void
  placeholder?: string
}

export const EditorPromptInput = ({
  onSubmit,
  isLoading,
  documentId,
  deepThink,
  legalResearch,
  onDeepThinkChange,
  onLegalResearchChange,
  placeholder = "Задайте вопрос о документе…"
}: EditorPromptInputProps) => {
  return (
    <div 
      className="w-full max-w-4xl mx-auto"
      style={{ 
        display: 'flex', 
        flexDirection: 'column', 
        gap: 'var(--space-4)' 
      }}
    >
      <PromptInput
        onSubmit={onSubmit}
        className="w-full [&_form_input-group]:border [&_form_input-group]:border-border [&_form_input-group]:rounded-lg [&_form_input-group]:bg-bg-elevated [&_form_input-group]:focus-within:border-border-strong [&_form_input-group]:transition-all [&_form_input-group]:hover:border-border-strong"
        style={{
          '--input-border': 'var(--color-border)',
          '--input-bg': 'var(--color-bg-elevated)',
          '--input-focus-border': 'var(--color-border-strong)',
        } as React.CSSProperties}
      >
        <PromptInputBody>
          <div className="flex items-end gap-2 w-full">
            <div className="flex-1 relative">
              <PromptInputTextarea 
                placeholder={placeholder}
                className="w-full min-h-[120px] max-h-[300px] text-base py-4 px-4 resize-none focus:outline-none leading-relaxed overflow-y-auto"
                style={{
                  color: 'var(--color-text-primary)',
                  backgroundColor: 'transparent',
                  padding: 'var(--space-4)',
                }}
              />
            </div>
          </div>
          <PromptInputSubmit 
            variant="default"
            className="rounded-md h-10 w-10 p-0 flex items-center justify-center shrink-0 transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              backgroundColor: 'var(--color-accent)',
              color: 'var(--color-bg-primary)',
            }}
            disabled={isLoading || !documentId}
            status={isLoading ? "submitted" : undefined}
            aria-label="Отправить сообщение"
          />
        </PromptInputBody>
      </PromptInput>

      {/* Compact settings panel */}
      <SettingsPanel
        webSearch={false}
        deepThink={deepThink}
        legalResearch={legalResearch}
        draftMode={false}
        onWebSearchChange={() => {}}
        onDeepThinkChange={onDeepThinkChange}
        onLegalResearchChange={onLegalResearchChange}
        onDraftModeChange={() => {}}
      />
    </div>
  )
}

