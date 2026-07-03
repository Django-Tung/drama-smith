"""零成本探测:OpenAI 兼容 `GET /models` 验证鉴权 + 连通(design D6)。

litellm 无跨供应商统一的「零成本探测」(列模型/最小 ping 因 provider 而异),故自检直接打
供应商的 `/models` 端点:不发任何 chat/generate,不产生费用。无该端点的 provider →
`ProbeNotSupported`(service 降级为「跳过并告知」,FR-C3 允许降级)。

`client` 可注入(测试用 `httpx.MockTransport`);缺省自建短超时客户端。
"""

from __future__ import annotations

import httpx

from drama_smith.core.errors import ProviderAuthFailed, RateLimited
from drama_smith.llm.base import _DEFAULT_OPENAI_BASE_URL, ProbeNotSupported

_PROBE_TIMEOUT = 10.0


async def probe_models_endpoint(
    base_url: str | None,
    api_key: str,
    *,
    provider: str,
    client: httpx.AsyncClient | None = None,
) -> None:
    """`GET {base_url}/models` 零成本探测。

    - 2xx → 鉴权 + 连通正常;401/403 → `ProviderAuthFailed`;429/5xx/超时 → `RateLimited`;
    - 404(无 /models 端点)→ `ProbeNotSupported`。
    """
    url = f"{(base_url or _DEFAULT_OPENAI_BASE_URL).rstrip('/')}/models"
    owned = client is None
    transport_client = client or httpx.AsyncClient(timeout=_PROBE_TIMEOUT)
    try:
        resp = await transport_client.get(url, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.TimeoutException as exc:
        raise RateLimited("Provider timed out during connectivity probe") from exc
    except httpx.HTTPError as exc:
        raise RateLimited("Provider unreachable during connectivity probe") from exc
    finally:
        if owned:
            await transport_client.aclose()

    if resp.status_code in (401, 403):
        raise ProviderAuthFailed()
    if resp.status_code == 429:
        raise RateLimited("Provider rate-limited during connectivity probe")
    if resp.status_code == 404:
        raise ProbeNotSupported(f"{provider!r} exposes no /models endpoint for a zero-cost probe")
    if resp.status_code >= 500:
        raise RateLimited(f"Provider returned HTTP {resp.status_code}")
    # 2xx:鉴权与连通正常;不做任何生成。
