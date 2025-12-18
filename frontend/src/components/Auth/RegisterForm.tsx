import { useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import './Auth.css'

const RegisterForm = () => {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [company, setCompany] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const { register } = useAuth()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (password !== confirmPassword) {
      setError('Пароли не совпадают')
      return
    }

    if (password.length < 8) {
      setError('Пароль должен быть не менее 8 символов')
      return
    }

    setLoading(true)

    try {
      await register(email, password, fullName || undefined, company || undefined)
    } catch (err: any) {
      // Улучшенная обработка ошибок (как в LoginForm)
      let errorMessage = 'Ошибка при регистрации. Попробуйте еще раз.'
      
      if (err.response) {
        const data = err.response.data
        if (typeof data?.detail === 'string') {
          errorMessage = data.detail
        } else if (Array.isArray(data?.detail)) {
          // Ошибки валидации Pydantic
          errorMessage = data.detail.map((e: any) => {
            const field = e.loc?.join('.') || 'field'
            return `${field}: ${e.msg || 'validation error'}`
          }).join('; ')
        } else if (data?.detail) {
          errorMessage = String(data.detail)
        } else if (data?.message) {
          errorMessage = String(data.message)
        }
      } else if (err.message) {
        errorMessage = err.message
      }
      
      setError(errorMessage)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h2 className="auth-title">Регистрация</h2>
        <p className="auth-subtitle">Создайте новый аккаунт</p>

        {error && <div className="auth-error">{error}</div>}

        <form onSubmit={handleSubmit} className="auth-form">
          <div className="auth-field">
            <label htmlFor="email" className="auth-label">
              Email *
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="auth-input"
              placeholder="your@email.com"
              disabled={loading}
            />
          </div>

          <div className="auth-field">
            <label htmlFor="fullName" className="auth-label">
              ФИО
            </label>
            <input
              id="fullName"
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="auth-input"
              placeholder="Иванов Иван Иванович"
              disabled={loading}
            />
          </div>

          <div className="auth-field">
            <label htmlFor="company" className="auth-label">
              Компания
            </label>
            <input
              id="company"
              type="text"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              className="auth-input"
              placeholder="ООО Компания"
              disabled={loading}
            />
          </div>

          <div className="auth-field">
            <label htmlFor="password" className="auth-label">
              Пароль * (минимум 8 символов)
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="auth-input"
              placeholder="••••••••"
              disabled={loading}
              minLength={8}
            />
          </div>

          <div className="auth-field">
            <label htmlFor="confirmPassword" className="auth-label">
              Подтвердите пароль *
            </label>
            <input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              className="auth-input"
              placeholder="••••••••"
              disabled={loading}
              minLength={8}
            />
          </div>

          <button type="submit" className="auth-button" disabled={loading}>
            {loading ? 'Регистрация...' : 'Зарегистрироваться'}
          </button>
        </form>
      </div>
    </div>
  )
}

export default RegisterForm

