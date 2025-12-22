import axios from 'axios'
import { logger } from '../lib/logger'

const BASE_URL = import.meta.env.VITE_API_URL || ''

export interface RegisterRequest {
  email: string
  password: string
  full_name?: string
  company?: string
}

export interface LoginRequest {
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: {
    id: string
    email: string
    full_name: string | null
    company: string | null
    role: string
  }
}

export interface UserResponse {
  id: string
  email: string
  full_name: string | null
  company: string | null
  role: string
  created_at: string
}

const getApiUrl = (path: string) => {
  const prefix = BASE_URL.endsWith('/') ? BASE_URL.slice(0, -1) : BASE_URL
  return `${prefix}${path}`
}

export const register = async (data: RegisterRequest): Promise<TokenResponse> => {
  const response = await axios.post(getApiUrl('/api/auth/register'), data)
  return response.data
}

export const login = async (data: LoginRequest): Promise<TokenResponse> => {
  const response = await axios.post(getApiUrl('/api/auth/login'), data)
  return response.data
}

export const logout = async (): Promise<void> => {
  const token = localStorage.getItem('access_token')
  if (token) {
    try {
      await axios.post(
        getApiUrl('/api/auth/logout'),
        {},
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      )
    } catch (error) {
      logger.error('Logout error:', error)
    }
  }
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  localStorage.removeItem('user')
}

export const getMe = async (): Promise<UserResponse> => {
  const token = localStorage.getItem('access_token')
  if (!token) {
    throw new Error('No access token')
  }

  const response = await axios.get(getApiUrl('/api/auth/me'), {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
  return response.data
}

export const refreshToken = async (): Promise<{ access_token: string; token_type: string }> => {
  const refreshToken = localStorage.getItem('refresh_token')
  if (!refreshToken) {
    throw new Error('No refresh token')
  }

  const response = await axios.post(getApiUrl('/api/auth/refresh'), null, {
    params: {
      refresh_token: refreshToken,
    },
  })
  return response.data
}

