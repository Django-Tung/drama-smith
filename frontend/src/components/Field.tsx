import type { ReactNode } from 'react'

import { Label } from '@/components/ui/label'

interface FieldProps {
  label: string
  /** 关联控件 id(点击 label 聚焦控件)。 */
  htmlFor?: string
  error?: string
  children: ReactNode
}

/** 表单字段:Label + 控件 + 错误文案(受 React Hook Form 错误态驱动)。 */
export function Field({ label, htmlFor, error, children }: FieldProps) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {error ? <p className="text-sm font-medium text-destructive">{error}</p> : null}
    </div>
  )
}
