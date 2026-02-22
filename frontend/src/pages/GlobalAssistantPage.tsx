import { Suspense } from 'react'
import { Box, CircularProgress } from '@mui/material'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { AssistantUIChat } from '../components/Chat/AssistantUIChat'
import { Home, FolderOpen, MessageSquare } from 'lucide-react'

const PageLoader = () => (
  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
    <CircularProgress />
  </Box>
)

const GlobalAssistantPage = () => {
  const navItems = [
    { id: 'home', label: 'Главная', icon: Home, path: '/' },
    { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
    { id: 'assistant', label: 'Ассистент', icon: MessageSquare, path: '/assistant' },
  ]

  return (
    <div
      className="h-screen flex overflow-hidden"
      style={{ backgroundColor: 'var(--color-bg-primary)' }}
    >
      <UnifiedSidebar navItems={navItems} title="Legal AI" />
      <div className="flex-1 flex flex-col overflow-hidden">
        <main className="flex-1 overflow-hidden">
          <div className="h-full">
            <Suspense fallback={<PageLoader />}>
              <AssistantUIChat />
            </Suspense>
          </div>
        </main>
      </div>
    </div>
  )
}

export default GlobalAssistantPage
