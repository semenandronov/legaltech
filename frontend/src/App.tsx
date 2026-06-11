import { lazy, Suspense, useMemo } from 'react'
import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import { Box, CircularProgress } from '@mui/material'
import { MessageSquare, FileEdit, BookOpen, Scissors } from 'lucide-react'
import ProtectedRoute from './components/ProtectedRoute'
import { InternalDevToolsRoute } from './components/InternalDevToolsRoute'
import { useAuth } from './contexts/AuthContext'
import { canAccessInternalDevTools } from './utils/internalDevToolsAccess'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import UnifiedSidebar from './components/Layout/UnifiedSidebar'
const AssistantChatPage = lazy(() => import('./pages/AssistantChatPage'))

// Lazy load heavy pages
const CasesListPage = lazy(() => import('./pages/CasesListPage'))
const NewCasePage = lazy(() => import('./pages/NewCasePage'))
const ContradictionsPage = lazy(() => import('./pages/ContradictionsPage'))
const AnalysisPage = lazy(() => import('./pages/AnalysisPage'))
const ReportsPage = lazy(() => import('./pages/ReportsPage'))
const TabularReviewPage = lazy(() => import('./pages/TabularReviewPage'))
const DocumentEditorPage = lazy(() => import('./pages/DocumentEditorPage'))
const PlaybooksPage = lazy(() => import('./pages/PlaybooksPage'))
const GlobalAssistantPage = lazy(() => import('./pages/GlobalAssistantPage'))
const LegalCorpusManagePage = lazy(() => import('./pages/LegalCorpusManagePage'))
const CourtPracticeManagePage = lazy(() => import('./pages/CourtPracticeManagePage'))
const DraftTemplatesAdminPage = lazy(() => import('./pages/DraftTemplatesAdminPage'))
const CaseOverviewPage = lazy(() => import('./pages/CaseOverviewPage'))
const CaseWorkflowsPage = lazy(() => import('./pages/CaseWorkflowsPage'))
const HistoryPage = lazy(() => import('./pages/HistoryPage'))
const ChunkPreviewPage = lazy(() => import('./pages/ChunkPreviewPage'))
const ChunkLabPage = lazy(() => import('./pages/ChunkLabPage'))

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
        path="/assistant"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <GlobalAssistantPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route
        path="/history"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <HistoryPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route
        path="/legal-corpus"
        element={
          <ProtectedRoute>
            <InternalDevToolsRoute redirectTo="/cases">
              <Suspense fallback={<PageLoader />}>
                <LegalCorpusManagePage />
              </Suspense>
            </InternalDevToolsRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/court-practice"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <CourtPracticeManagePage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/draft-templates"
        element={
          <ProtectedRoute>
            <InternalDevToolsRoute redirectTo="/cases">
              <Suspense fallback={<PageLoader />}>
                <DraftTemplatesAdminPage />
              </Suspense>
            </InternalDevToolsRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/new"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <NewCasePage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route
        path="/chunk-preview"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <ChunkPreviewPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <CaseOverviewPage />
            </Suspense>
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
        path="/cases/:caseId/chunk-lab"
        element={
          <ProtectedRoute>
            <ChunkLabRouteGate />
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
        path="/cases/:caseId/editor/:documentId?"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <DocumentEditorPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/playbooks"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <PlaybooksPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/workflows"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <CaseWorkflowsPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

const ChunkLabRouteGate = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const fallback = caseId ? `/cases/${caseId}/chat` : '/cases'
  return (
    <InternalDevToolsRoute redirectTo={fallback}>
      <Suspense fallback={<PageLoader />}>
        <ChunkLabPage />
      </Suspense>
    </InternalDevToolsRoute>
  )
}

const CaseChatPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const { user } = useAuth()

  const navItems = useMemo(() => {
    const all = [
      { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
      { id: 'chunk-lab', label: 'Чанки', icon: Scissors, path: `/cases/${caseId}/chunk-lab` },
      { id: 'editor', label: 'Редактор', icon: FileEdit, path: `/cases/${caseId}/editor` },
      { id: 'playbooks', label: 'Playbooks', icon: BookOpen, path: `/cases/${caseId}/playbooks` },
    ]
    if (!canAccessInternalDevTools(user?.email)) {
      return all.filter((item) => item.id !== 'chunk-lab')
    }
    return all
  }, [caseId, user?.email])

  return (
    <Suspense fallback={<PageLoader />}>
      <div 
        className="flex h-screen"
        style={{ backgroundColor: 'var(--color-bg-primary)' }}
      >
        <UnifiedSidebar navItems={navItems} title="Legal AI" />
        <main className="flex-1 overflow-hidden">
          <AssistantChatPage />
        </main>
      </div>
    </Suspense>
  )
}

export default App
