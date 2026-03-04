import { useEditor, EditorContent } from '@tiptap/react'
import { useEffect, useImperativeHandle, forwardRef, useState, useCallback, useRef } from 'react'
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
  const [hasRisks, setHasRisks] = useState(false)
  const [showFindReplace, setShowFindReplace] = useState(false)
  const [showClauseLibrary, setShowClauseLibrary] = useState(false)
  const editorContentRef = useRef<HTMLDivElement>(null)

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
      // Always report position — cursor (from===to) or selection (from!==to)
      if (onSelectionRangeChange) {
        onSelectionRangeChange({ from, to })
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

      const docText = editor.state.doc.textContent
      const searchText = text.trim()

      // Try progressively shorter strings until we find a match in the full doc text
      let matchText = searchText
      let charIndex = docText.indexOf(matchText)
      if (charIndex === -1) {
        matchText = searchText.slice(0, 100)
        charIndex = docText.indexOf(matchText)
      }
      if (charIndex === -1) {
        matchText = searchText.slice(0, 50)
        charIndex = docText.indexOf(matchText)
      }
      if (charIndex === -1) {
        // Try first 5 words
        matchText = searchText.split(/\s+/).slice(0, 5).join(' ')
        charIndex = docText.indexOf(matchText)
      }
      if (charIndex === -1) return false

      // Convert docText char offset → ProseMirror position by walking nodes
      // (text may span multiple nodes due to marks/formatting, so per-node indexOf fails)
      let charCount = 0
      let foundPos = -1
      editor.state.doc.descendants((node, pos) => {
        if (foundPos !== -1) return false
        if (node.isText && node.text) {
          const nodeLen = node.text.length
          if (charCount + nodeLen > charIndex) {
            foundPos = pos + (charIndex - charCount)
            return false
          }
          charCount += nodeLen
        }
        return true
      })

      if (foundPos === -1) return false

      const endPos = Math.min(foundPos + matchText.length, editor.state.doc.content.size)

      editor.chain()
        .focus()
        .setTextSelection({ from: foundPos, to: endPos })
        .run()

      const { view } = editor
      const coords = view.coordsAtPos(foundPos)
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

      const docText = editor.state.doc.textContent

      // Collect ALL occurrences (char offsets in docText)
      const charIndices: number[] = []
      let searchFrom = 0
      while (true) {
        const idx = docText.indexOf(originalText, searchFrom)
        if (idx === -1) break
        charIndices.push(idx)
        searchFrom = idx + originalText.length
      }
      if (charIndices.length === 0) return false

      // Convert docText char offset → ProseMirror position
      const charToPmPos = (charIndex: number): number => {
        let charCount = 0
        let foundPos = -1
        editor.state.doc.descendants((node, pos) => {
          if (foundPos !== -1) return false
          if (node.isText && node.text) {
            const nodeLen = node.text.length
            if (charCount + nodeLen > charIndex) {
              foundPos = pos + (charIndex - charCount)
              return false
            }
            charCount += nodeLen
          }
          return true
        })
        return foundPos
      }

      // Apply from LAST to FIRST so earlier positions stay stable
      charIndices.reverse()

      let tr = editor.state.tr
      for (const charIndex of charIndices) {
        const from = charToPmPos(charIndex)
        const to = charToPmPos(charIndex + originalText.length)
        if (from === -1 || to === -1) continue
        tr = tr.replaceWith(from, to, editor.state.schema.text(newText))
      }

      editor.view.dispatch(tr)
      editor.commands.focus()
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

      const charToPmPos = (_docText: string, charIndex: number): number => {
        let charCount = 0
        let foundPos = -1
        editor.state.doc.descendants((node, pos) => {
          if (foundPos !== -1) return false
          if (node.isText && node.text) {
            const nodeLen = node.text.length
            if (charCount + nodeLen > charIndex) {
              foundPos = pos + (charIndex - charCount)
              return false
            }
            charCount += nodeLen
          }
          return true
        })
        return foundPos
      }

      // Collect all (from, to, replacement) pairs from original doc, then apply last→first
      const docText = editor.state.doc.textContent
      const ops: { from: number; to: number; text: string }[] = []

      for (const { original, replacement } of replacements) {
        let searchFrom = 0
        while (true) {
          const idx = docText.indexOf(original, searchFrom)
          if (idx === -1) break
          const from = charToPmPos(docText, idx)
          const to = charToPmPos(docText, idx + original.length)
          if (from !== -1 && to !== -1) ops.push({ from, to, text: replacement })
          searchFrom = idx + original.length
        }
      }

      if (ops.length === 0) return 0

      // Sort descending by position so replacements don't shift earlier positions
      ops.sort((a, b) => b.from - a.from)

      let tr = editor.state.tr
      for (const { from, to, text } of ops) {
        tr = tr.replaceWith(from, to, editor.state.schema.text(text))
      }

      editor.view.dispatch(tr)
      editor.commands.focus()
      onChange(editor.getHTML())
      return ops.length
    },
    setSelectionHighlight: (from: number, to: number) => {
      editor?.commands.setSelectionHighlight(from, to)
    },
    clearSelectionHighlight: () => {
      editor?.commands.clearSelectionHighlight()
    },
  }), [editor, onChange])

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
        hasRisks={hasRisks}
        onClearRisks={handleClearRisks}
      />
      <div
        className="flex-1 overflow-auto document-canvas"
        style={{ backgroundColor: '#f1f3f4' }}
      >
        <div className="flex justify-center py-8 px-4">
          <div
            ref={editorContentRef}
            className="editor-content"
            style={{
              width: '100%',
              maxWidth: `${scaledWidth}px`,
              minHeight: `${scaledHeight}px`,
              backgroundColor: 'white',
              boxShadow: '0 1px 3px 0 rgba(60, 64, 67, 0.3), 0 4px 8px 3px rgba(60, 64, 67, 0.15)',
              padding: `${scaledMargin}px`,
            }}
          >
            <EditorContent editor={editor} />
            <FindReplace
              editor={editor}
              isOpen={showFindReplace}
              onClose={() => setShowFindReplace(false)}
            />
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

