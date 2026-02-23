import { Editor } from '@tiptap/react'
import {
  Bold,
  Italic,
  List,
  ListOrdered,
  Link as LinkIcon,
  Undo,
  Redo,
  Heading1,
  Heading2,
  Heading3,
  Strikethrough,
  Code,
  Quote,
  AlertTriangle,
  Trash2,
  Search,
  Library
} from 'lucide-react'

interface EditorToolbarProps {
  editor: Editor | null
  hasRisks?: boolean
  onClearRisks?: () => void
  onOpenFindReplace?: () => void
  onOpenClauseLibrary?: () => void
}

// Prevent toolbar buttons from stealing focus from the editor.
// This is the standard fix for TipTap toolbar — without it,
// the first click only returns focus and the command is ignored.
const preventFocusLoss = (e: React.MouseEvent) => {
  e.preventDefault()
}

export const EditorToolbar = ({
  editor,
  hasRisks = false,
  onClearRisks,
  onOpenFindReplace,
  onOpenClauseLibrary
}: EditorToolbarProps) => {
  if (!editor) {
    return null
  }

  const ToolbarButton = ({
    onClick,
    isActive,
    disabled,
    icon: Icon,
    title
  }: {
    onClick: () => void
    isActive?: boolean
    disabled?: boolean
    icon: React.ComponentType<{ className?: string }>
    title: string
  }) => (
    <button
      onMouseDown={preventFocusLoss}
      onClick={onClick}
      disabled={disabled}
      aria-label={title}
      aria-pressed={isActive}
      className={`p-2 rounded transition-colors ${
        isActive
          ? 'bg-blue-100 text-blue-700'
          : 'hover:bg-gray-100 text-gray-700'
      } disabled:opacity-50 disabled:cursor-not-allowed`}
    >
      <Icon className="w-4 h-4" aria-hidden="true" />
    </button>
  )

  return (
    <div className="flex items-center gap-1 p-2 border-b bg-white" style={{ borderBottomColor: 'var(--color-border)' }}>
      {/* Undo/Redo */}
      <ToolbarButton
        onClick={() => editor.chain().focus().undo().run()}
        disabled={!editor.can().undo()}
        icon={Undo}
        title="Отменить (Ctrl+Z)"
      />
      <ToolbarButton
        onClick={() => editor.chain().focus().redo().run()}
        disabled={!editor.can().redo()}
        icon={Redo}
        title="Повторить (Ctrl+Y)"
      />

      <div className="w-px h-6 bg-gray-300 mx-1"></div>

      {/* Headings */}
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
        isActive={editor.isActive('heading', { level: 1 })}
        icon={Heading1}
        title="Заголовок 1"
      />
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
        isActive={editor.isActive('heading', { level: 2 })}
        icon={Heading2}
        title="Заголовок 2"
      />
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
        isActive={editor.isActive('heading', { level: 3 })}
        icon={Heading3}
        title="Заголовок 3"
      />

      <div className="w-px h-6 bg-gray-300 mx-1"></div>

      {/* Text formatting */}
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleBold().run()}
        isActive={editor.isActive('bold')}
        icon={Bold}
        title="Жирный (Ctrl+B)"
      />
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleItalic().run()}
        isActive={editor.isActive('italic')}
        icon={Italic}
        title="Курсив (Ctrl+I)"
      />
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleStrike().run()}
        isActive={editor.isActive('strike')}
        icon={Strikethrough}
        title="Зачеркнуть"
      />
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleCode().run()}
        isActive={editor.isActive('code')}
        icon={Code}
        title="Код"
      />
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleBlockquote().run()}
        isActive={editor.isActive('blockquote')}
        icon={Quote}
        title="Цитата"
      />

      <div className="w-px h-6 bg-gray-300 mx-1"></div>

      {/* Lists */}
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleBulletList().run()}
        isActive={editor.isActive('bulletList')}
        icon={List}
        title="Маркированный список"
      />
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
        isActive={editor.isActive('orderedList')}
        icon={ListOrdered}
        title="Нумерованный список"
      />

      <div className="w-px h-6 bg-gray-300 mx-1"></div>

      {/* Link */}
      <ToolbarButton
        onClick={() => {
          const url = window.prompt('Введите URL:')
          if (url) {
            editor.chain().focus().setLink({ href: url }).run()
          }
        }}
        isActive={editor.isActive('link')}
        icon={LinkIcon}
        title="Вставить ссылку"
      />

      {/* Table */}
      <button
        onMouseDown={preventFocusLoss}
        onClick={() => {
          editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
        }}
        className="p-2 rounded hover:bg-gray-100 text-gray-700 transition-colors"
        aria-label="Вставить таблицу"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
      </button>

      <div className="w-px h-6 bg-gray-300 mx-1"></div>

      {/* Find & Replace */}
      {onOpenFindReplace && (
        <button
          onMouseDown={preventFocusLoss}
          onClick={onOpenFindReplace}
          className="p-2 rounded hover:bg-gray-100 text-gray-700 transition-colors"
          aria-label="Поиск и замена"
        >
          <Search className="w-4 h-4" aria-hidden="true" />
        </button>
      )}

      {/* Clause Library */}
      {onOpenClauseLibrary && (
        <button
          onMouseDown={preventFocusLoss}
          onClick={onOpenClauseLibrary}
          className="p-2 rounded hover:bg-gray-100 text-gray-700 transition-colors"
          aria-label="Библиотека клауз"
        >
          <Library className="w-4 h-4" aria-hidden="true" />
        </button>
      )}

      {/* Spacer to push Track Changes and Risks to the right */}
      <div className="flex-1"></div>

      {/* Risks indicator and clear button */}
      {hasRisks && onClearRisks && (
        <>
          <div className="flex items-center gap-1 px-2 py-1 bg-amber-50 border border-amber-200 rounded text-amber-700 text-xs">
            <AlertTriangle className="w-3 h-3" aria-hidden="true" />
            <span>Риски подсвечены</span>
          </div>
          <button
            onMouseDown={preventFocusLoss}
            onClick={onClearRisks}
            className="p-2 rounded hover:bg-amber-100 text-amber-600 transition-colors"
            aria-label="Очистить подсветку рисков"
          >
            <Trash2 className="w-4 h-4" />
          </button>
          <div className="w-px h-6 bg-gray-300 mx-1"></div>
        </>
      )}


    </div>
  )
}
