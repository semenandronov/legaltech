import { createPortal } from 'react-dom'
import type { Editor } from '@tiptap/react'
import { PenLine, Copy, Trash2, Loader2, ArrowRight, X } from 'lucide-react'
import { useState, useRef, useEffect, useCallback } from 'react'
import { aiAssist, type RiskItem } from '../../services/documentEditorApi'
import { toast } from 'sonner'

interface SelectionMenuProps {
  editor: Editor
  documentId?: string
  onReplaceSelection?: (text: string) => void
  onSetRisks?: (risks: RiskItem[]) => void
}

type Mode = 'idle' | 'input' | 'loading'

interface MenuCoords {
  top: number
  left: number
}

function getSelectionMenuCoords(editor: Editor): MenuCoords | null {
  const { from, to } = editor.state.selection
  if (from === to || editor.isDestroyed) return null
  if (editor.isActive('table')) return null

  try {
    const start = editor.view.coordsAtPos(from)
    const end = editor.view.coordsAtPos(to)
    return {
      top: Math.min(start.top, end.top),
      left: (start.left + end.right) / 2,
    }
  } catch {
    return null
  }
}

export const SelectionMenu = ({
  editor,
  documentId,
  onReplaceSelection,
  onSetRisks: _onSetRisks,
}: SelectionMenuProps) => {
  const [mode, setMode] = useState<Mode>('idle')
  const [instruction, setInstruction] = useState('')
  const [visible, setVisible] = useState(false)
  const [coords, setCoords] = useState<MenuCoords | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const syncPosition = useCallback(() => {
    const next = getSelectionMenuCoords(editor)
    if (!next) {
      setVisible(false)
      setCoords(null)
      if (mode !== 'loading') {
        setMode('idle')
        setInstruction('')
      }
      return
    }
    setCoords(next)
    setVisible(true)
  }, [editor, mode])

  useEffect(() => {
    syncPosition()
    editor.on('selectionUpdate', syncPosition)

    const scrollRoot = editor.view.dom.closest('.document-canvas')
    scrollRoot?.addEventListener('scroll', syncPosition, { passive: true })
    window.addEventListener('resize', syncPosition)

    return () => {
      editor.off('selectionUpdate', syncPosition)
      scrollRoot?.removeEventListener('scroll', syncPosition)
      window.removeEventListener('resize', syncPosition)
    }
  }, [editor, syncPosition])

  useEffect(() => {
    if (mode === 'input') {
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [mode])

  const handleRevise = async () => {
    if (!instruction.trim()) return
    if (!documentId) {
      toast.error('Сначала сохраните документ')
      return
    }

    const { from, to } = editor.state.selection
    const selectedText = editor.state.doc.textBetween(from, to)
    if (!selectedText) {
      toast.error('Выделите текст')
      return
    }

    setMode('loading')
    try {
      const result = await aiAssist(documentId, 'improve', selectedText, instruction.trim())
      if (result.result) {
        let cleaned = result.result.trim()
        cleaned = cleaned.replace(/^```[\s\S]*?\n/, '').replace(/\n```\s*$/, '')
        cleaned = cleaned.replace(
          /^(Улучшенн(ый|ая|ое) (версия|текст|вариант)|Результат|Переписанн(ый|ая) (версия|текст)):?\s*\n*/i,
          '',
        ).trim()

        editor.chain().focus().deleteRange({ from, to }).insertContent(cleaned).run()
        onReplaceSelection?.(cleaned)
        toast.success('Текст исправлен')
      } else {
        toast.error('Не удалось обработать текст')
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Ошибка AI'
      toast.error(message)
    } finally {
      setMode('idle')
      setInstruction('')
    }
  }

  const handleCopy = () => {
    const { from, to } = editor.state.selection
    const selectedText = editor.state.doc.textBetween(from, to)
    void navigator.clipboard.writeText(selectedText)
    toast.success('Скопировано')
  }

  const handleDelete = () => {
    editor.chain().focus().deleteSelection().run()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleRevise()
    if (e.key === 'Escape') {
      setMode('idle')
      setInstruction('')
    }
  }

  if (!visible || !coords) {
    return null
  }

  return createPortal(
    <div
      role="toolbar"
      aria-label="Действия с выделением"
      className="flex items-center rounded-xl shadow-xl border border-white/10"
      style={{
        position: 'fixed',
        top: coords.top - 8,
        left: coords.left,
        transform: 'translate(-50%, -100%)',
        zIndex: 10050,
        background: 'rgba(17, 17, 17, 0.95)',
        backdropFilter: 'blur(10px)',
        pointerEvents: 'auto',
      }}
    >
      {mode === 'idle' && (
        <>
          {documentId && (
            <button
              type="button"
              onClick={() => setMode('input')}
              className="flex items-center gap-2 px-3.5 py-2 text-[13px] font-medium text-white/90 hover:bg-white/10 border-r border-white/10 whitespace-nowrap"
            >
              <PenLine className="w-3.5 h-3.5" />
              Исправить AI
            </button>
          )}

          <button
            type="button"
            onClick={handleCopy}
            className="flex items-center justify-center w-9 py-2 text-white/70 hover:bg-white/10 border-r border-white/10"
            title="Копировать"
          >
            <Copy className="w-3.5 h-3.5" />
          </button>

          <button
            type="button"
            onClick={handleDelete}
            className="flex items-center justify-center w-9 py-2 text-white/70 hover:bg-red-500/20 hover:text-red-300"
            title="Удалить"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </>
      )}

      {mode === 'input' && (
        <>
          <PenLine className="w-3.5 h-3.5 ml-3 shrink-0 text-white/50" />
          <input
            ref={inputRef}
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Как исправить..."
            className="bg-transparent outline-none text-[13px] text-white px-2.5 py-2 w-52"
          />
          <button
            type="button"
            onClick={handleRevise}
            disabled={!instruction.trim()}
            className="flex items-center justify-center w-8 py-2 text-white/80 hover:bg-white/10 border-l border-white/10 disabled:opacity-30"
          >
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => {
              setMode('idle')
              setInstruction('')
            }}
            className="flex items-center justify-center w-8 py-2 text-white/50 hover:bg-white/10 border-l border-white/10"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </>
      )}

      {mode === 'loading' && (
        <div className="flex items-center gap-2 px-4 py-2 text-white/80 text-[13px]">
          <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-300" />
          Исправляю…
        </div>
      )}
    </div>,
    document.body,
  )
}
