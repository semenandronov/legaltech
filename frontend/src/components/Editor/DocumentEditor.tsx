import { useEditor, EditorContent } from '@tiptap/react'
import { useEffect, useImperativeHandle, forwardRef, useState } from 'react'
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
import { Ruler } from './Ruler'
import './Editor.css'

interface DocumentEditorProps {
  content: string
  onChange: (content: string) => void
  onSelectionChange: (text: string) => void
  caseId?: string
  onInsertText?: (text: string) => void
}

export interface DocumentEditorRef {
  insertText: (text: string) => void
  setContent: (content: string) => void
  replaceSelectedText: (text: string) => void
  getSelectedText: () => string
  getSelectedRange: () => { from: number; to: number } | null
  addComment: (from: number, to: number, text: string) => void
  removeComment: (id: string) => void
  getComments: () => Array<{ id: string; from: number; to: number; text: string; createdAt?: string }>
  addRisk: (from: number, to: number, level: 'high' | 'medium' | 'low', description: string) => void
  clearRisks: () => void
  getRisks: () => Array<{ id: string; from: number; to: number; level: 'high' | 'medium' | 'low'; description: string }>
}

export const DocumentEditor = forwardRef<DocumentEditorRef, DocumentEditorProps>(({
  content,
  onChange,
  onSelectionChange,
  caseId,
  onInsertText
}, ref) => {
  const [zoom] = useState(100)
  
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
      SlashCommands.configure({ caseId, onInsertText }),
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
    ],
    content,
    editorProps: {
      attributes: {
        class: 'prose prose-lg max-w-none focus:outline-none editor-content',
      },
    },
    onUpdate: ({ editor }) => {
      const html = editor.getHTML()
      onChange(html)
    },
    onSelectionUpdate: ({ editor }) => {
      const { from, to } = editor.state.selection
      const text = editor.state.doc.textBetween(from, to)
      onSelectionChange(text)
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
    addComment: (from: number, to: number, text: string) => {
      if (editor) {
        ;(editor.chain().focus() as any).addComment(from, to, text).run()
        onChange(editor.getHTML())
      }
    },
    removeComment: (id: string) => {
      if (editor) {
        ;(editor.chain().focus() as any).removeComment(id).run()
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
        ;(editor.chain().focus() as any).addRisk(from, to, level, description).run()
        onChange(editor.getHTML())
      }
    },
    clearRisks: () => {
      if (editor) {
        ;(editor.chain().focus() as any).clearRisks().run()
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
    }
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

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <EditorToolbar editor={editor} />
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
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
})

DocumentEditor.displayName = 'DocumentEditor'

