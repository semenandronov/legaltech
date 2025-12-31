import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import { Box, CircularProgress } from '@mui/material'
import { MessageSquare, FileText, Table } from 'lucide-react'
import ProtectedRoute from './components/ProtectedRoute'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import UnifiedSidebar from './components/Layout/UnifiedSidebar'
const AssistantChatPage = lazy(() => import('./pages/AssistantChatPage'))

// Lazy load heavy pages
const CasesListPage = lazy(() => import('./pages/CasesListPage'))
const CaseOverviewPage = lazy(() => import('./pages/CaseOverviewPage'))
const ContradictionsPage = lazy(() => import('./pages/ContradictionsPage'))
const DocumentsPage = lazy(() => import('./pages/DocumentsPage'))
const AnalysisPage = lazy(() => import('./pages/AnalysisPage'))
const ReportsPage = lazy(() => import('./pages/ReportsPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const TabularReviewPage = lazy(() => import('./pages/TabularReviewPage'))

// Loading fallback
const PageLoader = () => (
  <Box
    sx={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      height: '100vh',
    }}
  >
    <CircularProgress />
  </Box>
)

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Navigate to="/cases" replace />
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <CasesListPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId"
        element={
          <ProtectedRoute>
            <CaseRedirect />
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/chat"
        element={
          <ProtectedRoute>
            <CaseChatPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/workspace"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <CaseOverviewPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/documents"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <DocumentsPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/contradictions"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <ContradictionsPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/analysis"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <AnalysisPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/reports"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <ReportsPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/tabular-review/:reviewId?"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <TabularReviewPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <SettingsPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

const CaseRedirect = () => {
  const { caseId } = useParams<{ caseId: string }>()
  return <Navigate to={`/cases/${caseId}/chat`} replace />
}

const CaseChatPage = () => {
  const { caseId } = useParams<{ caseId: string }>()

  const navItems = [
    { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
    { id: 'documents', label: 'Документы', icon: FileText, path: `/cases/${caseId}/documents` },
    { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: `/cases/${caseId}/tabular-review` },
  ]

  return (
    <Suspense fallback={<PageLoader />}>
      <div className="flex h-screen bg-gradient-to-br from-[#F8F9FA] via-white to-[#F0F4F8]">
        <UnifiedSidebar navItems={navItems} title="Legal AI" />
        <div className="flex-1 flex flex-col overflow-hidden content-background">
          <main className="flex-1 overflow-y-auto">
            <div className="h-full">
              <AssistantChatPage />
            </div>
          </main>
        </div>
      </div>
    </Suspense>
  )
}

export default App