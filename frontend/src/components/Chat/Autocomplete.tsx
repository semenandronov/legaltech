import React from 'react'
import { Box, Text } from '@radix-ui/themes'
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
    <Box 
      className="chat-autocomplete"
      style={{
        position: 'absolute',
        bottom: '100%',
        left: 0,
        right: 0,
        marginBottom: '8px',
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        borderRadius: '12px',
        boxShadow: '0 8px 24px rgba(0, 0, 0, 0.4)',
        zIndex: 100,
        maxHeight: '200px',
        overflowY: 'auto',
      }}
    >
      <Box className="chat-autocomplete-list" style={{ display: 'flex', flexDirection: 'column' }}>
        {suggestions.map((suggestion, index) => (
          <Box
            key={index}
            className={`chat-autocomplete-item ${index === selectedIndex ? 'selected' : ''}`}
            onClick={() => onSelect(suggestion)}
            style={{
              padding: '12px 16px',
              cursor: 'pointer',
              borderBottom: index < suggestions.length - 1 ? '1px solid var(--color-border)' : 'none',
              transition: 'background-color 0.15s',
              backgroundColor: index === selectedIndex ? 'var(--color-hover)' : 'transparent',
            }}
            onMouseEnter={(e) => {
              if (index !== selectedIndex) {
                e.currentTarget.style.backgroundColor = 'var(--color-hover)'
              }
            }}
            onMouseLeave={(e) => {
              if (index !== selectedIndex) {
                e.currentTarget.style.backgroundColor = 'transparent'
              }
            }}
          >
            <Text 
              className="chat-autocomplete-command"
              size="3"
              weight={index === selectedIndex ? 'medium' : 'regular'}
              style={{
                color: index === selectedIndex ? 'var(--color-primary)' : 'var(--color-text)',
              }}
            >
              {suggestion}
            </Text>
          </Box>
        ))}
      </Box>
    </Box>
  )
}

export default Autocomplete


