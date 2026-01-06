import { Moon, Sun } from 'lucide-react'
import { useTheme } from '../../hooks/useTheme'
import { Button } from './Button'

const ThemeToggle = () => {
  // Темная тема временно скрыта — не отображаем переключатель
  useTheme() // сохраняем вызов, чтобы не потерять связь с контекстом при будущих изменениях
  return null
}

export default ThemeToggle
