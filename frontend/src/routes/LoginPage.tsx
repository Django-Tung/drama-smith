import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { ApiError } from '@/api/errors'
import { Field } from '@/components/Field'
import { useAuthStore } from '@/stores/auth'

// 校验规则对齐后端(spec FR-U1):用户名 3–32 位字母/数字/下划线;密码 ≥8 位。
const schema = z.object({
  username: z
    .string()
    .min(3, '用户名至少 3 位')
    .max(32, '用户名至多 32 位')
    .regex(/^[A-Za-z0-9_]+$/, '仅限字母、数字、下划线'),
  password: z.string().min(8, '密码至少 8 位'),
})

type LoginValues = z.infer<typeof schema>

export function LoginPage() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const [serverError, setServerError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({ resolver: zodResolver(schema) })

  const onSubmit = async (values: LoginValues) => {
    setServerError(null)
    try {
      await login(values)
      navigate('/', { replace: true })
    } catch (err) {
      setServerError(ApiError.isApiError(err) ? err.message : '登录失败,请重试')
    }
  }

  return (
    <main className="auth-shell">
      <h1>登录</h1>
      <form onSubmit={handleSubmit(onSubmit)}>
        <Field label="用户名" error={errors.username?.message}>
          <input autoComplete="username" {...register('username')} />
        </Field>
        <Field label="密码" error={errors.password?.message}>
          <input type="password" autoComplete="current-password" {...register('password')} />
        </Field>
        {serverError ? <p className="error">{serverError}</p> : null}
        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? '登录中…' : '登录'}
        </button>
      </form>
      <p>
        还没有账号?<Link to="/register">注册</Link>
      </p>
    </main>
  )
}
