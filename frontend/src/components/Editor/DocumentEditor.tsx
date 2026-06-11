import { useEditor, EditorContent } from '@tiptap/react'
import { useEffect, useImperativeHandle, forwardRef, useState, useCallback, useRef, useMemo } from 'react'
import { useDebouncedCallback } from 'use-debounce'
import type { CommentItem } from './extensions/Comment'
import { EditorToolbar } from './EditorToolbar'
import { createEditorExtensions } from './createEditorExtensions'
import { FindReplace } from './FindReplace'
import { SelectionMenu } from './SelectionMenu'
import { ClauseLibrary } from './ClauseLibrary'
import './Editor.css'
import { buildEditorContextForChat } from '@/utils/editorContextWindow'
import { fuzzyFindInPlainText } from '@/utils/applyHybridEdit'
import {
  textSpanToPmRange,
  replaceTextSpanPreservingMarks,
  resolveTextOccurrenceInDoc,
} from '@/utils/docTextPosition'
import { capturePmRange, type PmTextRange } from './editorSelection'

interface DocumentEditorProps {
  content: string
  onChange: (content: string) => void
  onSelectionChange: (text: string) => void
  onSelectionRangeChange?: (range: { from: number; to: number } | null) => void
  caseId?: string
  documentId?: string
  onInsertText?: (text: string) => void
  comments?: CommentItem[]
  onCommentsChange?: (comments: CommentItem[]) => void
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
  scrollToText: (text: string, nthOccurrence?: number) => boolean
  replaceText: (originalText: string, newText: string) => boolean
  replaceAllText: (originalText: string, newText: string) => number
  replaceRange: (from: number, to: number, text: string) => void
  replaceNodeById: (nodeId: string, newText: string) => boolean
  replaceTextFuzzy: (originalText: string, newText: string) => boolean
  getChatContextHtml: () => string
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
  onInsertText,
  comments,
  onCommentsChange,
}, ref) => {
  // Zoom level for document scaling (could be made configurable via props in future)
  const zoom = 100
  const [hasRisks, setHasRisks] = useState(false)
  const [showFindReplace, setShowFindReplace] = useState(false)
  const [showClauseLibrary, setShowClauseLibrary] = useState(false)
  const editorContentRef = useRef<HTMLDivElement>(null)
  /** Preserved while toolbar/select steals focus — formatting applies here, not first line. */
  const savedSelectionRef = useRef<PmTextRange | null>(null)

  // Stable refs — parent re-renders on every selection must NOT recreate the editor.
  const onChangeRef = useRef(onChange)
  const onSelectionChangeRef = useRef(onSelectionChange)
  const onSelectionRangeChangeRef = useRef(onSelectionRangeChange)
  const onInsertTextRef = useRef(onInsertText)
  onChangeRef.current = onChange
  onSelectionChangeRef.current = onSelectionChange
  onSelectionRangeChangeRef.current = onSelectionRangeChange
  onInsertTextRef.current = onInsertText

  const handleOpenFindReplace = useCallback(() => {
    setShowFindReplace(true)
  }, [])

  const handleOpenClauseLibrary = useCallback(() => {
    setShowClauseLibrary(true)
  }, [])

  const handleInsertClause = useCallback((clauseContent: string) => {
    onInsertTextRef.current?.(clauseContent)
  }, [])

  const lastEditorContentRef = useRef<string>('')
  const lastUserScrollAtRef = useRef<number>(0)

  const debouncedOnChange = useDebouncedCallback((html: string) => {
    lastEditorContentRef.current = html
    onChangeRef.current(html)
  }, 300)

  const editorInstanceRef = useRef<ReturnType<typeof useEditor>>(null)

  const extensions = useMemo(
    () =>
      createEditorExtensions({
        caseId,
        documentId,
        onInsertText: (text) => onInsertTextRef.current?.(text),
        onSetRisks: (risks) => setHasRisks(risks.length > 0),
        onImproveText: () => {
          const ed = editorInstanceRef.current
          if (ed) onChangeRef.current(ed.getHTML())
        },
        onOpenFindReplace: handleOpenFindReplace,
        onOpenClauseLibrary: handleOpenClauseLibrary,
      }),
    [caseId, documentId, handleOpenFindReplace, handleOpenClauseLibrary],
  )

  const editor = useEditor(
    {
      extensions,
      content,
      editable: true,
      immediatelyRender: false,
      editorProps: {
        attributes: {
          class: 'editor-surface focus:outline-none',
          spellcheck: 'true',
        },
        handleScrollToSelection: () => true,
      },
      onUpdate: ({ editor: ed }) => {
        debouncedOnChange(ed.getHTML())
      },
      onCreate: ({ editor: ed }) => {
        queueMicrotask(() => {
          ed.commands.syncDraftGapMarks()
        })
      },
      onSelectionUpdate: ({ editor: ed }) => {
        const { from, to } = ed.state.selection
        onSelectionChangeRef.current(ed.state.doc.textBetween(from, to))
        const captured = capturePmRange(ed)
        if (captured) {
          savedSelectionRef.current = captured
        }
        onSelectionRangeChangeRef.current?.(from !== to ? { from, to } : null)
      },
    },
    [caseId, documentId],
  )

  editorInstanceRef.current = editor

  // Update editor content when prop changes externally (e.g., loading a document, restoring a version).
  // Skip if the new content is what the editor itself just produced — avoids re-setting on undo/redo.
  useEffect(() => {
    if (editor && content !== editor.getHTML() && content !== lastEditorContentRef.current) {
      editor.commands.setContent(content, false)
      lastEditorContentRef.current = content
      queueMicrotask(() => {
        editor.commands.syncDraftGapMarks()
      })
    }
  }, [content, editor])

  // Hydrate comments from props (persisted in document metadata).
  useEffect(() => {
    if (!editor) return
    if (!comments) return
    editor.commands.setComments(comments)
  }, [editor, comments, documentId])

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
        const commentExtension: any = editor.extensionManager.extensions.find(ext => ext.name === 'comment')
        const nextComments = (commentExtension?.options?.comments || []) as CommentItem[]
        onCommentsChange?.(nextComments)
        onChange(editor.getHTML())
      }
    },
    removeComment: (id: string) => {
      if (editor) {
        editor.chain().focus().removeComment(id).run()
        const commentExtension: any = editor.extensionManager.extensions.find(ext => ext.name === 'comment')
        const nextComments = (commentExtension?.options?.comments || []) as CommentItem[]
        onCommentsChange?.(nextComments)
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
    scrollToText: (text: string, nthOccurrence: number = 0) => {
      if (!editor || !text) return false

      const doc = editor.state.doc
      const occurrence = resolveTextOccurrenceInDoc(doc.textContent, text, nthOccurrence)
      if (!occurrence) return false

      const pmRange = textSpanToPmRange(doc, occurrence.charStart, occurrence.charEnd)
      if (!pmRange) return false

      editor.chain().focus().setTextSelection(pmRange).run()

      const { view } = editor
      const coords = view.coordsAtPos(pmRange.from)
      const editorElement = view.dom.closest('.document-canvas')
      if (editorElement && coords) {
        const containerRect = editorElement.getBoundingClientRect()
        const scrollTop =
          editorElement.scrollTop + (coords.top - containerRect.top) - containerRect.height / 3
        editorElement.scrollTo({
          top: Math.max(0, scrollTop),
          behavior: 'smooth',
        })
      }

      return true
    },
    replaceText: (originalText: string, newText: string) => {
      if (!editor || !originalText) return false
      const occurrence = resolveTextOccurrenceInDoc(editor.state.doc.textContent, originalText, 0)
      if (!occurrence) return false
      return replaceTextSpanPreservingMarks(
        editor,
        occurrence.charStart,
        occurrence.charEnd,
        newText,
      )
    },
    replaceAllText: (originalText: string, newText: string) => {
      if (!editor || !originalText) return 0
      const doc = editor.state.doc
      const docText = doc.textContent
      const ops: { from: number; to: number }[] = []
      let searchFrom = 0

      while (true) {
        const idx = docText.indexOf(originalText, searchFrom)
        if (idx === -1) break
        const range = textSpanToPmRange(doc, idx, idx + originalText.length)
        if (range) ops.push(range)
        searchFrom = idx + originalText.length
      }

      if (ops.length === 0) return 0

      ops.sort((a, b) => b.from - a.from)
      let tr = editor.state.tr
      for (const { from, to } of ops) {
        const marks = tr.doc.resolve(from).marks()
        const node =
          marks.length > 0
            ? editor.state.schema.text(newText, marks)
            : editor.state.schema.text(newText)
        tr = tr.replaceWith(from, to, node)
      }
      editor.view.dispatch(tr)
      editor.commands.focus()
      return ops.length
    },
    replaceRange: (from: number, to: number, text: string) => {
      if (!editor) return
      editor.chain().focus().deleteRange({ from, to }).insertContent(text).run()
      // onUpdate fires automatically
    },
    replaceTextFuzzy: (originalText: string, newText: string) => {
      if (!editor || !originalText) return false
      const docText = editor.state.doc.textContent
      const match = fuzzyFindInPlainText(docText, originalText)
      if (!match) return false

      let charStart = docText.indexOf(match)
      if (charStart === -1) {
        charStart = docText.toLowerCase().indexOf(match.toLowerCase())
      }
      if (charStart === -1) return false

      return replaceTextSpanPreservingMarks(editor, charStart, charStart + match.length, newText)
    },
    getChatContextHtml: () => {
      if (!editor) return ''
      const full = editor.getHTML()
      const { from, to } = editor.state.selection
      const selected = from !== to ? editor.state.doc.textBetween(from, to) : ''
      return buildEditorContextForChat(full, {
        selectedText: selected || undefined,
      }).html
    },
    replaceNodeById: (nodeId: string, newText: string) => {
      if (!editor || !nodeId?.trim()) return false

      const { state, view } = editor
      let blockPos = -1
      let blockNode = state.doc.nodeAt(0)

      state.doc.descendants((node, pos) => {
        if (node.attrs?.id === nodeId && node.isBlock) {
          blockPos = pos
          blockNode = node
          return false
        }
        return true
      })

      if (blockPos === -1 || !blockNode?.isBlock) return false

      const innerFrom = blockPos + 1
      const innerTo = blockPos + blockNode.nodeSize - 1
      const tr = state.tr

      if (innerTo > innerFrom) {
        tr.replaceWith(innerFrom, innerTo, state.schema.text(newText))
      } else {
        tr.insert(innerFrom, state.schema.text(newText))
      }

      view.dispatch(tr)
      editor.commands.focus()
      onChange(editor.getHTML())
      return true
    },
    replaceMultipleTexts: (replacements: Array<{ original: string; replacement: string }>) => {
      if (!editor) return 0

      const doc = editor.state.doc
      const docText = doc.textContent
      const ops: { from: number; to: number; text: string }[] = []

      for (const { original, replacement } of replacements) {
        let searchFrom = 0
        while (true) {
          const idx = docText.indexOf(original, searchFrom)
          if (idx === -1) break
          const range = textSpanToPmRange(doc, idx, idx + original.length)
          if (range) ops.push({ ...range, text: replacement })
          searchFrom = idx + original.length
        }
      }

      if (ops.length === 0) return 0

      ops.sort((a, b) => b.from - a.from)

      let tr = editor.state.tr
      for (const { from, to, text } of ops) {
        const marks = tr.doc.resolve(from).marks()
        const newNode =
          marks.length > 0
            ? editor.state.schema.text(text, marks)
            : editor.state.schema.text(text)
        tr = tr.replaceWith(from, to, newNode)
      }

      editor.view.dispatch(tr)
      editor.commands.focus()
      return ops.length
    },
    setSelectionHighlight: () => {
      /* native ProseMirror selection only — highlight plugin removed (broke drag-select) */
    },
    clearSelectionHighlight: () => {},
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
        getSavedSelection={() => savedSelectionRef.current}
        hasRisks={hasRisks}
        onClearRisks={handleClearRisks}
        onCommentsChanged={(next) => onCommentsChange?.(next as CommentItem[])}
      />
      <div
        className="flex-1 overflow-auto document-canvas"
        style={{ backgroundColor: '#f1f3f4' }}
        onScroll={() => {
          lastUserScrollAtRef.current = Date.now()
        }}
      >
        <div style={{ width: '100%', padding: '32px 24px 96px', boxSizing: 'border-box' }}>
          <div
            ref={editorContentRef}
            className="editor-content"
            style={{
              width: '100%',
              maxWidth: `${scaledWidth}px`,
              minHeight: `${scaledHeight}px`,
              margin: '0 auto',
              backgroundColor: 'white',
              boxShadow: 'none',
              padding: `${scaledMargin}px`,
            }}
          >
            <div className="relative">
              <EditorContent editor={editor} />
            </div>
            <SelectionMenu
              editor={editor}
              documentId={documentId}
              onReplaceSelection={() => onChange(editor.getHTML())}
            />
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

