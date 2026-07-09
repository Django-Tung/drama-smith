import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { cn } from '@/utils/cn'

/**
 * Markdown 渲染(react-markdown + remark-gfm)。剧本版本查看用:正文常含标题 / 列表 /
 * 强调 / 引用等 markdown 结构。样式经 `components` 逐元素贴 Tailwind class(不引
 * `@tailwindcss/typography`,保持 M2「无新样式插件」);渲染器只取 `children`(及必要的
 * `className` / `href`),不透传 react-markdown 注入的 `node`,避免 React 未知属性告警。
 *
 * 本文件仅导出 `Markdown` 组件,满足 react-refresh/only-export-components。
 */
const RENDERERS: Components = {
  h1: ({ children }) => <h1 className="mb-2 mt-4 text-xl font-bold">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2 mt-3 text-lg font-bold">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1.5 mt-3 text-base font-semibold">{children}</h3>,
  h4: ({ children }) => <h4 className="mb-1 mt-2 text-sm font-semibold">{children}</h4>,
  p: ({ children }) => <p className="my-2 leading-relaxed">{children}</p>,
  ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-6">{children}</ul>,
  ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-6">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-border pl-3 text-muted-foreground">
      {children}
    </blockquote>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-primary underline underline-offset-2"
    >
      {children}
    </a>
  ),
  hr: () => <hr className="my-4 border-border" />,
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-border bg-muted px-2 py-1 text-left font-semibold">{children}</th>
  ),
  td: ({ children }) => (
    <td className="border border-border px-2 py-1 align-top">{children}</td>
  ),
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded-md bg-muted p-3 text-sm">{children}</pre>
  ),
  // 围栏代码块(带 language-xxx)由外层 <pre> 装扮;行内 code 才贴 pill 样式。
  code: ({ className, children }) => {
    if (typeof className === 'string' && className.startsWith('language-')) {
      return <code className={className}>{children}</code>
    }
    return <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">{children}</code>
  },
}

export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn('text-sm', className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={RENDERERS}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
