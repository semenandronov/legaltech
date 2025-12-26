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
  const [theme, setThemeState] = useState<Theme>(() => {
    // Check localStorage first, then default to dark (Harvey style)
    const saved = localStorage.getItem('theme') as Theme | null
    if (saved) return saved
    
    // Default to dark theme (Harvey style)
    return 'dark'
  })

  // Create MUI theme based on current theme mode
  const muiTheme = useMemo(() => {
    return createHarveyTheme(theme as PaletteMode)
  }, [theme])

  // Initialize theme on mount
  useEffect(() => {
    const root = document.documentElement
    const saved = localStorage.getItem('theme') as Theme | null
    const initialTheme = saved || 'dark'
    root.setAttribute('data-theme', initialTheme)
    if (!saved) {
      localStorage.setItem('theme', initialTheme)
    }
    
    // Add/remove dark class for shadcn-ui (for backward compatibility)
    if (initialTheme === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
  }, [])

  useEffect(() => {
    const root = document.documentElement
    root.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
    
    // Add/remove dark class for shadcn-ui (for backward compatibility)
    if (theme === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
  }, [theme])

  const toggleTheme = () => {
    setThemeState(prev => prev === 'dark' ? 'light' : 'dark')
  }

  const setTheme = (newTheme: Theme) => {
    setThemeState(newTheme)
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
