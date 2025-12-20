import { Navigate } from 'react-router-dom'

const Dashboard = () => {
  // Redirect to cases list page
  return <Navigate to="/cases" replace />
}

export default Dashboard

