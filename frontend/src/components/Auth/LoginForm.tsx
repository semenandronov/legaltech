import { useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import './Auth.css'

const LoginForm = () => {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    try {
      await login(email, password)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка при входе. Проверьте email и пароль.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h2 className="auth-title">Вход в систему</h2>
        <p className="auth-subtitle">Войдите в свой аккаунт для продолжения</p>

        {error && <div className="auth-error">{error}</div>}

        <form onSubmit={handleSubmit} className="auth-form">
          <div className="auth-field">
            <label htmlFor="email" className="auth-label">
              Email
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
            <label htmlFor="password" className="auth-label">
              Пароль
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

          <button type="submit" className="auth-button" disabled={loading}>
            {loading ? 'Вход...' : 'Войти'}
          </button>
        </form>
      </div>
    </div>
  )
}

export default LoginForm

