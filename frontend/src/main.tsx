import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Theme as RadixTheme } from '@radix-ui/themes'
import { AuthProvider } from './contexts/AuthContext'
import { ThemeProvider, useTheme } from './contexts/ThemeContext'
import App from './App'
import '@radix-ui/themes/styles.css'
import './index.css'

// Wrapper to sync Radix Theme with our custom theme
const RadixThemeWrapper = ({ children }: { children: React.ReactNode }) => {
  const { theme } = useTheme()
  const isDark = theme === 'dark'
  
  return (
    <RadixTheme 
      appearance={isDark ? 'dark' : 'light'} 
      accentColor="cyan" 
      grayColor="slate"
      radius="medium"
      scaling="100%"
      style={{
        '--accent-9': '#00D4FF',
        '--accent-10': '#00B8E6',
        '--gray-1': isDark ? '#0F0F23' : '#FFFFFF',
        '--gray-2': isDark ? '#1A1B2E' : '#F8F9FA',
        '--gray-3': isDark ? '#242538' : '#F0F2F5',
        '--gray-4': isDark ? '#2A2B3E' : '#E5E8EB',
        '--gray-9': isDark ? '#B0B3C0' : '#666B78',
        '--gray-12': isDark ? '#FFFFFF' : '#0F1419',
      } as React.CSSProperties}
    >
      {children}
    </RadixTheme>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ThemeProvider>
        <RadixThemeWrapper>
          <AuthProvider>
            <App />
          </AuthProvider>
        </RadixThemeWrapper>
      </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>,
)

