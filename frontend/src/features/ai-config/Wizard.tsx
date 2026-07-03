import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError } from '@/api/errors'
import { modelsApi } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuthStore } from '@/stores/auth'

import { ModelConfigForm } from './ModelConfigForm'
import type { ConfigFormValues } from './schema'

type Step = 'text' | 'image' | 'video'

const STEP_ORDER: Step[] = ['text', 'image', 'video']
const STEP_LABEL: Record<Step, string> = {
  text: '文本模型',
  image: '图片模型',
  video: '视频模型',
}
const STEP_DESC: Record<Step, string> = {
  text: '必配:剧本 / 角色生成等文本能力需至少一个可用文本模型,自检通过方可继续。',
  image: '可选:角色立绘 / 场景图生成。可跳过,稍后在设置中补配。',
  video: '可选:M3 接入(本期可保存,暂不支持自检 / 生成)。',
}

function errMsg(e: unknown, fallback: string): string {
  return ApiError.isApiError(e) ? e.message : fallback
}

/**
 * 初始化向导(design D11)。文本为门禁步:创建后须自检通过才进下一步;
 * image / video 可跳过。全程不刷新 /api/me(避免 SetupPage 提前重定向),
 * 仅「完成」时刷新 → text_model_configured 翻 true → 回主页。
 */
export function Wizard() {
  const navigate = useNavigate()
  const refreshUser = useAuthStore((s) => s.refreshUser)
  const [step, setStep] = useState<Step>('text')
  const [textId, setTextId] = useState<number | null>(null)
  const [imageId, setImageId] = useState<number | null>(null)
  const [videoId, setVideoId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const finish = async () => {
    try {
      await refreshUser()
    } catch {
      /* 文本已配;刷新失败不阻塞回主页。 */
    }
    navigate('/dramas', { replace: true })
  }

  const onText = async (v: ConfigFormValues) => {
    setError(null)
    setBusy(true)
    try {
      const base_url = v.base_url || null
      let id = textId
      if (id == null) {
        const cfg = await modelsApi.create({
          purpose: 'text',
          provider: v.provider,
          model: v.model,
          api_key: v.api_key,
          base_url,
        })
        id = cfg.id
        setTextId(id)
      } else {
        await modelsApi.update(id, {
          provider: v.provider,
          model: v.model,
          base_url,
          api_key: v.api_key,
        })
      }
      try {
        await modelsApi.test(id)
        setStep('image')
      } catch (e) {
        setError(errMsg(e, '自检失败:Key 无效或被限流,请检查后重试'))
      }
    } catch (e) {
      setError(errMsg(e, '保存失败,请重试'))
    } finally {
      setBusy(false)
    }
  }

  const onImage = async (v: ConfigFormValues) => {
    setError(null)
    setBusy(true)
    try {
      let id = imageId
      if (id == null) {
        const cfg = await modelsApi.create({
          purpose: 'image',
          provider: v.provider,
          model: v.model,
          api_key: v.api_key,
          base_url: v.base_url || null,
        })
        id = cfg.id
        setImageId(id)
      } else {
        await modelsApi.update(id, {
          provider: v.provider,
          model: v.model,
          base_url: v.base_url || null,
          api_key: v.api_key,
        })
      }
      try {
        await modelsApi.test(id)
        setStep('video')
      } catch (e) {
        setError(`${errMsg(e, '自检失败')} —— 已保存,可在设置页稍后修复。`)
        setStep('video')
      }
    } catch (e) {
      setError(errMsg(e, '保存失败,请重试'))
    } finally {
      setBusy(false)
    }
  }

  const onVideo = async (v: ConfigFormValues) => {
    setError(null)
    setBusy(true)
    try {
      let id = videoId
      if (id == null) {
        const cfg = await modelsApi.create({
          purpose: 'video',
          provider: v.provider,
          model: v.model,
          api_key: v.api_key,
          base_url: v.base_url || null,
        })
        id = cfg.id
        setVideoId(id)
      } else {
        await modelsApi.update(id, {
          provider: v.provider,
          model: v.model,
          base_url: v.base_url || null,
          api_key: v.api_key,
        })
      }
      await finish()
    } catch (e) {
      setError(errMsg(e, '保存失败,请重试'))
    } finally {
      setBusy(false)
    }
  }

  const stepIndex = STEP_ORDER.indexOf(step)
  const done = (s: Step): boolean =>
    (s === 'text' && textId != null) ||
    (s === 'image' && imageId != null) ||
    (s === 'video' && videoId != null) ||
    STEP_ORDER.indexOf(s) < stepIndex

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-xl">
        <CardHeader>
          <CardTitle className="font-serif text-xl">初始化模型配置</CardTitle>
          <CardDescription>BYOK:使用你自己的 API Key,明文仅本次加密、不落本地。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <ol className="flex flex-wrap items-center gap-2 text-sm">
            {STEP_ORDER.map((s, i) => (
              <li key={s} className="flex items-center gap-2">
                <Badge variant={done(s) ? 'default' : s === step ? 'outline' : 'secondary'}>
                  {i + 1}. {STEP_LABEL[s]}
                  {s === 'text' ? ' · 必配' : ''}
                </Badge>
                {i < STEP_ORDER.length - 1 ? (
                  <span className="text-muted-foreground">›</span>
                ) : null}
              </li>
            ))}
          </ol>

          <div>
            <h3 className="font-medium">{STEP_LABEL[step]}</h3>
            <p className="text-sm text-muted-foreground">{STEP_DESC[step]}</p>
          </div>

          {step === 'text' ? (
            <ModelConfigForm
              purpose="text"
              submitLabel={textId == null ? '保存并自检' : '更新并自检'}
              submitting={busy}
              serverError={error}
              onSubmit={onText}
            >
              {textId != null ? (
                <Button type="button" variant="ghost" onClick={() => setStep('image')} disabled={busy}>
                  下一步
                </Button>
              ) : null}
            </ModelConfigForm>
          ) : null}

          {step === 'image' ? (
            <ModelConfigForm
              purpose="image"
              submitLabel={imageId == null ? '保存并自检' : '更新并自检'}
              submitting={busy}
              serverError={error}
              onSubmit={onImage}
            >
              <Button type="button" variant="ghost" onClick={() => setStep('video')} disabled={busy}>
                跳过
              </Button>
            </ModelConfigForm>
          ) : null}

          {step === 'video' ? (
            <ModelConfigForm
              purpose="video"
              submitLabel={videoId == null ? '保存' : '更新'}
              submitting={busy}
              serverError={error}
              onSubmit={onVideo}
            >
              <Button type="button" variant="ghost" onClick={() => void finish()} disabled={busy}>
                跳过 / 完成
              </Button>
            </ModelConfigForm>
          ) : null}

          {textId != null && step !== 'video' ? (
            <div className="flex justify-end border-t pt-3">
              <Button type="button" variant="outline" onClick={() => void finish()} disabled={busy}>
                完成,进入应用
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </main>
  )
}
