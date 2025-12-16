import { useLocation } from 'react-router-dom'
import Sidebar from '../components/Layout/Sidebar'
import Header from '../components/Layout/Header'
import StatsCards from '../components/Dashboard/StatsCards'
import CasesList from '../components/Dashboard/CasesList'
import './Dashboard.css'

const Dashboard = () => {
  const location = useLocation()

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

