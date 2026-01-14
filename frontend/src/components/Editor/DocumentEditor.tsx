import { useEditor, EditorContent } from '@tiptap/react'
import { useEffect, useImperativeHandle, forwardRef } from 'react'
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
}

export const DocumentEditor = forwardRef<DocumentEditorRef, DocumentEditorProps>(({
  content,
  onChange,
  onSelectionChange,
  caseId,
  onInsertText
}, ref) => {
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

  // Expose insertText method via ref
  useImperativeHandle(ref, () => ({
    insertText: (text: string) => {
      if (editor) {
        editor.chain().focus().insertContent('\n\n' + text).run()
        onChange(editor.getHTML())
      }
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

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <EditorToolbar editor={editor} />
      <div className="flex-1 overflow-y-auto p-8">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
})

DocumentEditor.displayName = 'DocumentEditor'

