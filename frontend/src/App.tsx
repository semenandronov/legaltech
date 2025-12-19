import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import ProtectedRoute from './components/ProtectedRoute'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import Dashboard from './pages/Dashboard'
import AnalysisPage from './pages/AnalysisPage'
import CaseWorkspacePage from './pages/CaseWorkspacePage'
import ReportsPage from './pages/ReportsPage'
import SettingsPage from './pages/SettingsPage'
import { useState, useEffect } from 'react'
import ChatWindow from './components/ChatWindow'
import Sidebar from './components/Layout/Sidebar'
import { getCase } from './services/api'

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Dashboard />
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
            <CaseWorkspacePage />
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
      console.error('Ошибка при загрузке дела:', error)
    }
  }

  return (
    <div className="dashboard-root">
      <Sidebar />
      <div className="dashboard-content chat-page-content">
        {/* Hide header on chat page for ChatGPT-style */}
        <main className="dashboard-main chat-page-main">
          <div className="dashboard-chat-column">
            <ChatWindow caseId={caseId || ''} fileNames={fileNames} />
          </div>
        </main>
      </div>
    </div>
  )
}

export default App

