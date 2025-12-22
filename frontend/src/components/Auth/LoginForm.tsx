"use client"

import { useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import * as z from 'zod'
import { toast } from 'sonner'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/UI/form'
import Input from '@/components/UI/Input'
import { Button } from '@/components/UI/Button'
import { Alert, AlertDescription } from '@/components/UI/alert'

const loginSchema = z.object({
  email: z.string().email('Некорректный email адрес'),
  password: z.string().min(8, 'Пароль должен содержать минимум 8 символов'),
})

type LoginFormValues = z.infer<typeof loginSchema>

const LoginForm = () => {
  const [error, setError] = useState<string | null>(null)
  const { login } = useAuth()

  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      email: '',
      password: '',
    },
  })

  const handleSubmit = async (values: LoginFormValues) => {
    setError(null)
    
    try {
      await login(values.email, values.password)
      toast.success('Успешный вход в систему')
    } catch (err: unknown) {
      let errorMessage = 'Ошибка при входе. Проверьте email и пароль.'
      
      if (err && typeof err === 'object' && 'response' in err) {
        const axiosError = err as { response?: { data?: { detail?: string | Array<{ loc?: string[]; msg?: string }>; message?: string } } }
        const data = axiosError.response?.data
        if (typeof data?.detail === 'string') {
          errorMessage = data.detail
        } else if (Array.isArray(data?.detail)) {
          errorMessage = data.detail.map((e) => {
            const field = e.loc?.join('.') || 'field'
            return `${field}: ${e.msg || 'validation error'}`
          }).join('; ')
        } else if (data?.detail) {
          errorMessage = String(data.detail)
        } else if (data?.message) {
          errorMessage = String(data.message)
        }
      } else if (err && typeof err === 'object' && 'message' in err && typeof err.message === 'string') {
        errorMessage = err.message
      }
      
      setError(errorMessage)
      toast.error(errorMessage)
    }
  }

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h2 className="auth-title">Вход в систему</h2>
        <p className="auth-subtitle">Войдите в свой аккаунт для продолжения</p>

        {error && (
          <Alert variant="destructive" className="mb-4">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="auth-form space-y-4">
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input
                      type="email"
                      placeholder="your@email.com"
                      disabled={form.formState.isSubmitting}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Пароль</FormLabel>
                  <FormControl>
                    <Input
                      type="password"
                      placeholder="••••••••"
                      disabled={form.formState.isSubmitting}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Минимум 8 символов
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <Button
              type="submit"
              className="w-full"
              disabled={form.formState.isSubmitting}
              isLoading={form.formState.isSubmitting}
            >
              {form.formState.isSubmitting ? 'Вход...' : 'Войти'}
            </Button>
          </form>
        </Form>
      </div>
    </div>
  )
}

export default LoginForm
