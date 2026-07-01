import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { ApiError } from '@/api/errors'
import { Field } from '@/components/Field'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
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
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="font-serif text-xl">登录</CardTitle>
          <CardDescription>登录到 drama-smith</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <Field label="用户名" htmlFor="username" error={errors.username?.message}>
              <Input id="username" autoComplete="username" {...register('username')} />
            </Field>
            <Field label="密码" htmlFor="password" error={errors.password?.message}>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                {...register('password')}
              />
            </Field>
            {serverError ? (
              <p className="text-sm font-medium text-destructive">{serverError}</p>
            ) : null}
            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? '登录中…' : '登录'}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            还没有账号?
            <Link to="/register" className="text-primary hover:underline">
              注册
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  )
}
