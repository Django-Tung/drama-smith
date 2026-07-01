import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { authApi } from '@/api/endpoints'
import { ApiError } from '@/api/errors'
import { Field } from '@/components/Field'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useAuthStore } from '@/stores/auth'

// 校验规则对齐后端(spec FR-U1):用户名 3–32 位字母/数字/下划线;
// 密码 ≥8 位且须含字母 + 数字。
const schema = z.object({
  username: z
    .string()
    .min(3, '用户名至少 3 位')
    .max(32, '用户名至多 32 位')
    .regex(/^[A-Za-z0-9_]+$/, '仅限字母、数字、下划线'),
  password: z
    .string()
    .min(8, '密码至少 8 位')
    .regex(/[A-Za-z]/, '须包含字母')
    .regex(/\d/, '须包含数字'),
})

type RegisterValues = z.infer<typeof schema>

export function RegisterPage() {
  const navigate = useNavigate()
  const setSession = useAuthStore((s) => s.setSession)
  const [serverError, setServerError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RegisterValues>({ resolver: zodResolver(schema) })

  const onSubmit = async (values: RegisterValues) => {
    setServerError(null)
    try {
      const tokens = await authApi.register(values)
      setSession(tokens)
      navigate('/', { replace: true })
    } catch (err) {
      setServerError(ApiError.isApiError(err) ? err.message : '注册失败,请重试')
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="font-serif text-xl">注册</CardTitle>
          <CardDescription>创建 drama-smith 账号</CardDescription>
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
                autoComplete="new-password"
                {...register('password')}
              />
            </Field>
            {serverError ? (
              <p className="text-sm font-medium text-destructive">{serverError}</p>
            ) : null}
            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? '注册中…' : '注册'}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            已有账号?
            <Link to="/login" className="text-primary hover:underline">
              登录
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  )
}
