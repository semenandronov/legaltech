import { BubbleMenu, Editor } from '@tiptap/react'
import { PenLine, Copy, Trash2, Loader2, ArrowRight, X } from 'lucide-react'
import { useState, useRef, useEffect } from 'react'
import { aiAssist, type RiskItem } from '../../services/documentEditorApi'
import { toast } from 'sonner'

interface SelectionMenuProps {
  editor: Editor
  documentId?: string
  onReplaceSelection?: (text: string) => void
  onSetRisks?: (risks: RiskItem[]) => void
}

type Mode = 'idle' | 'input' | 'loading'

export const SelectionMenu = ({
  editor,
  documentId,
  onReplaceSelection,
  onSetRisks: _onSetRisks,
}: SelectionMenuProps) => {
  const [mode, setMode] = useState<Mode>('idle')
  const [instruction, setInstruction] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // Focus input when entering revision mode
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
        cleaned = cleaned.replace(/^(Улучшенн(ый|ая|ое) (версия|текст|вариант)|Результат|Переписанн(ый|ая) (версия|текст)):?\s*\n*/i, '').trim()

        editor.chain().focus().deleteRange({ from, to }).insertContent(cleaned).run()
        if (onReplaceSelection) onReplaceSelection(cleaned)
        toast.success('Текст исправлен')
      } else {
        toast.error('Не удалось обработать текст')
      }
    } catch (error: any) {
      toast.error(error.message || 'Ошибка AI')
    } finally {
      setMode('idle')
      setInstruction('')
    }
  }

  const handleCopy = () => {
    const { from, to } = editor.state.selection
    const selectedText = editor.state.doc.textBetween(from, to)
    navigator.clipboard.writeText(selectedText)
    toast.success('Скопировано')
  }

  const handleDelete = () => {
    editor.chain().focus().deleteSelection().run()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleRevise()
    if (e.key === 'Escape') { setMode('idle'); setInstruction('') }
  }

  if (!documentId) return null

  return (
    <BubbleMenu
      editor={editor}
      shouldShow={({ editor: e }) => {
        const { from, to } = e.state.selection
        return from !== to
      }}
      tippyOptions={{
        duration: 150,
        placement: 'top',
        offset: [0, 8],
        appendTo: () => document.body,
        popperOptions: {
          modifiers: [
            { name: 'preventOverflow', options: { boundary: 'viewport', padding: 8 } },
            { name: 'flip', options: { fallbackPlacements: ['bottom', 'top'] } },
          ],
        },
      }}
    >
      <div
        className="flex items-center rounded-xl overflow-hidden"
        style={{
          background: 'rgba(10, 10, 10, 0.96)',
          boxShadow: '0 4px 20px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.07)',
          backdropFilter: 'blur(12px)',
        }}
      >
        {mode === 'idle' && (
          <>
            {/* Add revision */}
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => setMode('input')}
              className="flex items-center gap-2 px-3.5 py-2 text-[13px] font-medium transition-colors duration-100 whitespace-nowrap"
              style={{ color: 'rgba(255,255,255,0.9)', borderRight: '1px solid rgba(255,255,255,0.08)' }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.09)' }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
            >
              <PenLine className="w-3.5 h-3.5" />
              Add revision
            </button>

            {/* Copy */}
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={handleCopy}
              className="flex items-center justify-center w-9 py-2 transition-colors duration-100"
              style={{ color: 'rgba(255,255,255,0.6)', borderRight: '1px solid rgba(255,255,255,0.08)' }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.09)' }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
              title="Копировать"
            >
              <Copy className="w-3.5 h-3.5" />
            </button>

            {/* Delete */}
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={handleDelete}
              className="flex items-center justify-center w-9 py-2 transition-colors duration-100"
              style={{ color: 'rgba(255,255,255,0.6)' }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,80,80,0.15)'; e.currentTarget.style.color = '#f87171' }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'rgba(255,255,255,0.6)' }}
              title="Удалить"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </>
        )}

        {mode === 'input' && (
          <>
            <PenLine className="w-3.5 h-3.5 ml-3 flex-shrink-0" style={{ color: 'rgba(255,255,255,0.5)' }} />
            <input
              ref={inputRef}
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Как исправить..."
              className="bg-transparent outline-none text-[13px] px-2.5 py-2 w-56"
              style={{ color: 'rgba(255,255,255,0.9)', caretColor: 'white' }}
              onMouseDown={(e) => e.stopPropagation()}
            />
            {/* Confirm */}
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={handleRevise}
              disabled={!instruction.trim()}
              className="flex items-center justify-center w-8 py-2 transition-colors duration-100 disabled:opacity-30"
              style={{ color: 'rgba(255,255,255,0.8)', borderLeft: '1px solid rgba(255,255,255,0.08)' }}
              onMouseEnter={(e) => { if (instruction.trim()) e.currentTarget.style.background = 'rgba(255,255,255,0.09)' }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
            >
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
            {/* Cancel */}
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => { setMode('idle'); setInstruction('') }}
              className="flex items-center justify-center w-8 py-2 transition-colors duration-100"
              style={{ color: 'rgba(255,255,255,0.4)', borderLeft: '1px solid rgba(255,255,255,0.08)' }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.09)' }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </>
        )}

        {mode === 'loading' && (
          <div className="flex items-center gap-2 px-4 py-2">
            <Loader2 className="w-3.5 h-3.5 animate-spin" style={{ color: '#93c5fd' }} />
            <span className="text-[13px]" style={{ color: 'rgba(255,255,255,0.7)' }}>Исправляю...</span>
          </div>
        )}
      </div>
    </BubbleMenu>
  )
}
