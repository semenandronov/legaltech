import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Sidebar from '../components/Layout/Sidebar'
import Header from '../components/Layout/Header'
import StatsCards from '../components/Dashboard/StatsCards'
import CasesList from '../components/Dashboard/CasesList'
import UploadArea from '../components/UploadArea'
import ChatWindow from '../components/ChatWindow'
import CaseSidebar from '../components/CaseSidebar'
import './Dashboard.css'

const Dashboard = () => {
  const [caseId, setCaseId] = useState<string | null>(null)
  const [fileNames, setFileNames] = useState<string[]>([])
  const navigate = useNavigate()
  const location = useLocation()

  const handleUpload = (newCaseId: string, names: string[]) => {
    setCaseId(newCaseId)
    setFileNames(names)
    navigate(`/cases/${newCaseId}/chat`)
  }

  // Check if we're on a case page
  const isCasePage = location.pathname.startsWith('/cases/')

  return (
    <div className="dashboard-root">
      <Sidebar />
      <div className="dashboard-content" style={{ marginLeft: '260px' }}>
        <Header />
        <main className="dashboard-main">
          {isCasePage ? (
            // Case page - redirect to chat route (handled by App.tsx)
            null
          ) : (
            // Main dashboard - show stats and cases list
            <div className="dashboard-main-content">
              <StatsCards />
              <CasesList />
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

export default Dashboard

