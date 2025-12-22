import React from 'react'
import './Chat.css'

interface AutocompleteProps {
  suggestions: string[]
  selectedIndex: number
  onSelect: (suggestion: string) => void
  visible: boolean
}

const Autocomplete: React.FC<AutocompleteProps> = ({
  suggestions,
  selectedIndex,
  onSelect,
  visible
}) => {
  if (!visible || suggestions.length === 0) {
    return null
  }

  return (
    <div className="chat-autocomplete">
      <div className="chat-autocomplete-list">
        {suggestions.map((suggestion, index) => (
          <div
            key={index}
            className={`chat-autocomplete-item ${index === selectedIndex ? 'selected' : ''}`}
            onClick={() => onSelect(suggestion)}
            onMouseEnter={() => {
              // Handle hover if needed
            }}
          >
            <span className="chat-autocomplete-command">{suggestion}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default Autocomplete

