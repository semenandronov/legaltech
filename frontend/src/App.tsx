import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import ProtectedRoute from './components/ProtectedRoute'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import CasesListPage from './pages/CasesListPage'
import CaseOverviewPage from './pages/CaseOverviewPage'
import ContradictionsPage from './pages/ContradictionsPage'
import DocumentsPage from './pages/DocumentsPage'
import AnalysisPage from './pages/AnalysisPage'
import ReportsPage from './pages/ReportsPage'
import SettingsPage from './pages/SettingsPage'
import TabularReviewPage from './pages/TabularReviewPage'
import { useState, useEffect } from 'react'
import ChatWindow from './components/ChatWindow'
import CaseNavigation from './components/CaseOverview/CaseNavigation'
import { getCase } from './services/api'
import { logger } from '@/lib/logger'

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
            <CasesListPage />
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
            <CaseOverviewPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/documents"
        element={
          <ProtectedRoute>
            <DocumentsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/contradictions"
        element={
          <ProtectedRoute>
            <ContradictionsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/analysis"
        element={
          <ProtectedRoute>
            <AnalysisPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/reports"
        element={
          <ProtectedRoute>
            <ReportsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId/tabular-review/:reviewId?"
        element={
          <ProtectedRoute>
            <TabularReviewPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings"
        element={
          <ProtectedRoute>
            <SettingsPage />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

const CaseChatPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const [fileNames, setFileNames] = useState<string[]>([])

  useEffect(() => {
    if (caseId) {
      loadCase()
    }
  }, [caseId])

  const loadCase = async () => {
    if (!caseId) return
    try {
      const caseData = await getCase(caseId)
      setFileNames(caseData.file_names || [])
    } catch (error) {
      logger.error('Ошибка при загрузке дела:', error)
    }
  }

  return (
    <div className="flex h-screen bg-primary">
      <CaseNavigation caseId={caseId || ''} />
      <div className="flex-1 flex flex-col overflow-hidden">
        <main className="flex-1 overflow-y-auto">
          <div className="h-full">
            <ChatWindow caseId={caseId || ''} fileNames={fileNames} />
          </div>
        </main>
      </div>
    </div>
  )
}

export default App