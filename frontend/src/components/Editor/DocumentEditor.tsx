import { useEditor, EditorContent } from '@tiptap/react'
import { useEffect, useImperativeHandle, forwardRef, useState, useCallback } from 'react'
import { useDebouncedCallback } from 'use-debounce'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import Link from '@tiptap/extension-link'
import Table from '@tiptap/extension-table'
import TableRow from '@tiptap/extension-table-row'
import TableCell from '@tiptap/extension-table-cell'
import TableHeader from '@tiptap/extension-table-header'
import Typography from '@tiptap/extension-typography'
import Highlight from '@tiptap/extension-highlight'
import { EditorToolbar } from './EditorToolbar'
import { SlashCommands } from './SlashCommands'
import { TrackChanges } from './extensions/TrackChanges'
import { Comment } from './extensions/Comment'
import { RiskHighlight } from './extensions/RiskHighlight'
import { AIKeyboardShortcuts } from './extensions/AIKeyboardShortcuts'
import { SelectionHighlight } from './extensions/SelectionHighlight'
import { SelectionMenu } from './SelectionMenu'
import type { RiskItem } from '../../services/documentEditorApi'
import { Ruler } from './Ruler'
import { FindReplace } from './FindReplace'
import { ClauseLibrary } from './ClauseLibrary'
import './Editor.css'

interface DocumentEditorProps {
  content: string
  onChange: (content: string) => void
  onSelectionChange: (text: string) => void
  onSelectionRangeChange?: (range: { from: number; to: number } | null) => void
  caseId?: string
  documentId?: string
  onInsertText?: (text: string) => void
}

export interface DocumentEditorRef {
  insertText: (text: string) => void
  setContent: (content: string) => void
  replaceSelectedText: (text: string) => void
  getSelectedText: () => string
  getSelectedRange: () => { from: number; to: number } | null
  setSelection: (from: number, to: number) => void
  addComment: (from: number, to: number, text: string) => void
  removeComment: (id: string) => void
  getComments: () => Array<{ id: string; from: number; to: number; text: string; createdAt?: string }>
  addRisk: (from: number, to: number, level: 'high' | 'medium' | 'low', description: string) => void
  setRisks: (risks: Array<{ id: string; from: number; to: number; level: 'high' | 'medium' | 'low'; description: string }>) => void
  clearRisks: () => void
  getRisks: () => Array<{ id: string; from: number; to: number; level: 'high' | 'medium' | 'low'; description: string }>
  scrollToText: (text: string) => boolean
  replaceText: (originalText: string, newText: string) => boolean
  replaceRange: (from: number, to: number, text: string) => void
  replaceMultipleTexts: (replacements: Array<{ original: string; replacement: string }>) => number
  setSelectionHighlight: (from: number, to: number) => void
  clearSelectionHighlight: () => void
}

export const DocumentEditor = forwardRef<DocumentEditorRef, DocumentEditorProps>(({
  content,
  onChange,
  onSelectionChange,
  onSelectionRangeChange,
  caseId,
  documentId,
  onInsertText
}, ref) => {
  // Zoom level for document scaling (could be made configurable via props in future)
  const zoom = 100
  const [trackChangesEnabled, setTrackChangesEnabled] = useState(false)
  const [hasRisks, setHasRisks] = useState(false)
  const [showFindReplace, setShowFindReplace] = useState(false)
  const [showClauseLibrary, setShowClauseLibrary] = useState(false)

  // Memoized callbacks for keyboard shortcuts
  const handleOpenFindReplace = useCallback(() => {
    setShowFindReplace(true)
  }, [])

  const handleOpenClauseLibrary = useCallback(() => {
    setShowClauseLibrary(true)
  }, [])

  const handleInsertClause = useCallback((clauseContent: string) => {
    if (onInsertText) {
      onInsertText(clauseContent)
    }
  }, [onInsertText])
  
  // Debounced onChange to prevent excessive re-renders during typing
  const debouncedOnChange = useDebouncedCallback(
    (html: string) => {
      onChange(html)
    },
    300 // 300ms debounce
  )
  
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: {
          levels: [1, 2, 3, 4, 5, 6],
        },
      }),
      Placeholder.configure({
        placeholder: 'Начните писать или введите / для команд...',
      }),
      Link.configure({
        openOnClick: false,
        HTMLAttributes: {
          class: 'editor-link',
        },
      }),
      Table.configure({
        resizable: true,
        HTMLAttributes: {
          class: 'editor-table',
        },
      }),
      TableRow,
      TableHeader,
      TableCell,
      Typography,
      Highlight.configure({
        multicolor: true,
      }),
      SlashCommands.configure({ 
        caseId, 
        documentId,
        onInsertText,
        onSetRisks: (risks) => {
          setHasRisks(risks.length > 0)
        }
      }),
      TrackChanges.configure({
        enabled: false,
        pendingChanges: [],
      }),
      Comment.configure({
        comments: [],
      }),
      RiskHighlight.configure({
        risks: [],
      }),
      AIKeyboardShortcuts.configure({
        documentId,
        onImproveText: () => {
          onChange(editor?.getHTML() || '')
        },
        onSetRisks: (risks) => {
          setHasRisks(risks.length > 0)
        },
        onOpenFindReplace: handleOpenFindReplace,
        onOpenClauseLibrary: handleOpenClauseLibrary,
      }),
      SelectionHighlight,
    ],
    content,
    editorProps: {
      attributes: {
        class: 'prose prose-lg max-w-none focus:outline-none editor-content',
      },
    },
    onUpdate: ({ editor }) => {
      const html = editor.getHTML()
      debouncedOnChange(html)
    },
    onSelectionUpdate: ({ editor }) => {
      const { from, to } = editor.state.selection
      const text = editor.state.doc.textBetween(from, to)
      onSelectionChange(text)
      if (onSelectionRangeChange) {
        onSelectionRangeChange(from !== to ? { from, to } : null)
      }
    },
  })

  // Update editor content when prop changes (e.g., when loading a document)
  useEffect(() => {
    if (editor && content !== editor.getHTML()) {
      editor.commands.setContent(content, false)
    }
  }, [content, editor])

  // Expose insertText and setContent methods via ref
  useImperativeHandle(ref, () => ({
    insertText: (text: string) => {
      if (editor) {
        editor.chain().focus().insertContent('\n\n' + text).run()
        onChange(editor.getHTML())
      }
    },
    setContent: (newContent: string) => {
      if (editor) {
        editor.commands.setContent(newContent, false)
        onChange(editor.getHTML())
      }
    },
    replaceSelectedText: (text: string) => {
      if (editor) {
        const { from, to } = editor.state.selection
        if (from !== to) {
          // Replace selected text
          editor.chain()
            .focus()
            .deleteRange({ from, to })
            .insertContent(text)
            .run()
        } else {
          // If nothing selected, just insert
          editor.chain().focus().insertContent(text).run()
        }
        onChange(editor.getHTML())
      }
    },
    getSelectedText: () => {
      if (editor) {
        const { from, to } = editor.state.selection
        return editor.state.doc.textBetween(from, to)
      }
      return ''
    },
    getSelectedRange: () => {
      if (editor) {
        const { from, to } = editor.state.selection
        if (from !== to) {
          return { from, to }
        }
      }
      return null
    },
    setSelection: (from: number, to: number) => {
      if (editor) {
        try {
          // Ensure positions are within document bounds
          const docSize = editor.state.doc.content.size
          const safeFrom = Math.max(0, Math.min(from, docSize))
          const safeTo = Math.max(safeFrom, Math.min(to, docSize))
          
          editor.chain()
            .focus()
            .setTextSelection({ from: safeFrom, to: safeTo })
            .scrollIntoView()
            .run()
        } catch (error) {
          console.error('Error setting selection:', error)
        }
      }
    },
    addComment: (from: number, to: number, text: string) => {
      if (editor) {
        editor.chain().focus().addComment(from, to, text).run()
        onChange(editor.getHTML())
      }
    },
    removeComment: (id: string) => {
      if (editor) {
        editor.chain().focus().removeComment(id).run()
        onChange(editor.getHTML())
      }
    },
    getComments: () => {
      if (editor) {
        const commentExtension = editor.extensionManager.extensions.find(ext => ext.name === 'comment')
        if (commentExtension && commentExtension.options.comments) {
          return commentExtension.options.comments
        }
      }
      return []
    },
    addRisk: (from: number, to: number, level: 'high' | 'medium' | 'low', description: string) => {
      if (editor) {
        editor.chain().focus().addRisk(from, to, level, description).run()
        setHasRisks(true)
        onChange(editor.getHTML())
      }
    },
    setRisks: (risks: Array<{ id: string; from: number; to: number; level: 'high' | 'medium' | 'low'; description: string }>) => {
      if (editor) {
        editor.chain().focus().setRisks(risks).run()
        setHasRisks(risks.length > 0)
        onChange(editor.getHTML())
      }
    },
    clearRisks: () => {
      if (editor) {
        editor.chain().focus().clearRisks().run()
        setHasRisks(false)
        onChange(editor.getHTML())
      }
    },
    getRisks: () => {
      if (editor) {
        const riskExtension = editor.extensionManager.extensions.find(ext => ext.name === 'riskHighlight')
        if (riskExtension && riskExtension.options.risks) {
          return riskExtension.options.risks
        }
      }
      return []
    },
    scrollToText: (text: string) => {
      if (!editor || !text) return false
      
      // Получаем текстовое содержимое документа
      const docText = editor.state.doc.textContent
      const searchText = text.trim()
      
      // Ищем позицию текста в документе
      const index = docText.indexOf(searchText)
      if (index === -1) {
        // Пробуем найти частичное совпадение (первые 50 символов)
        const shortText = searchText.slice(0, 50)
        const shortIndex = docText.indexOf(shortText)
        if (shortIndex === -1) return false
      }
      
      // Ищем позицию в ProseMirror документе
      let foundPos = -1
      editor.state.doc.descendants((node, pos) => {
        if (foundPos !== -1) return false
        if (node.isText && node.text) {
          const nodeIndex = node.text.indexOf(searchText)
          if (nodeIndex !== -1) {
            foundPos = pos + nodeIndex
            return false
          }
          // Частичное совпадение
          const shortText = searchText.slice(0, Math.min(50, searchText.length))
          const shortIndex = node.text.indexOf(shortText)
          if (shortIndex !== -1) {
            foundPos = pos + shortIndex
            return false
          }
        }
        return true
      })
      
      if (foundPos === -1) return false
      
      // Устанавливаем выделение и скроллим
      const endPos = Math.min(foundPos + searchText.length, editor.state.doc.content.size)
      
      editor.chain()
        .focus()
        .setTextSelection({ from: foundPos, to: endPos })
        .run()
      
      // Скроллим к выделенному тексту
      const { view } = editor
      const coords = view.coordsAtPos(foundPos)
      
      // Находим контейнер редактора и скроллим
      const editorElement = view.dom.closest('.document-canvas')
      if (editorElement && coords) {
        const containerRect = editorElement.getBoundingClientRect()
        const scrollTop = editorElement.scrollTop + (coords.top - containerRect.top) - containerRect.height / 3
        editorElement.scrollTo({
          top: Math.max(0, scrollTop),
          behavior: 'smooth'
        })
      }
      
      return true
    },
    replaceText: (originalText: string, newText: string) => {
      if (!editor || !originalText) return false
      
      // Ищем позицию текста в ProseMirror документе
      let foundPos = -1
      let foundEndPos = -1
      
      editor.state.doc.descendants((node, pos) => {
        if (foundPos !== -1) return false
        if (node.isText && node.text) {
          const nodeIndex = node.text.indexOf(originalText)
          if (nodeIndex !== -1) {
            foundPos = pos + nodeIndex
            foundEndPos = foundPos + originalText.length
            return false
          }
        }
        return true
      })
      
      if (foundPos === -1) return false
      
      // If track changes is enabled, add as pending change
      if (trackChangesEnabled) {
        editor.chain().focus().addPendingChange({
          id: `change-${Date.now()}`,
          from: foundPos,
          to: foundPos + newText.length,
          type: 'insertion' as const,
          content: newText,
        }).run()
      }
      
      // Заменяем текст
      editor.chain()
        .focus()
        .setTextSelection({ from: foundPos, to: foundEndPos })
        .deleteSelection()
        .insertContent(newText)
        .run()
      
      onChange(editor.getHTML())
      return true
    },
    replaceRange: (from: number, to: number, text: string) => {
      if (!editor) return
      editor.chain().focus().deleteRange({ from, to }).insertContent(text).run()
      onChange(editor.getHTML())
    },
    replaceMultipleTexts: (replacements: Array<{ original: string; replacement: string }>) => {
      if (!editor) return 0
      let applied = 0
      for (const { original, replacement } of replacements) {
        let foundPos = -1
        let foundEnd = -1
        editor.state.doc.descendants((node, pos) => {
          if (foundPos !== -1) return false
          if (node.isText && node.text) {
            const idx = node.text.indexOf(original)
            if (idx !== -1) {
              foundPos = pos + idx
              foundEnd = foundPos + original.length
              return false
            }
          }
          return true
        })
        if (foundPos !== -1) {
          editor.chain().focus().deleteRange({ from: foundPos, to: foundEnd }).insertContent(replacement).run()
          applied++
        }
      }
      if (applied > 0) onChange(editor.getHTML())
      return applied
    },
    setSelectionHighlight: (from: number, to: number) => {
      editor?.commands.setSelectionHighlight(from, to)
    },
    clearSelectionHighlight: () => {
      editor?.commands.clearSelectionHighlight()
    },
  }), [editor, onChange, trackChangesEnabled])

  if (!editor) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-2"></div>
          <p className="text-sm text-gray-500">Загрузка редактора...</p>
        </div>
      </div>
    )
  }

  // A4 dimensions at 96 DPI: 816px × 1056px
  const pageWidth = 816
  const pageHeight = 1056
  const margin = 96 // 1 inch = 96px
  const scaledWidth = (pageWidth * zoom) / 100
  const scaledHeight = (pageHeight * zoom) / 100
  const scaledMargin = (margin * zoom) / 100

  // Handle track changes toggle
  const handleTrackChangesToggle = (enabled: boolean) => {
    setTrackChangesEnabled(enabled)
    if (editor) {
      editor.chain().focus().setTrackChangesEnabled(enabled).run()
    }
  }

  // Handle clear risks
  const handleClearRisks = () => {
    if (editor) {
      editor.chain().focus().clearRisks().run()
      setHasRisks(false)
    }
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <EditorToolbar 
        editor={editor}
        trackChangesEnabled={trackChangesEnabled}
        onTrackChangesToggle={handleTrackChangesToggle}
        hasRisks={hasRisks}
        onClearRisks={handleClearRisks}
        onOpenFindReplace={handleOpenFindReplace}
        onOpenClauseLibrary={handleOpenClauseLibrary}
      />
      <div 
        className="flex-1 overflow-auto document-canvas"
        style={{ backgroundColor: '#f1f3f4' }}
      >
        <div className="flex justify-center py-8 px-4">
          <div className="document-container" style={{ width: `${scaledWidth + 20}px` }}>
            {/* Horizontal Ruler */}
            <div style={{ marginLeft: '20px' }}>
              <Ruler 
                length={scaledWidth} 
                orientation="horizontal" 
                zoom={zoom} 
              />
            </div>
            
            {/* Document with vertical ruler */}
            <div className="flex">
              {/* Vertical Ruler */}
              <Ruler 
                length={scaledHeight} 
                orientation="vertical" 
                zoom={zoom} 
              />
              
              {/* White document page */}
              <div 
                className="document-page bg-white"
                style={{
                  width: `${scaledWidth}px`,
                  minHeight: `${scaledHeight}px`,
                  boxShadow: '0 1px 3px 0 rgba(60, 64, 67, 0.3), 0 4px 8px 3px rgba(60, 64, 67, 0.15)',
                }}
              >
                {/* Document content area with margins */}
                <div
                  className="editor-content"
                  style={{
                    padding: `${scaledMargin}px`,
                    minHeight: `${scaledHeight - (scaledMargin * 2)}px`,
                  }}
                >
                  <EditorContent editor={editor} />
                  {/* Selection bubble menu for AI actions */}
                  <SelectionMenu 
                    editor={editor}
                    documentId={documentId}
                    onReplaceSelection={() => {
                      onChange(editor.getHTML())
                    }}
                    onSetRisks={(risks: RiskItem[]) => {
                      editor.chain().focus().setRisks(risks).run()
                      setHasRisks(risks.length > 0)
                    }}
                  />
                  {/* Find and Replace panel */}
                  <FindReplace
                    editor={editor}
                    isOpen={showFindReplace}
                    onClose={() => setShowFindReplace(false)}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      
      {/* Clause Library modal */}
      <ClauseLibrary
        isOpen={showClauseLibrary}
        onClose={() => setShowClauseLibrary(false)}
        onInsertClause={handleInsertClause}
        caseId={caseId}
      />
    </div>
  )
})

DocumentEditor.displayName = 'DocumentEditor'

