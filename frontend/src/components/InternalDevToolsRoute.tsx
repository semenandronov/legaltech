import { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { Box, CircularProgress } from '@mui/material'
import { useAuth } from '../contexts/AuthContext'
import { canAccessInternalDevTools } from '../utils/internalDevToolsAccess'

/**
 * Оборачивает маршруты chunk-lab, legal-corpus, admin/draft-templates.
 * Чужие пользователи получают редирект.
 */
export function InternalDevToolsRoute({ children, redirectTo }: { children: ReactNode; redirectTo: string }) {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <CircularProgress />
      </Box>
    )
  }

  if (!canAccessInternalDevTools(user?.email)) {
    return <Navigate to={redirectTo} replace />
  }

  return <>{children}</>
}
