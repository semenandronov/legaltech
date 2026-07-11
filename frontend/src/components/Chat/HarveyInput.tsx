import { useCallback, useEffect, useRef, useState, type ComponentType } from 'react'
import {
  AlignJustify,
  ArrowRight,
  BookOpen,
  FileText,
  FolderOpen,
  Gavel,
  Loader2,
  Mic,
  MicOff,
  Plus,
  SlidersHorizontal,
  Sparkles,
  Square,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import type { LegalCorpusFileRow } from '@/services/api'
import {
  canEnableCourtPractice,
  canEnableLegalResearch,
  canSelectDraftMode,
} from '@/lib/chatInstrumentPolicy'
import {
  chatHasActiveInstruments,
  chatInstrumentControlsEnabled,
  productFeatures,
} from '@/lib/productFeatures'
import { useClickOutside } from '@/hooks/useClickOutside'
import { useSpeechRecognition } from '@/hooks/useSpeechRecognition'
import { CHAT_FILE_ACCEPT } from './chatInputConstants'
import { LEGAL_PROMPTS } from './legalPrompts'

export interface HarveyFileContext {
  file_id?: string
  filename: string
  file_type?: string
  text: string
  charCount: number
}

export interface HarveySelectedFile {
  id: string
  filename: string
  file_type?: string
}

interface HarveyInputCoreProps {
  appearance?: 'default' | 'mike'
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  fileContexts: HarveyFileContext[]
  uploadingFiles: string[]
  onAddFiles: (files: File[]) => void
  onRemoveContext: (index: number) => void
  isStreaming: boolean
  isDraftMode: boolean
  onSetDraftMode: (draft: boolean) => void
  selectedCaseFiles: HarveySelectedFile[]
  onRemoveCaseFile: (id: string) => void
  placeholder?: string
  useLegalCorpus: boolean
  onUseLegalCorpusChange: (value: boolean) => void
  useCourtPractice: boolean
  onUseCourtPracticeChange: (value: boolean) => void
}

export type HarveyInputProps =
  | (HarveyInputCoreProps & {
      variant: 'global'
      onOpenCasePicker: () => void
      isLegalCorpusUploader: boolean
      corpusFiles: LegalCorpusFileRow[]
      corpusUploading: boolean
      onCorpusFilesSelected: (files: File[]) => void
      onDeleteCorpusFile: (corpusFileId: string) => void
    })
  | (HarveyInputCoreProps & {
      variant: 'case'
      onOpenCaseFilePicker: () => void
      isImprovingPrompt?: boolean
      onImprovePrompt?: () => void
    })

function toolBtnClass(...parts: Array<string | false | undefined>) {
  return parts.filter(Boolean).join(' ')
}

function MikeInstrumentToggle({
  active,
  disabled,
  onClick,
  icon: Icon,
  label,
  title,
}: {
  active: boolean
  disabled?: boolean
  onClick: () => void
  icon: ComponentType<{ className?: string }>
  label: string
  title?: string
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      title={title}
      className={toolBtnClass(
        'ws-mike-instrument-btn',
        active && 'ws-mike-instrument-btn--active',
      )}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span>{label}</span>
    </button>
  )
}

function HarveyInputFilePills({
  uploadingFiles,
  fileContexts,
  selectedCaseFiles,
  onRemoveContext,
  onRemoveCaseFile,
  caseFileIcon,
}: {
  uploadingFiles: string[]
  fileContexts: HarveyFileContext[]
  selectedCaseFiles: HarveySelectedFile[]
  onRemoveContext: (index: number) => void
  onRemoveCaseFile: (id: string) => void
  caseFileIcon: 'file' | 'folder'
}) {
  const hasFiles =
    fileContexts.length > 0 || uploadingFiles.length > 0 || selectedCaseFiles.length > 0

  if (!hasFiles) return null

  const CaseIcon = caseFileIcon === 'folder' ? FolderOpen : FileText

  return (
    <div className="px-4 pb-2 flex flex-wrap gap-2">
      {uploadingFiles.map((name) => (
        <div key={`uploading-${name}`} className="ws-file-pill ws-file-pill--link">
          <Loader2 className="w-3 h-3 animate-spin" />
          <span className="max-w-[140px] truncate">{name}</span>
        </div>
      ))}
      {fileContexts.map((fileContext, index) => (
        <div key={`ctx-${index}`} className="ws-file-pill">
          <FileText className="w-3 h-3" style={{ color: 'var(--color-success)' }} />
          <span className="max-w-[140px] truncate">{fileContext.filename}</span>
          <span style={{ color: 'var(--color-text-muted)' }}>
            {Math.round(fileContext.charCount / 1000)}k
          </span>
          <button type="button" onClick={() => onRemoveContext(index)} className="ws-file-pill-remove">
            <X className="w-3 h-3" />
          </button>
        </div>
      ))}
      {selectedCaseFiles.map((file) => (
        <div key={`case-${file.id}`} className="ws-file-pill ws-file-pill--accent">
          <CaseIcon className="w-3 h-3" />
          <span className="max-w-[140px] truncate">{file.filename}</span>
          <button type="button" onClick={() => onRemoveCaseFile(file.id)} className="ws-file-pill-remove">
            <X className="w-3 h-3" />
          </button>
        </div>
      ))}
    </div>
  )
}

function HarveyInputSettingsMenu({
  variant,
  isOpen,
  onClose,
  isDraftMode,
  onSetDraftMode,
  useLegalCorpus,
  onUseLegalCorpusChange,
  useCourtPractice,
  onUseCourtPracticeChange,
  isStreaming,
  isLegalCorpusUploader,
  corpusFiles,
  corpusUploading,
  onCorpusFilesSelected,
  onDeleteCorpusFile,
}: {
  variant: 'global' | 'case'
  isOpen: boolean
  onClose: () => void
  isDraftMode: boolean
  onSetDraftMode: (draft: boolean) => void
  useLegalCorpus: boolean
  onUseLegalCorpusChange: (value: boolean) => void
  useCourtPractice: boolean
  onUseCourtPracticeChange: (value: boolean) => void
  isStreaming: boolean
  isLegalCorpusUploader: boolean
  corpusFiles: LegalCorpusFileRow[]
  corpusUploading: boolean
  onCorpusFilesSelected: (files: File[]) => void
  onDeleteCorpusFile: (corpusFileId: string) => void
}) {
  const corpusFileInputRef = useRef<HTMLInputElement>(null)

  if (!isOpen) return null

  const showAskDraftMode = productFeatures.draftMode
  const showLegalCorpusControl = productFeatures.legalCorpus && variant === 'global'
  const showCourtPracticeControl = productFeatures.courtPractice
  const showInstrumentToggles =
    !isDraftMode && (showLegalCorpusControl || showCourtPracticeControl)
  const showCorpusUploader = variant === 'global' && showLegalCorpusControl && isLegalCorpusUploader

  const modeSection = showAskDraftMode ? (
    <>
      <div className="ws-dropdown-header">Режим</div>
      <button
        type="button"
        onClick={() => { onSetDraftMode(false); onClose() }}
        className={toolBtnClass('ws-dropdown-item', !isDraftMode && 'ws-dropdown-item--selected')}
      >
        <span
          className="w-2 h-2 rounded-full flex-shrink-0"
          style={{
            backgroundColor: !isDraftMode ? 'var(--color-text-primary)' : 'var(--color-border-strong)',
          }}
        />
        Ask
      </button>
      <button
        type="button"
        disabled={!canSelectDraftMode(useLegalCorpus, useCourtPractice)}
        onClick={() => {
          if (!canSelectDraftMode(useLegalCorpus, useCourtPractice)) return
          onSetDraftMode(true)
          onClose()
        }}
        className={toolBtnClass('ws-dropdown-item', isDraftMode && 'ws-dropdown-item--selected')}
        title={useLegalCorpus || useCourtPractice ? 'Недоступно при включённых инструментах' : undefined}
        style={{ color: isDraftMode ? 'var(--color-link)' : undefined }}
      >
        <span
          className="w-2 h-2 rounded-full flex-shrink-0"
          style={{
            backgroundColor: isDraftMode ? 'var(--color-link)' : 'var(--color-border-strong)',
          }}
        />
        Draft
      </button>
    </>
  ) : null

  const globalInstrumentSection = showInstrumentToggles ? (
    <>
      <div className="ws-dropdown-header">Справочник</div>
      {showLegalCorpusControl && (
        <button
          type="button"
          disabled={!canEnableLegalResearch(isDraftMode) || useCourtPractice}
          onClick={() => onUseLegalCorpusChange(!useLegalCorpus)}
          className="ws-dropdown-item"
          style={{ color: useLegalCorpus ? 'var(--color-success)' : undefined }}
        >
          <BookOpen
            className="w-4 h-4 flex-shrink-0"
            style={{ color: useLegalCorpus ? 'var(--color-success)' : 'var(--color-text-muted)' }}
          />
          <span className="flex-1 min-w-0">Справочник</span>
          <span
            className="w-2 h-2 rounded-full flex-shrink-0"
            style={{
              backgroundColor: useLegalCorpus ? 'var(--color-success)' : 'var(--color-border-strong)',
            }}
          />
        </button>
      )}
      {showCourtPracticeControl && (
        <button
          type="button"
          disabled={!canEnableCourtPractice(isDraftMode) || useLegalCorpus}
          onClick={() => onUseCourtPracticeChange(!useCourtPractice)}
          className="ws-dropdown-item"
          style={{ color: useCourtPractice ? 'var(--color-success)' : undefined }}
        >
          <Gavel
            className="w-4 h-4 flex-shrink-0"
            style={{ color: useCourtPractice ? 'var(--color-success)' : 'var(--color-text-muted)' }}
          />
          <span className="flex-1 min-w-0">Суд. практика</span>
          <span
            className="w-2 h-2 rounded-full flex-shrink-0"
            style={{
              backgroundColor: useCourtPractice ? 'var(--color-success)' : 'var(--color-border-strong)',
            }}
          />
        </button>
      )}
    </>
  ) : null

  const caseInstrumentSection = showInstrumentToggles ? (
    <>
      <div className="ws-dropdown-header">Инструменты</div>
      {showLegalCorpusControl && (
        <button
          type="button"
          disabled={!canEnableLegalResearch(isDraftMode) || useCourtPractice}
          onClick={() => onUseLegalCorpusChange(!useLegalCorpus)}
          className="ws-dropdown-item"
          title={isDraftMode ? 'Недоступно в режиме Draft' : undefined}
          style={{
            color: useLegalCorpus ? 'var(--color-success)' : undefined,
            backgroundColor: useLegalCorpus ? 'var(--color-success-bg)' : undefined,
          }}
        >
          <span
            className="w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0"
            style={{
              borderColor: useLegalCorpus ? 'var(--color-success)' : 'var(--color-border-strong)',
              backgroundColor: useLegalCorpus ? 'var(--color-success)' : 'transparent',
            }}
          >
            {useLegalCorpus && <span className="text-white" style={{ fontSize: '9px' }}>✓</span>}
          </span>
          Справочник
        </button>
      )}
      {showCourtPracticeControl && (
        <button
          type="button"
          disabled={!canEnableCourtPractice(isDraftMode) || (variant === 'global' && useLegalCorpus)}
          onClick={() => onUseCourtPracticeChange(!useCourtPractice)}
          className="ws-dropdown-item"
          title={isDraftMode ? 'Недоступно в режиме Draft' : undefined}
          style={{
            color: useCourtPractice ? 'var(--color-success)' : undefined,
            backgroundColor: useCourtPractice ? 'var(--color-success-bg)' : undefined,
          }}
        >
          <span
            className="w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0"
            style={{
              borderColor: useCourtPractice ? 'var(--color-success)' : 'var(--color-border-strong)',
              backgroundColor: useCourtPractice ? 'var(--color-success)' : 'transparent',
            }}
          >
            {useCourtPractice && <span className="text-white" style={{ fontSize: '9px' }}>✓</span>}
          </span>
          Суд. практика
        </button>
      )}
    </>
  ) : null

  const corpusUploaderSection = showCorpusUploader ? (
    <>
      <div className="ws-dropdown-header">Загрузка справочника (админ)</div>
      <div
        className="max-h-36 overflow-y-auto px-2 py-1.5 border-b"
        style={{ borderColor: 'var(--color-border-subtle)' }}
      >
        {corpusFiles.length === 0 ? (
          <p className="text-xs px-1" style={{ color: 'var(--color-text-muted)' }}>Файлов пока нет</p>
        ) : (
          corpusFiles.map((row) => (
            <div
              key={row.corpus_file_id}
              className="flex items-center gap-1 py-1 text-xs"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <span className="flex-1 min-w-0 truncate" title={row.source_filename}>
                {row.source_filename}
              </span>
              <span className="flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
                {row.chunk_count}
              </span>
              <button
                type="button"
                onClick={() => onDeleteCorpusFile(row.corpus_file_id)}
                disabled={corpusUploading}
                className="ws-file-pill-remove p-0.5"
                aria-label={`Удалить ${row.source_filename} из справочника`}
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))
        )}
      </div>
      <div className="px-2 py-2 flex items-center gap-2">
        <input
          ref={corpusFileInputRef}
          type="file"
          multiple
          accept={CHAT_FILE_ACCEPT}
          className="hidden"
          onChange={(e) => {
            const list = e.target.files
            if (list?.length) onCorpusFilesSelected(Array.from(list))
            e.target.value = ''
          }}
        />
        <button
          type="button"
          disabled={corpusUploading || isStreaming}
          onClick={() => corpusFileInputRef.current?.click()}
          className="ws-btn ws-btn-secondary text-xs"
          style={{ padding: '0.25rem 0.5rem', minHeight: 'auto' }}
        >
          {corpusUploading ? 'Индексация…' : 'Добавить файлы'}
        </button>
        {corpusUploading && (
          <Loader2 className="w-4 h-4 animate-spin" style={{ color: 'var(--color-success)' }} />
        )}
      </div>
    </>
  ) : null

  return (
    <div
      className="ws-dropdown"
      style={{
        minWidth: variant === 'global' ? '240px' : '160px',
        maxWidth: variant === 'global' ? 'min(92vw, 320px)' : undefined,
      }}
    >
      {variant === 'global' ? (
        <>
          {globalInstrumentSection}
          {corpusUploaderSection}
          {modeSection}
        </>
      ) : (
        <>
          {modeSection}
          {caseInstrumentSection}
        </>
      )}
    </div>
  )
}

export function HarveyInput(props: HarveyInputProps) {
  const {
    appearance = 'default',
    value,
    onChange,
    onSubmit,
    fileContexts,
    uploadingFiles,
    onAddFiles,
    onRemoveContext,
    isStreaming,
    isDraftMode,
    onSetDraftMode,
    selectedCaseFiles,
    onRemoveCaseFile,
    placeholder,
    useLegalCorpus,
    onUseLegalCorpusChange,
    useCourtPractice,
    onUseCourtPracticeChange,
    variant,
  } = props

  const isMike = appearance === 'mike'
  const isMikeCase = isMike && variant === 'case'
  const isMikeGlobal = isMike && variant === 'global'
  const isMikeChrome = isMikeCase || isMikeGlobal

  const resolvedPlaceholder =
    placeholder ??
    (isMike
      ? 'Задайте вопрос о документах...'
      : variant === 'case'
        ? 'Спросите что угодно о деле...'
        : 'Спросите что угодно...')

  const isImprovingPrompt = variant === 'case' ? (props.isImprovingPrompt ?? false) : false
  const onImprovePrompt = variant === 'case' ? props.onImprovePrompt : undefined

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const settingsRef = useRef<HTMLDivElement>(null)
  const filesDropdownRef = useRef<HTMLDivElement>(null)
  const promptsRef = useRef<HTMLDivElement>(null)

  const [settingsOpen, setSettingsOpen] = useState(false)
  const [filesDropdownOpen, setFilesDropdownOpen] = useState(false)
  const [promptsOpen, setPromptsOpen] = useState(false)

  const appendTranscript = useCallback(
    (text: string) => onChange(value ? `${value} ${text}` : text),
    [onChange, value],
  )
  const { isRecording, toggleRecording } = useSpeechRecognition(appendTranscript)

  useClickOutside(settingsRef, settingsOpen, () => setSettingsOpen(false))
  useClickOutside(promptsRef, promptsOpen, () => setPromptsOpen(false))
  useClickOutside(filesDropdownRef, filesDropdownOpen, () => setFilesDropdownOpen(false))

  useEffect(() => {
    const element = textareaRef.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`
  }, [value])

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      if (value.trim() && !isStreaming && !isImprovingPrompt) onSubmit()
    }
  }

  const showInstrumentControls = chatInstrumentControlsEnabled()
  const hasActiveSettings = chatHasActiveInstruments({
    draftMode: isDraftMode,
    legalResearch: useLegalCorpus,
    courtPractice: useCourtPractice,
  })

  const handleFileInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.files) {
      onAddFiles(Array.from(event.target.files))
      event.target.value = ''
    }
  }

  const attachedFileCount =
    fileContexts.length + selectedCaseFiles.length + uploadingFiles.length

  const caseFilesDropdown = (
    <div ref={filesDropdownRef} className="relative flex-shrink-0">
      <button
        type="button"
        onClick={() => setFilesDropdownOpen((open) => !open)}
        className={toolBtnClass(
          'ws-input-tool-btn',
          attachedFileCount > 0 && 'ws-input-tool-btn--accent',
          filesDropdownOpen && 'ws-input-tool-btn--active',
        )}
      >
        <Plus className="w-3.5 h-3.5" />
        Файлы
        {attachedFileCount > 0 && (
          <span className="ws-input-count-badge ws-input-count-badge--soft">
            {attachedFileCount}
          </span>
        )}
      </button>
      {filesDropdownOpen && (
        <div className="ws-dropdown" style={{ minWidth: '210px' }}>
          <button
            type="button"
            onClick={() => {
              fileInputRef.current?.click()
              setFilesDropdownOpen(false)
            }}
            className="ws-dropdown-item"
          >
            <Upload className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
            Загрузить с компьютера
          </button>
          <button
            type="button"
            onClick={() => {
              if (variant === 'case') {
                props.onOpenCaseFilePicker()
              }
              setFilesDropdownOpen(false)
            }}
            className="ws-dropdown-item"
          >
            <FolderOpen className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
            Из документов дела
          </button>
        </div>
      )}
    </div>
  )

  return (
    <div className={isMike ? 'ws-input-card ws-input-card--mike' : 'ws-input-card'}>
      <div className={isMike ? 'px-4 pt-4' : 'px-4 pt-4 pb-2'}>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={resolvedPlaceholder}
          rows={isMike ? 1 : 3}
          className={
            isMike
              ? 'max-h-48 w-full resize-none overflow-hidden border-0 bg-transparent p-0 text-sm leading-6 text-gray-900 outline-none placeholder:text-gray-400'
              : 'w-full resize-none outline-none bg-transparent'
          }
          style={
            isMike
              ? undefined
              : {
                  minHeight: '80px',
                  fontSize: '15px',
                  lineHeight: '1.6',
                  color: 'var(--color-text-primary)',
                  fontFamily: 'inherit',
                }
          }
        />
      </div>

      {!isMike && (
        <HarveyInputFilePills
          uploadingFiles={uploadingFiles}
          fileContexts={fileContexts}
          selectedCaseFiles={selectedCaseFiles}
          onRemoveContext={onRemoveContext}
          onRemoveCaseFile={onRemoveCaseFile}
          caseFileIcon={variant === 'case' ? 'folder' : 'file'}
        />
      )}

      <div className={isMike ? 'ws-input-toolbar ws-input-toolbar--mike' : 'ws-input-toolbar'}>
        <div
          className={
            isMikeChrome
              ? 'flex min-w-0 flex-wrap items-center gap-2'
              : 'flex min-w-0 items-center overflow-hidden'
          }
          style={{ gap: isMikeChrome ? undefined : '2px' }}
        >
          {variant === 'global' && !isMikeGlobal ? (
            <>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="ws-input-tool-btn"
              >
                <Plus className="w-3.5 h-3.5" />
                Файлы
              </button>
              <button
                type="button"
                onClick={props.onOpenCasePicker}
                className={toolBtnClass(
                  'ws-input-tool-btn',
                  selectedCaseFiles.length > 0 && 'ws-input-tool-btn--accent',
                )}
              >
                <FolderOpen className="w-3.5 h-3.5" />
                Из дел
                {selectedCaseFiles.length > 0 && (
                  <span className="ws-input-count-badge">{selectedCaseFiles.length}</span>
                )}
              </button>
              <button type="button" disabled className="ws-input-tool-btn">
                <Sparkles className="w-3.5 h-3.5" />
                Улучшить
              </button>
            </>
          ) : isMikeGlobal ? (
            <>
              <button
                type="button"
                onClick={props.onOpenCasePicker}
                className={toolBtnClass(
                  'ws-mike-instrument-btn',
                  selectedCaseFiles.length > 0 && 'ws-mike-instrument-btn--active',
                )}
              >
                <FolderOpen className="h-3.5 w-3.5 shrink-0" aria-hidden />
                <span>Из дел</span>
                {selectedCaseFiles.length > 0 && (
                  <span className="ws-mike-instrument-count">{selectedCaseFiles.length}</span>
                )}
              </button>
              {productFeatures.courtPractice && (
                <MikeInstrumentToggle
                  active={useCourtPractice}
                  disabled={!canEnableCourtPractice(isDraftMode) || useLegalCorpus}
                  onClick={() => onUseCourtPracticeChange(!useCourtPractice)}
                  icon={Gavel}
                  label="Судебная практика"
                  title={
                    isDraftMode
                      ? 'Недоступно в режиме Draft'
                      : useLegalCorpus
                        ? 'Нельзя включить вместе с законодательством'
                        : undefined
                  }
                />
              )}
              {productFeatures.legalCorpus && (
                <MikeInstrumentToggle
                  active={useLegalCorpus}
                  disabled={!canEnableLegalResearch(isDraftMode) || useCourtPractice}
                  onClick={() => onUseLegalCorpusChange(!useLegalCorpus)}
                  icon={BookOpen}
                  label="Законодательство (127 фз)"
                  title={
                    isDraftMode
                      ? 'Недоступно в режиме Draft'
                      : useCourtPractice
                        ? 'Нельзя включить вместе с судебной практикой'
                        : undefined
                  }
                />
              )}
            </>
          ) : isMikeCase ? (
            <>
              {productFeatures.courtPractice && (
                <MikeInstrumentToggle
                  active={useCourtPractice}
                  disabled={!canEnableCourtPractice(isDraftMode)}
                  onClick={() => onUseCourtPracticeChange(!useCourtPractice)}
                  icon={Gavel}
                  label="Судебная практика"
                  title={isDraftMode ? 'Недоступно в режиме Draft' : undefined}
                />
              )}
            </>
          ) : (
            <>
              {caseFilesDropdown}
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                disabled={isStreaming || isImprovingPrompt || !value.trim()}
                onClick={() => onImprovePrompt?.()}
                className="ws-input-tool-btn"
                aria-label="Улучшить формулировку запроса"
              >
                {isImprovingPrompt ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />
                ) : (
                  <Sparkles className="w-3.5 h-3.5" aria-hidden />
                )}
                Улучшить
              </button>
            </>
          )}
        </div>

        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={CHAT_FILE_ACCEPT}
          className="hidden"
          onChange={handleFileInputChange}
        />

        {!isMikeChrome && (
          <div ref={promptsRef} className="relative flex-shrink-0">
            <button
              type="button"
              onClick={() => setPromptsOpen((open) => !open)}
              className={toolBtnClass('ws-input-tool-btn', promptsOpen && 'ws-input-tool-btn--active')}
            >
              <AlignJustify className="w-3.5 h-3.5" />
              Промпты
            </button>
            {promptsOpen && (
              <div className="ws-dropdown ws-dropdown--wide ws-dropdown--scroll">
                {LEGAL_PROMPTS.map((group) => (
                  <div key={group.category}>
                    <div className="ws-dropdown-header">{group.category}</div>
                    {group.prompts.map((prompt) => (
                      <button
                        key={prompt}
                        type="button"
                        onClick={() => {
                          onChange(prompt)
                          setPromptsOpen(false)
                        }}
                        className="ws-dropdown-item"
                      >
                        {prompt}
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {showInstrumentControls && !isMikeChrome && (
          <div ref={settingsRef} className="relative flex-shrink-0">
            <button
              type="button"
              onClick={() => setSettingsOpen((open) => !open)}
              className={toolBtnClass(
                'ws-input-tool-btn',
                settingsOpen && 'ws-input-tool-btn--active',
                hasActiveSettings && 'ws-input-tool-btn--accent',
              )}
            >
              <SlidersHorizontal className="w-3.5 h-3.5" />
              Настройки
              {hasActiveSettings && <span className="ws-input-active-dot ml-0.5" />}
            </button>
            <HarveyInputSettingsMenu
              variant={variant}
              isOpen={settingsOpen}
              onClose={() => setSettingsOpen(false)}
              isDraftMode={isDraftMode}
              onSetDraftMode={onSetDraftMode}
              useLegalCorpus={useLegalCorpus}
              onUseLegalCorpusChange={onUseLegalCorpusChange}
              useCourtPractice={useCourtPractice}
              onUseCourtPracticeChange={onUseCourtPracticeChange}
              isStreaming={isStreaming}
              isLegalCorpusUploader={variant === 'global' ? props.isLegalCorpusUploader : false}
              corpusFiles={variant === 'global' ? props.corpusFiles : []}
              corpusUploading={variant === 'global' ? props.corpusUploading : false}
              onCorpusFilesSelected={variant === 'global' ? props.onCorpusFilesSelected : () => {}}
              onDeleteCorpusFile={variant === 'global' ? props.onDeleteCorpusFile : () => {}}
            />
          </div>
        )}

        {!isMikeChrome && <div className="flex-1" />}

        {!isMike && (
          <button
            type="button"
            onClick={toggleRecording}
            disabled={isStreaming}
            className={toolBtnClass(
              'ws-input-mic-btn flex-shrink-0 mr-1',
              isRecording && 'ws-input-mic-btn--recording',
            )}
          >
            {isRecording ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
          </button>
        )}

        <div className="flex-shrink-0">
          {isMike ? (
            <button
              type="button"
              onClick={onSubmit}
              disabled={!value.trim() || isStreaming}
              className="ws-mike-send-btn"
              aria-label={isStreaming ? 'Остановить' : 'Отправить'}
            >
              {isStreaming ? (
                <Square className="h-4 w-4" fill="currentColor" strokeWidth={0} />
              ) : (
                <ArrowRight className="h-4 w-4" />
              )}
            </button>
          ) : (
            <button
              type="button"
              onClick={onSubmit}
              disabled={!value.trim() || isStreaming}
              className="ws-btn ws-btn-primary"
              style={{ minWidth: '80px' }}
            >
              {isStreaming ? (
                <div
                  className="w-4 h-4 border-2 rounded-full animate-spin"
                  style={{
                    borderColor: 'rgba(255,255,255,0.3)',
                    borderTopColor: 'var(--color-on-accent)',
                  }}
                />
              ) : (
                'Отправить'
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
