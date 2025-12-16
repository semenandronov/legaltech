import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import LoginForm from '../components/Auth/LoginForm'
import { useAuth } from '../contexts/AuthContext'

const LoginPage = () => {
  const { isAuthenticated } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/', { replace: true })
    }
  }, [isAuthenticated, navigate])

  return <LoginForm />
}

export default LoginPage

