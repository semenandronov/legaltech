import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import RegisterForm from '../components/Auth/RegisterForm'
import { useAuth } from '../contexts/AuthContext'

const RegisterPage = () => {
  const { isAuthenticated } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/', { replace: true })
    }
  }, [isAuthenticated, navigate])

  return <RegisterForm />
}

export default RegisterPage

