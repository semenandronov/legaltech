import { lazy, Suspense, useMemo } from 'react'
import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import { Box, CircularProgress } from '@mui/material'
import ProtectedRoute from './components/ProtectedRoute'
import { InternalDevToolsRoute } from './components/InternalDevToolsRoute'
import { FeatureRoute } from './components/FeatureRoute'
import { buildMainNavItems } from './lib/mainNavItems'
import { isProductFeatureEnabled } from './lib/productFeatures'
import LoginPage from './pages/LoginPage'
import UnifiedSidebar from './components/Layout/UnifiedSidebar'
const AssistantChatPage = lazy(() => import('./pages/AssistantChatPage'))

// Lazy load heavy pages
const CasesListPage = lazy(() => import('./pages/CasesListPage'))
const NewCasePage = lazy(() => import('./pages/NewCasePage'))
const ContradictionsPage = lazy(() => import('./pages/ContradictionsPage'))
const AnalysisPage = lazy(() => import('./pages/AnalysisPage'))
const ReportsPage = lazy(() => import('./pages/ReportsPage'))
const TabularReviewPage = lazy(() => import('./pages/TabularReviewPage'))
const OperationsPage = lazy(() => import('./pages/OperationsPage'))
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
const DoclingStructurePage = lazy(() => import('./pages/DoclingStructurePage'))
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
      <Route path="/register" element={<Navigate to="/login" replace />} />
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
            <FeatureRoute feature="globalAssistant" redirectTo="/cases">
              <Suspense fallback={<PageLoader />}>
                <GlobalAssistantPage />
              </Suspense>
            </FeatureRoute>
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
            <FeatureRoute feature="legalCorpusPages" redirectTo="/cases">
              <InternalDevToolsRoute redirectTo="/cases">
                <Suspense fallback={<PageLoader />}>
                  <LegalCorpusManagePage />
                </Suspense>
              </InternalDevToolsRoute>
            </FeatureRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/court-practice"
        element={
          <ProtectedRoute>
            <FeatureRoute feature="courtPracticePages" redirectTo="/cases">
              <Suspense fallback={<PageLoader />}>
                <CourtPracticeManagePage />
              </Suspense>
            </FeatureRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/draft-templates"
        element={
          <ProtectedRoute>
            <FeatureRoute feature="draftTemplates" redirectTo="/cases">
              <InternalDevToolsRoute redirectTo="/cases">
                <Suspense fallback={<PageLoader />}>
                  <DraftTemplatesAdminPage />
                </Suspense>
              </InternalDevToolsRoute>
            </FeatureRoute>
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
        path="/docling-structure"
        element={
          <ProtectedRoute>
            <InternalDevToolsRoute redirectTo="/cases">
              <Suspense fallback={<PageLoader />}>
                <DoclingStructurePage />
              </Suspense>
            </InternalDevToolsRoute>
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
            <CaseChatRouteGate />
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/chunk-lab"
        element={
          <ProtectedRoute>
            <FeatureRoute feature="chunkLab" redirectTo="/cases">
              <ChunkLabRouteGate />
            </FeatureRoute>
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
        path="/cases/:caseId/operations"
        element={
          <ProtectedRoute>
            <Suspense fallback={<PageLoader />}>
              <OperationsPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/editor/:documentId?"
        element={
          <ProtectedRoute>
            <FeatureRoute feature="editor" redirectTo="/cases">
              <Suspense fallback={<PageLoader />}>
                <DocumentEditorPage />
              </Suspense>
            </FeatureRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/playbooks"
        element={
          <ProtectedRoute>
            <FeatureRoute feature="playbooks" redirectTo="/cases">
              <Suspense fallback={<PageLoader />}>
                <PlaybooksPage />
              </Suspense>
            </FeatureRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/workflows"
        element={
          <ProtectedRoute>
            <FeatureRoute feature="agentRuns" redirectTo="/cases">
              <Suspense fallback={<PageLoader />}>
                <CaseWorkflowsPage />
              </Suspense>
            </FeatureRoute>
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

const ChunkLabRouteGate = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const fallback = caseId ? `/cases/${caseId}` : '/cases'
  return (
    <InternalDevToolsRoute redirectTo={fallback}>
      <Suspense fallback={<PageLoader />}>
        <ChunkLabPage />
      </Suspense>
    </InternalDevToolsRoute>
  )
}

/** Внутренний ассистент: при выключенном флаге — на обзор дела. */
const CaseChatRouteGate = () => {
  const { caseId } = useParams<{ caseId: string }>()
  if (!isProductFeatureEnabled('caseAssistant')) {
    return <Navigate to={caseId ? `/cases/${caseId}` : '/cases'} replace />
  }
  return <CaseChatPage />
}

const CaseChatPage = () => {
  const navItems = useMemo(() => buildMainNavItems(), [])

  return (
    <Suspense fallback={<PageLoader />}>
      <div className="ws-shell ws-tabular-shell flex h-screen overflow-hidden">
        <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton={false} variant="tabular" />
        <main className="ws-tabular-page flex min-h-0 flex-1 flex-col overflow-hidden">
          <AssistantChatPage />
        </main>
      </div>
    </Suspense>
  )
}

export default App
