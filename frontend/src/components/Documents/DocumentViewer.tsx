import React, { useState, useEffect } from 'react'
import { DocumentWithMetadata } from './DocumentsList'
import EntityHighlighting from './EntityHighlighting'
import AIAnalysisPanel from './AIAnalysisPanel'
import { getEntities, ExtractedEntity } from '../../services/api'
import useKeyboardShortcuts from '../../hooks/useKeyboardShortcuts'
import CommandPalette from '../KeyboardShortcuts/CommandPalette'
import ShortcutsHelp from '../KeyboardShortcuts/ShortcutsHelp'
import './Documents.css'

interface DocumentViewerProps {
  document: DocumentWithMetadata | null
  caseId: string
  onNavigateNext: () => void
  onNavigatePrev: () => void
}

const DocumentViewer: React.FC<DocumentViewerProps> = ({
  document,
  caseId,
  onNavigateNext,
  onNavigatePrev
}) => {
  const [entities, setEntities] = useState<ExtractedEntity[]>([])
  const [documentText, setDocumentText] = useState<string>('')
  const [showCommandPalette, setShowCommandPalette] = useState(false)
  const [showShortcutsHelp, setShowShortcutsHelp] = useState(false)

  useEffect(() => {
    if (document?.id) {
      loadEntities()
      // TODO: Загрузить текст документа через API
      // Пока используем placeholder
      setDocumentText('Содержимое документа будет загружено здесь...')
    }
  }, [document?.id, caseId])

  // Keyboard shortcuts для навигации
  useKeyboardShortcuts({
    onNext: onNavigateNext,
    onPrev: onNavigatePrev,
    onConfirm: () => console.log('Confirm document'),
    onReject: () => console.log('Reject document'),
    onWithhold: () => console.log('Withhold document'),
    onCommandPalette: () => setShowCommandPalette(true),
    enabled: !!document
  })

  const commandPaletteCommands = [
    {
      id: 'confirm',
      label: 'Подтвердить документ',
      shortcut: 'y',
      action: () => console.log('Confirm')
    },
    {
      id: 'reject',
      label: 'Отклонить документ',
      shortcut: 'n',
      action: () => console.log('Reject')
    },
    {
      id: 'withhold',
      label: 'Заблокировать документ',
      shortcut: 'w',
      action: () => console.log('Withhold')
    },
    {
      id: 'help',
      label: 'Показать справку по shortcuts',
      shortcut: '?',
      action: () => {
        setShowCommandPalette(false)
        setShowShortcutsHelp(true)
      }
    }
  ]

  const loadEntities = async () => {
    if (!document?.id || !caseId) return
    try {
      const response = await getEntities(caseId, document.id)
      setEntities(response.entities || [])
    } catch (err) {
      console.error('Ошибка при загрузке сущностей:', err)
    }
  }

  if (!document) {
    return (
      <div className="document-viewer-empty">
        <div className="document-viewer-empty-content">
          <div className="document-viewer-empty-icon">📄</div>
          <h3>Выберите документ для просмотра</h3>
          <p>Кликните на документ в левой панели, чтобы открыть его здесь</p>
        </div>
      </div>
    )
  }

  const classification = document.classification
  const privilegeCheck = document.privilegeCheck
  const relevanceScore = classification?.relevance_score || 0
  const confidence = document.confidence || 0

  return (
    <div className="document-viewer">
      <div className="document-viewer-header">
        <div className="document-viewer-header-left">
          <button
            className="document-viewer-nav-btn"
            onClick={onNavigatePrev}
            aria-label="Предыдущий документ"
          >
            ←
          </button>
          <div className="document-viewer-title">
            <span className="document-viewer-filename">{document.filename}</span>
            {privilegeCheck?.is_privileged && (
              <span className="document-viewer-privilege-badge">🔒 Priv</span>
            )}
            {relevanceScore > 0 && (
              <span className="document-viewer-relevance">
                {relevanceScore}% | {Math.round(confidence)}% conf
              </span>
            )}
          </div>
          <button
            className="document-viewer-nav-btn"
            onClick={onNavigateNext}
            aria-label="Следующий документ"
          >
            →
          </button>
        </div>
        <div className="document-viewer-header-right">
          <button className="document-viewer-action-btn" aria-label="Поиск">
            🔍 Find
          </button>
          <button className="document-viewer-action-btn" aria-label="Настройки">
            ⚙️
          </button>
        </div>
      </div>

      <div className="document-viewer-content">
        <div className="document-viewer-text">
          <div className="document-viewer-metadata">
            {classification && (
              <>
                <div className="document-viewer-metadata-item">
                  <strong>Тип:</strong> {classification.doc_type}
                </div>
                {classification.key_topics && classification.key_topics.length > 0 && (
                  <div className="document-viewer-metadata-item">
                    <strong>Темы:</strong> {classification.key_topics.join(', ')}
                  </div>
                )}
              </>
            )}
            {document.created_at && (
              <div className="document-viewer-metadata-item">
                <strong>Дата загрузки:</strong> {new Date(document.created_at).toLocaleDateString('ru-RU')}
              </div>
            )}
          </div>

          {documentText ? (
            <EntityHighlighting
              text={documentText}
              entities={entities}
              onEntityClick={(entity) => {
                console.log('Entity clicked:', entity)
                // TODO: Показать детали сущности в модальном окне или sidebar
              }}
            />
          ) : (
            <div className="document-viewer-placeholder">
              <p>Загрузка содержимого документа...</p>
            </div>
          )}
        </div>
      </div>

      <AIAnalysisPanel
        document={document}
        entities={entities}
        onConfirm={() => console.log('Confirm document')}
        onReject={() => console.log('Reject document')}
        onWithhold={() => console.log('Withhold document')}
        onFlag={() => console.log('Flag document')}
        onBookmark={() => console.log('Bookmark document')}
        onAddComment={() => console.log('Add comment')}
      />

      {showCommandPalette && (
        <CommandPalette
          commands={commandPaletteCommands}
          onClose={() => setShowCommandPalette(false)}
        />
      )}

      {showShortcutsHelp && (
        <ShortcutsHelp onClose={() => setShowShortcutsHelp(false)} />
      )}
    </div>
  )
}

export default DocumentViewer
