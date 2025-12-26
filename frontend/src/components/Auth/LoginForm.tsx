import { useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import * as z from 'zod'
import { toast } from 'sonner'
import {
  TextField,
  Button,
  Alert,
  Box,
  Typography,
  Stack,
  Card,
  CardContent,
} from '@mui/material'

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
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        bgcolor: 'background.default',
        p: 2,
      }}
    >
      <Card sx={{ maxWidth: 400, width: '100%' }}>
        <CardContent sx={{ p: 4 }}>
          <Stack spacing={3}>
            <Box>
              <Typography variant="h4" fontWeight={600} sx={{ mb: 1 }}>
                Вход в систему
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Войдите в свой аккаунт для продолжения
              </Typography>
            </Box>

            {error && (
              <Alert severity="error">{error}</Alert>
            )}

            <Box
              component="form"
              onSubmit={form.handleSubmit(handleSubmit)}
              sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}
            >
              <Controller
                name="email"
                control={form.control}
                render={({ field, fieldState }) => (
                  <TextField
                    {...field}
                    label="Email"
                    type="email"
                    placeholder="your@email.com"
                    disabled={form.formState.isSubmitting}
                    error={!!fieldState.error}
                    helperText={fieldState.error?.message}
                    fullWidth
                  />
                )}
              />

              <Controller
                name="password"
                control={form.control}
                render={({ field, fieldState }) => (
                  <TextField
                    {...field}
                    label="Пароль"
                    type="password"
                    placeholder="••••••••"
                    disabled={form.formState.isSubmitting}
                    error={!!fieldState.error}
                    helperText={fieldState.error?.message || 'Минимум 8 символов'}
                    fullWidth
                  />
                )}
              />

              <Button
                type="submit"
                variant="contained"
                fullWidth
                disabled={form.formState.isSubmitting}
                size="large"
              >
                {form.formState.isSubmitting ? 'Вход...' : 'Войти'}
              </Button>
            </Box>
          </Stack>
        </CardContent>
      </Card>
    </Box>
  )
}

export default LoginForm
