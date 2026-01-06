import { createContext, useContext, useEffect, useState, ReactNode, useMemo } from 'react'
import { ThemeProvider as MUIThemeProvider, CssBaseline } from '@mui/material'
import { createHarveyTheme } from '../theme/theme'
import type { PaletteMode } from '@mui/material'

type Theme = 'dark' | 'light'

interface ThemeContextType {
  theme: Theme
  toggleTheme: () => void
  setTheme: (theme: Theme) => void
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined)

export const ThemeProvider = ({ children }: { children: ReactNode }) => {
  // По умолчанию и всегда используем светлую тему (Legora-style)
  const [theme, setThemeState] = useState<Theme>('light')

  // Create MUI theme based on current theme mode
  const muiTheme = useMemo(() => {
    return createHarveyTheme(theme as PaletteMode)
  }, [theme])

  // Initialize theme on mount - форсим светлую тему и игнорируем предыдущие сохранения
  useEffect(() => {
    const root = document.documentElement
    const initialTheme: Theme = 'light'
    root.setAttribute('data-theme', initialTheme)
    localStorage.setItem('theme', initialTheme)
    setThemeState(initialTheme)

    // Add/remove dark class for shadcn-ui (for backward compatibility)
    root.classList.remove('dark')
  }, [])

  useEffect(() => {
    const root = document.documentElement
    root.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
    
    // Add/remove dark class for shadcn-ui (for backward compatibility)
    root.classList.remove('dark')
  }, [theme])

  const toggleTheme = () => {
    // Темная тема временно скрыта — оставляем только светлую
    setThemeState('light')
  }

  const setTheme = (newTheme: Theme) => {
    // Гарантируем, что тема остаётся светлой
    setThemeState('light')
  }

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, setTheme }}>
      <MUIThemeProvider theme={muiTheme}>
        <CssBaseline />
        {children}
      </MUIThemeProvider>
    </ThemeContext.Provider>
  )
}

export const useTheme = () => {
  const context = useContext(ThemeContext)
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider')
  }
  return context
}
