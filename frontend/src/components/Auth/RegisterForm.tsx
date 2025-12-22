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

const registerSchema = z.object({
  email: z.string().email('Некорректный email адрес'),
  password: z.string().min(8, 'Пароль должен содержать минимум 8 символов'),
  confirmPassword: z.string().min(8, 'Пароль должен содержать минимум 8 символов'),
  fullName: z.string().optional(),
  company: z.string().optional(),
}).refine((data) => data.password === data.confirmPassword, {
  message: "Пароли не совпадают",
  path: ["confirmPassword"],
})

type RegisterFormValues = z.infer<typeof registerSchema>

const RegisterForm = () => {
  const [error, setError] = useState<string | null>(null)
  const { register } = useAuth()

  const form = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      email: '',
      password: '',
      confirmPassword: '',
      fullName: '',
      company: '',
    },
  })

  const handleSubmit = async (values: RegisterFormValues) => {
    setError(null)
    
    try {
      await register(
        values.email,
        values.password,
        values.fullName || undefined,
        values.company || undefined
      )
      toast.success('Регистрация успешна! Добро пожаловать!')
    } catch (err: unknown) {
      let errorMessage = 'Ошибка при регистрации. Попробуйте еще раз.'
      
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
        <h2 className="auth-title">Регистрация</h2>
        <p className="auth-subtitle">Создайте новый аккаунт</p>

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
                  <FormLabel>Email *</FormLabel>
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
              name="fullName"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>ФИО</FormLabel>
                  <FormControl>
                    <Input
                      type="text"
                      placeholder="Иванов Иван Иванович"
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
              name="company"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Компания</FormLabel>
                  <FormControl>
                    <Input
                      type="text"
                      placeholder="ООО Компания"
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
                  <FormLabel>Пароль *</FormLabel>
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

            <FormField
              control={form.control}
              name="confirmPassword"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Подтвердите пароль *</FormLabel>
                  <FormControl>
                    <Input
                      type="password"
                      placeholder="••••••••"
                      disabled={form.formState.isSubmitting}
                      {...field}
                    />
                  </FormControl>
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
              {form.formState.isSubmitting ? 'Регистрация...' : 'Зарегистрироваться'}
            </Button>
          </form>
        </Form>
      </div>
    </div>
  )
}

export default RegisterForm
