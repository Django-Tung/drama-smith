import { cn } from '@/utils/cn'

export interface AvatarProps {
  /** 签名 URL(`MediaPublic.signed_url`,`<img src>` 直用);null/空 → 首字母占位。 */
  src?: string | null
  /** 角色名;无图时取首字符(兼容中英文)圆形占位,并作 `<img alt>`。 */
  name: string
  /** 像素边长(正方形;默认 40)。 */
  size?: number
  className?: string
}

/**
 * 轻量头像(无 Radix 依赖,shadcn 风格):`src` 优先,缺省渲染 `name` 首字母圆形占位。
 * 图片走后端签名的相对 URL(内容端点不校 Bearer,token 即凭证),故无需 Authorization 头。
 */
export function Avatar({ src, name, size = 40, className }: AvatarProps) {
  const initial = (name?.trim()?.[0] ?? '?').toUpperCase()
  const boxStyle = { width: size, height: size }

  if (src) {
    return (
      <img
        src={src}
        alt={name}
        style={boxStyle}
        className={cn('shrink-0 rounded-full bg-muted object-cover', className)}
        loading="lazy"
      />
    )
  }

  return (
    <div
      role="img"
      aria-label={name}
      style={boxStyle}
      className={cn(
        'flex shrink-0 items-center justify-center rounded-full bg-muted font-medium text-muted-foreground',
        className,
      )}
    >
      <span style={{ fontSize: Math.max(12, Math.round(size * 0.4)) }}>{initial}</span>
    </div>
  )
}
