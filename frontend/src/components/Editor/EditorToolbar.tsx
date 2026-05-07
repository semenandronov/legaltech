import { Editor } from '@tiptap/react'
import {
  Bold,
  Italic,
  List,
  ListOrdered,
  Undo,
  Redo,
  Heading1,
  Heading2,
  Heading3,
  Strikethrough,
  AlignLeft,
  AlignCenter,
  AlignRight,
  AlignJustify,
  AlertTriangle,
  Trash2,
  MessageSquarePlus,
  MessageSquareOff
} from 'lucide-react'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../UI/tooltip'
import { useEffect, useRef, useState } from 'react'

interface EditorToolbarProps {
  editor: Editor | null
  hasRisks?: boolean
  onClearRisks?: () => void
  onCommentsChanged?: (comments: Array<{ id: string; from: number; to: number; text: string; createdAt?: string }>) => void
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
  onCommentsChanged,
}: EditorToolbarProps) => {
  if (!editor) {
    return null
  }

  const DEFAULT_FONT_FAMILY = 'Times New Roman'
  const DEFAULT_FONT_SIZE = '14pt'

  const [currentFontFamily, setCurrentFontFamily] = useState<string>(DEFAULT_FONT_FAMILY)
  const [currentFontSize, setCurrentFontSize] = useState<string>(DEFAULT_FONT_SIZE)
  const lastSyncedRef = useRef<{ family: string; size: string }>({
    family: DEFAULT_FONT_FAMILY,
    size: DEFAULT_FONT_SIZE,
  })

  useEffect(() => {
    const syncFromSelection = () => {
      try {
        const attrs = editor.getAttributes('textStyle') as { fontFamily?: string; fontSize?: string }
        const nextFamily = attrs?.fontFamily || DEFAULT_FONT_FAMILY
        const nextSize = attrs?.fontSize || DEFAULT_FONT_SIZE
        const prev = lastSyncedRef.current
        if (prev.family !== nextFamily) {
          setCurrentFontFamily(nextFamily)
          prev.family = nextFamily
        }
        if (prev.size !== nextSize) {
          setCurrentFontSize(nextSize)
          prev.size = nextSize
        }
      } catch {
        const prev = lastSyncedRef.current
        if (prev.family !== DEFAULT_FONT_FAMILY) {
          setCurrentFontFamily(DEFAULT_FONT_FAMILY)
          prev.family = DEFAULT_FONT_FAMILY
        }
        if (prev.size !== DEFAULT_FONT_SIZE) {
          setCurrentFontSize(DEFAULT_FONT_SIZE)
          prev.size = DEFAULT_FONT_SIZE
        }
      }
    }

    syncFromSelection()
    editor.on('selectionUpdate', syncFromSelection)
    return () => {
      editor.off('selectionUpdate', syncFromSelection)
    }
  }, [editor])

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
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onMouseDown={preventFocusLoss}
          onClick={onClick}
          disabled={disabled}
          aria-label={title}
          aria-pressed={isActive}
          className={`p-2 rounded transition-colors ${
            isActive
              ? 'bg-muted text-foreground'
              : 'hover:bg-gray-100 text-gray-700'
          } disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          <Icon className="w-4 h-4" aria-hidden="true" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom">
        {title}
      </TooltipContent>
    </Tooltip>
  )

  return (
    <TooltipProvider delayDuration={350}>
      <div
        className="editor-toolbar flex items-center gap-1 p-2 border-b min-h-[54px] sticky top-0 z-30"
        style={{ borderBottomColor: 'var(--color-border)' }}
      >
        {/* Typography */}
        <>
          <select
            value={currentFontFamily}
            onMouseDown={preventFocusLoss}
            onPointerDown={preventFocusLoss}
            onChange={(e) => {
              const v = e.target.value
              setCurrentFontFamily(v)
              editor.chain().focus().setFontFamily(v).run()
            }}
            className="h-9 px-2 text-sm border rounded-md bg-white"
            style={{ borderColor: 'var(--color-border)' }}
            aria-label="Шрифт"
          >
            <option value="Times New Roman">Times New Roman</option>
            <option value="Arial">Arial</option>
            <option value="Calibri">Calibri</option>
            <option value="Inter">Inter</option>
          </select>
          <select
            value={currentFontSize}
            onMouseDown={preventFocusLoss}
            onPointerDown={preventFocusLoss}
            onChange={(e) => {
              const v = e.target.value
              setCurrentFontSize(v)
              editor.chain().focus().setFontSize(v).run()
            }}
            className="h-9 px-2 text-sm border rounded-md bg-white"
            style={{ borderColor: 'var(--color-border)' }}
            aria-label="Размер шрифта"
          >
            <option value="10pt">10</option>
            <option value="11pt">11</option>
            <option value="12pt">12</option>
            <option value="13pt">13</option>
            <option value="14pt">14</option>
            <option value="16pt">16</option>
            <option value="18pt">18</option>
            <option value="20pt">20</option>
          </select>
          <div className="w-px h-6 bg-gray-300 mx-1" />
        </>

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

        {/* Formatting */}
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

        <div className="w-px h-6 bg-gray-300 mx-1"></div>

        {/* Align */}
        <ToolbarButton
          onClick={() => editor.chain().focus().setTextAlign('left').run()}
          isActive={editor.isActive({ textAlign: 'left' })}
          icon={AlignLeft}
          title="По левому краю"
        />
        <ToolbarButton
          onClick={() => editor.chain().focus().setTextAlign('center').run()}
          isActive={editor.isActive({ textAlign: 'center' })}
          icon={AlignCenter}
          title="По центру"
        />
        <ToolbarButton
          onClick={() => editor.chain().focus().setTextAlign('right').run()}
          isActive={editor.isActive({ textAlign: 'right' })}
          icon={AlignRight}
          title="По правому краю"
        />
        <ToolbarButton
          onClick={() => editor.chain().focus().setTextAlign('justify').run()}
          isActive={editor.isActive({ textAlign: 'justify' })}
          icon={AlignJustify}
          title="По ширине"
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

        {/* Spacer */}
        <div className="flex-1"></div>

        {/* Comments */}
        <ToolbarButton
          onClick={() => {
            const { from, to } = editor.state.selection
            if (from === to) {
              window.alert('Выделите текст, чтобы добавить комментарий.')
              return
            }
            const text = window.prompt('Комментарий к выделенному фрагменту:')
            if (!text || !text.trim()) return
            editor.chain().focus().addComment(from, to, text.trim()).run()
            const ext: any = editor.extensionManager.extensions.find((e: any) => e.name === 'comment')
            const comments = (ext?.options?.comments || []) as Array<{ id: string; from: number; to: number; text: string; createdAt?: string }>
            onCommentsChanged?.(comments)
          }}
          icon={MessageSquarePlus}
          title="Добавить комментарий (по выделению)"
        />
        <ToolbarButton
          onClick={() => {
            editor.chain().focus().setComments([]).run()
            onCommentsChanged?.([])
          }}
          icon={MessageSquareOff}
          title="Очистить все комментарии"
        />

        {/* Risks */}
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
    </TooltipProvider>
  )
}
