import React from 'react'
import { Card, CardContent } from '@/components/UI/Card'
import { cn } from '@/lib/utils'
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
    <Card className="absolute bottom-full left-0 right-0 mb-2 border shadow-lg z-50 max-h-[200px] overflow-hidden">
      <CardContent className="p-0">
        <div className="flex flex-col">
          {suggestions.map((suggestion, index) => (
            <button
              key={index}
              className={cn(
                "px-4 py-3 text-left text-sm transition-colors cursor-pointer",
                "hover:bg-accent focus:bg-accent focus:outline-none",
                index === selectedIndex && "bg-accent font-medium text-primary",
                index < suggestions.length - 1 && "border-b"
              )}
              onClick={() => onSelect(suggestion)}
              onMouseEnter={() => {
                // Можно добавить логику для обновления selectedIndex при hover
              }}
            >
              <span className={cn(
                index === selectedIndex ? "text-primary" : "text-foreground"
              )}>
                {suggestion}
              </span>
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

export default Autocomplete
