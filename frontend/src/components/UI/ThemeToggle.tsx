import { Moon, Sun } from 'lucide-react'
import { useTheme } from '../../hooks/useTheme'
import Button from './Button'

const ThemeToggle = () => {
  const { theme, toggleTheme } = useTheme()
  
  return (
    <Button
      variant="secondary"
      size="sm"
      onClick={toggleTheme}
      className="p-2"
      aria-label={`Переключить на ${theme === 'dark' ? 'светлую' : 'тёмную'} тему`}
    >
      {theme === 'dark' ? (
        <Sun className="w-4 h-4" />
      ) : (
        <Moon className="w-4 h-4" />
      )}
    </Button>
  )
}

export default ThemeToggle
