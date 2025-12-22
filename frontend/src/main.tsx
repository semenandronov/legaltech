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
  return (
    <RadixTheme 
      appearance={theme === 'dark' ? 'dark' : 'light'} 
      accentColor="cyan" 
      radius="medium"
      scaling="100%"
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

