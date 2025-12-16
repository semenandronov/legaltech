import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { login as loginApi, register as registerApi, logout as logoutApi, getMe, UserResponse } from '../services/auth'

interface AuthContextType {
  user: UserResponse | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, fullName?: string, company?: string) => Promise<void>
  logout: () => Promise<void>
  isAuthenticated: boolean
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

interface AuthProviderProps {
  children: ReactNode
}

export const AuthProvider = ({ children }: AuthProviderProps) => {
  const [user, setUser] = useState<UserResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Check if user is logged in on mount
    const checkAuth = async () => {
      const token = localStorage.getItem('access_token')
      const storedUser = localStorage.getItem('user')

      if (token && storedUser) {
        try {
          // Verify token is still valid
          const userData = await getMe()
          setUser(userData)
          localStorage.setItem('user', JSON.stringify(userData))
        } catch (error) {
          // Token invalid, clear storage
          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
          localStorage.removeItem('user')
          setUser(null)
        }
      }
      setLoading(false)
    }

    checkAuth()
  }, [])

  const login = async (email: string, password: string) => {
    const response = await loginApi({ email, password })
    localStorage.setItem('access_token', response.access_token)
    localStorage.setItem('refresh_token', response.refresh_token)
    localStorage.setItem('user', JSON.stringify(response.user))
    setUser(response.user as UserResponse)
  }

  const register = async (email: string, password: string, fullName?: string, company?: string) => {
    const response = await registerApi({ email, password, full_name: fullName, company })
    localStorage.setItem('access_token', response.access_token)
    localStorage.setItem('refresh_token', response.refresh_token)
    localStorage.setItem('user', JSON.stringify(response.user))
    setUser(response.user as UserResponse)
  }

  const logout = async () => {
    await logoutApi()
    setUser(null)
  }

  const value: AuthContextType = {
    user,
    loading,
    login,
    register,
    logout,
    isAuthenticated: !!user,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

