import React, { useState, useEffect, useRef } from 'react'
import './ShortcutsHelp.css'

interface Command {
  id: string
  label: string
  shortcut?: string
  action: () => void
}

interface CommandPaletteProps {
  commands: Command[]
  onClose: () => void
}

const CommandPalette: React.FC<CommandPaletteProps> = ({ commands, onClose }) => {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const filteredCommands = commands.filter(cmd =>
    cmd.label.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      onClose()
      return
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex(prev => Math.min(prev + 1, filteredCommands.length - 1))
      return
    }

    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex(prev => Math.max(prev - 1, 0))
      return
    }

    if (e.key === 'Enter') {
      e.preventDefault()
      if (filteredCommands[selectedIndex]) {
        filteredCommands[selectedIndex].action()
        onClose()
      }
      return
    }
  }

  return (
    <div className="command-palette-overlay" onClick={onClose}>
      <div className="command-palette-modal" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          type="text"
          className="command-palette-input"
          placeholder="Введите команду..."
          value={searchQuery}
          onChange={(e) => {
            setSearchQuery(e.target.value)
            setSelectedIndex(0)
          }}
          onKeyDown={handleKeyDown}
        />
        <div className="command-palette-list">
          {filteredCommands.map((cmd, idx) => (
            <div
              key={cmd.id}
              className={`command-palette-item ${idx === selectedIndex ? 'selected' : ''}`}
              onClick={() => {
                cmd.action()
                onClose()
              }}
            >
              <span className="command-palette-label">{cmd.label}</span>
              {cmd.shortcut && (
                <span className="command-palette-shortcut">{cmd.shortcut}</span>
              )}
            </div>
          ))}
          {filteredCommands.length === 0 && (
            <div className="command-palette-empty">Команды не найдены</div>
          )}
        </div>
      </div>
    </div>
  )
}

export default CommandPalette
