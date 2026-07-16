# 后端技术方案(drama-smith)

> 版本:v0.1 · 状态:实施型 · 最近更新:2026-06-30
> **定位**:承接 [`architecture.md`](./architecture.md)(契约与任务模型)与 [`database.md`](./database.md)(表结构),本文落地**后端进程内部的工程结构与模块实现**:FastAPI 分层、依赖注入与生命周期、鉴权与隔离、LangGraph 分析图、`core/llm` 接缝、任务执行器、富媒体存储、信封加密、配置与错误处理、测试。表 DDL 见 database.md;跨端契约见 architecture.md §3。
> **默认决策**:Python 3.12+ · uv · FastAPI · LangGraph · SQLAlchemy 2.0(async)+ Alembic · litellm · ruff/mypy/pytest · 进程内 asyncio 执行器 · 本地磁盘 `FileStore`。

---

## 1. 分层总览与依赖方向

```
api(接口层)        REST 路由 + /ws/tasks · 仅做参数解析、鉴权、组装响应
   │ Depends
services(应用层)    用例编排:校验门禁→调图/执行器→落库→返回;事务边界
   │
graphs/tasks(编排层) LangGraph 分析图 · 任务执行器(asyncio)· 状态机
   │
core(能力层)        llm 接缝 · crypto · config · security · logging
db / storage(设施层) SQLAlchemy 仓储(强制 user_id 过滤)· FileStore
```

**依赖方向只能向下**:上层依赖下层,`core/llm` 不反向依赖 `graphs`/`services`;`graphs`/`analysis` **绝不**直接 import litellm 或任何厂商 SDK(承接 [architecture §4.2](../architecture/system-architecture.md),NFR-2)。

---

## 2. 目录结构(职责到模块)

承接 [architecture.md §6.1](./architecture.md):

```
backend/src/drama_smith/
├── main.py               # FastAPI app、lifespan、CORS、路由挂载、启动恢复
├── core/
│   ├── config.py         # Settings(pydantic-settings):DB/JWT/MEK/存储/并发上限/CORS 源
│   ├── security.py       # JWT 签发/校验(HS256)、密码(argon2id)、刷新令牌生成/哈希
│   ├── crypto.py         # 信封加密(§8):encrypt/decrypt API Key
│   ├── logging.py        # rich handler、结构化字段、脱敏过滤器
│   └── errors.py         # 异常类 + →HTTP 错误映射(见 §10)
├── llm/                  # 供应商无关接缝(§6)
│   ├── base.py           # 统一接口:TextModel / ImageModel / VideoModel
│   ├── factory.py        # 按 model_configs 快照构造客户端
│   ├── litellm_text.py / litellm_image.py
│   └── adapters/         # 视频等自定义适配器(submit/poll,如 seedance/kling/veo)
├── db/
│   ├── base.py           # Declarative Base、async 引擎/会话工厂、JSON/TS 类型
│   ├── session.py        # get_session 依赖(请求级会话)
│   ├── models/           # ORM 模型(对应 database.md 各表)
│   └── repositories/     # 仓储:每域一个,查询强制带 user_id(§4)
├── graphs/
│   └── analysis_graph.py # LangGraph 分析图定义(本期)
├── analysis/
│   ├── state.py          # TypedDict 状态(script/characters/plotlines/conflicts/pacing/shots)
│   ├── nodes/            # 抽取角色 / 情节线 / 冲突节奏 / 切分镜 等节点
│   └── prompts.py        # 提示工程(拆解/分镜/时长约束)
├── tasks/                # 任务执行器(§7)
│   ├── executor.py       # asyncio 执行器 + 每用户信号量 + 队列
│   ├── states.py         # 状态机枚举与流转
│   ├── recover.py        # 启动扫描 running→interrupted
│   └── progress.py       # 进度回调 → 更新记录 → 广播 /ws/tasks
├── storage/
│   ├── base.py           # FileStore 接口
│   └── local.py          # 本地磁盘实现(可换 MinIO/S3 实现)
├── api/
│   ├── deps.py           # 依赖:current_user / session / executor / filestore / crypto
│   ├── auth.py · me.py · models.py · characters.py · dramas.py
│   ├── episodes.py · shots.py · media.py · video.py · render.py · export.py
│   ├── tasks.py · task_results.py
│   └── ws_tasks.py       # /ws/tasks 连接管理 + 广播
└── migrations/           # Alembic(env.py + versions/)
```

> `generation/`、`simulation/` 本期不实现,仅保留结构位。

---

## 3. 应用入口与生命周期(`main.py`)

```python
# 伪码示意
app = FastAPI(title="drama-smith", lifespan=lifespan)

@asynccontextmanager
async def lifespan(app):
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_size=..., pool_pre_ping=True)
    filestore = LocalFileStore(
        settings.media_root,
        settings.jwt_secret.get_secret_value(),   # 复用 jwt_secret 签名(无新密钥)
        settings.media_signed_url_ttl_seconds,
    )
    filestore.ensure_root()                       # 建 media_root 目录
    executor = TaskExecutor(engine, filestore, max_per_user=settings.max_tasks_per_user)
    await executor.recover_running()          # running → interrupted(§7.4)
    app.state.engine, app.state.executor, app.state.filestore = engine, executor, filestore
    yield
    await executor.shutdown()                  # 优雅停止:取消在跑协程、落 interrupted
    await engine.dispose()
```

- CORS 放行 `settings.cors_origins`(开发期含 Vite 源)。
- 路由统一 `/api` 前缀;`/ws/tasks` 单独挂载。
- 启动恢复在 lifespan 完成,保证进程重启后任务状态一致。

---

## 4. 鉴权与多租户隔离(实现)

**依赖链**(api 层 `Depends`):

```python
async def get_current_user(token: str = Depends(oauth_scheme), sec=Depends(get_security)) -> User:
    claims = sec.verify_access_token(token)     # HS256 验签、查 exp
    user = await user_repo.get(claims.sub)
    if user is None: raise NotFound
    if user.locked_until and user.locked_until > utcnow(): raise Locked
    return user
```

- **资源归属**:仓储方法签名一律 `(user_id, resource_id, ...)`,内部 `WHERE id=:id AND user_id=:user_id`,无命中→`NotFound`→接口 404([architecture §5.1](./architecture.md))。
- **登录防爆破**:`login` 失败递增 `failed_login_count`、达 5 置 `locked_until=now+15min`;成功清零([FR-U/user-auth §5](../requirements/features/user-auth.md))。
- **刷新令牌**:登录签发随机串→存哈希;`/refresh` 校验哈希 + 未过期 + 未吊销→签新 access;`/logout` 置 `revoked_at`。
- **越权富媒体**:`media` 经 `user_id` 校验 + 签名 URL/鉴权代理下发([architecture §5.6](./architecture.md))。

---

## 5. LangGraph 分析图编排(`graphs/analysis_graph.py`)

**为什么用图**:拆解是多步骤、有依赖、需流式的任务;LangGraph 提供状态流转、节点重试与流式事件,契合,且为未来生成/模拟图统一范式([architecture §4.1](../architecture/system-architecture.md))。

**状态(`analysis/state.py`)**:

```python
class AnalysisState(TypedDict):
    script: str
    preset_characters: list[Character]        # FR-A4 用户预置
    characters: list[Character]               # 融合后产出
    plotlines: list[Plotline]
    conflicts: list[Conflict]
    pacing: Pacing
    shots: list[Shot]                         # 3–15s 分镜
    aspect_ratio: str; style_preset: str | None
```

**图结构**:`START → extract_characters → (analyze_plot | analyze_conflict | analyze_pacing 可并行) → split_shots → END`。
- 节点仅消费 `core/llm` 构造的文本模型;提示工程在 `analysis/prompts.py`(含分镜 3–15s 时长约束、与预置角色融合,[analysis §5.1](../requirements/features/analysis.md))。
- **流式进度**:节点产出经 `astream_events` → 归一化为 `(progress, stage)` → 回调写 `tasks` 表 + 广播(§7.5)。
- 图由**任务执行器**(§7)在 `analyze` 任务中拉起,异常→任务 `failed`。

---

## 6. `core/llm` 供应商无关接缝(`llm/`)

**统一接口(`llm/base.py`)**:

```python
class TextModel(Protocol):
    async def chat(self, messages, **params) -> ChatResult: ...
class ImageModel(Protocol):
    async def generate(self, prompt, **params) -> list[ImageRef]: ...   # 多候选
class VideoModel(Protocol):
    async def submit(self, prompt, image=None, **params) -> str: ...    # 返回 job_id
    async def poll(self, job_id) -> VideoResult: ...                     # 异步轮询
```

- **构造(`factory.py`)**:按 `model_configs` 快照(purpose/provider/model/key/base_url/params)构造:`text`/`image` → litellm;`video` → `adapters/<provider>.py` 自定义适配器(submit/poll,协议差异大,[architecture §4.2](../architecture/system-architecture.md))。
- **解密**:构造时用 `crypto.decrypt` 取明文 Key(仅驻内存,不落日志)。
- **门禁**:`purpose` 未配置(无 active 配置)→ 抛 `ModelNotConfigured`→ 接口禁用/任务不可发起([FR-C1](../requirements/features/ai-config.md))。
- **错误映射**:401/403/鉴权失败→置 `model_configs.status=invalid` + 抛 `ProviderAuthFailed`([FR-C5](../requirements/features/ai-config.md));429/超时→有限重试或降级([FR-C6](../requirements/features/ai-config.md))。
- **自检**:`/api/me/models/:id/test` 调零成本探测(如 `models.list` 或最小 ping),不真生成([FR-C3](../requirements/features/ai-config.md))。

---

## 7. 任务执行器(`tasks/`)— 本期核心设施

承接 [architecture.md §4](./architecture.md),此处给实现要点。

### 7.1 执行器(`executor.py`)

```python
class TaskExecutor:
    def __init__(self, engine, filestore, max_per_user): ...
    async def submit(self, task: Task, work: Callable) -> int:
        await repo.set_status(task.id, "pending")
        await self._sem_per_user[task.user_id].acquire_or_queue()   # 并发上限 + 排队
        asyncio.create_task(self._run(task, work))                  # 进程内协程
        return task.id
    async def _run(self, task, work):
        try:
            await repo.set_status(task.id, "running")
            result = await work(progress=self._progress_cb(task.id))  # work 内调图/llm/落产物
            await repo.finish(task.id, "succeeded", output_refs=result)
            await broadcaster.publish(task.id, "task.completed", ...)
        except CancelledError:
            await repo.finish(task.id, "canceled")                   # 已落地产物保留
        except Exception as e:
            await repo.finish(task.id, "failed", error=map_error(e))
```

- **并发**:`asyncio.Semaphore(max_per_user)` 按用户限流(默认 3–5);全局协程上限保护;超限留 `pending` 排队。
- **`work` 闭包**:由 services 层注入,封装具体业务(优化/拆解/图片/视频/合并),执行器只管调度与状态,不耦合业务。

### 7.2 状态机(`states.py`):`pending→running→{succeeded|failed|canceled|interrupted}`,流转经仓储原子更新。

### 7.3 取消/重试/重做:`cancel` → `asyncio.Task.cancel()`(协作式);`retry` → 新建任务复用 `input_snapshot`;单步重做走 `media`/`video` 端点各自提交。

### 7.4 启动恢复(`recover.py`):`UPDATE tasks SET status='interrupted', error={code:'restart_interrupted'} WHERE status='running'`([architecture §4.4](./architecture.md))。

### 7.5 进度广播(`progress.py` + `api/ws_tasks.py`):进度回调 → 更新 `tasks` 表 → 经 `Broadcaster` 推送给该用户 `/ws/tasks` 订阅者;WS 不可达不影响记录(REST 轮询可读)。

---

## 8. 富媒体存储(`storage/`)

**接口(`base.py`)**(`runtime_checkable` Protocol;以 `media_id` 为签名主键,而非 storage_key):

```python
class FileStore(Protocol):
    def save(self, user_id: int, data: bytes, *, ext: str, content_type: str) -> tuple[str, int]: ...  # -> (storage_key, size_bytes)
    def read(self, storage_key: str) -> bytes: ...
    def delete(self, storage_key: str) -> None: ...
    def sign(self, media_id: int) -> tuple[str, int]: ...      # -> (token, exp);HS256 {sub=media_id, exp}
    def verify(self, token: str, media_id: int) -> bool: ...    # 校签名 + sub == media_id + 未过期
    def build_signed_url(self, media_id: int, token: str, exp: int) -> str: ...  # -> /api/media/<id>/content?token=&exp=
    def ensure_root(self) -> None: ...                          # 建根目录
```

- **本地实现(`local.py`,`LocalFileStore(media_root, secret, ttl_seconds)`)**:按 `<media_root>/<user_id>/<yyyy>/<mm>/<uuid>.<ext>` 落盘;`storage_key` = 相对根的路径;`save` 顺带写文件并返回 `(key, size_bytes)`。
- **签名 URL(D10)**:`sign` 以 HS256 签 `{sub: media_id, exp: now+ttl}`,**复用 `jwt_secret`**(无新密钥);`build_signed_url` 拼相对 `/api/media/<id>/content?token=&exp=`。内容端点 `verify` 通过即放行(token 即凭证,不校 Bearer / 不查 user),响应带 `Cache-Control: private, max-age=60`。
- **上传约束**:硬上限 `media_upload_max_bytes`(默认 10MB)→ 超限 413;Pillow 解码失败 / 非图 → 422;超 1MiB(软阈值)递降 JPEG 质量重压缩。视频体积大,记 `size_bytes` + 配额(M3+)。
- **多候选 + 单选**:`media` 表同 owner 多行,新行 `selected=1` 时事务内翻同 owner 旧行为 0;**DB 层以生成列 `selected_key` + UNIQUE 保证每组至多一条 selected**(镜像 `model_configs.active_key`,见 [database §3.7](./database.md))。
- **迁移对象存储**:仅新增 `S3FileStore`/`MinioFileStore`,`media.storage_provider`/`storage_key` 不变;`sign`/`verify` 契约不变。

---

## 9. API Key 信封加密(`core/crypto.py`)

承接 [database.md §6](./database.md):

```python
def _seal(key: bytes, data: bytes) -> bytes:            # 自包含 blob = nonce‖ct‖tag
    nonce = os.urandom(12)                               # GCM 推荐 96-bit nonce
    return nonce + AESGCM(key).encrypt(nonce, data, None)
def _open(key: bytes, blob: bytes) -> bytes:             # 拆 12B nonce 后解密(验 tag)
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ct, None)
def encrypt(plaintext: str, mek: bytes) -> Envelope:    # -> (key_blob, dek_blob)
    dek = os.urandom(32)
    return Envelope(
        key_blob=_seal(dek, plaintext.encode()),         # DEK 加密明文 Key
        dek_blob=_seal(mek, dek),                        # MEK 封 DEK(信封)
    )
def decrypt(env: Envelope, mek: bytes) -> str:
    dek = _open(mek, env.dek_blob)
    return _open(dek, env.key_blob).decode()
```

- MEK 经 `get_mek()` 读 `Settings.mek`(env `DS_MEK`,base64 32B),不入库/日志/OpenAPI;`model_configs` 存两个**自包含 blob** 列 `api_key_ciphertext`/`dek_ciphertext`(各含 nonce,无单独 iv 列,A2)+ `api_key_masked` 脱敏串(m2)。
- 展示脱敏:`mask_key(key) = key[:3] + "…" + key[-4:]`(< 8 位回退 `…`);写时落 `api_key_masked`,读路径不碰 MEK、不解密。

---

## 10. 配置与错误处理

**配置(`core/config.py`)**:`pydantic-settings.BaseSettings`,字段含 `database_url`、`jwt_secret`、`jwt_access_ttl`(15m)、`refresh_ttl_days`(7)、`mek`(env `DS_MEK`,base64 32B)、`media_root`、`media_signed_url_ttl_seconds`(300)、`media_upload_max_bytes`(10MB)、`cors_origins`、`max_tasks_per_user`、`max_global_workers`、`login_max_failures`(5)、`login_lock_minutes`(15)。敏感字段标 `SecretStr`、不入 schema。

**错误(`core/errors.py` + 全局异常处理)**:领域异常 → [architecture §3.2](./architecture.md) 错误格式。

| 异常 | HTTP | `code` |
|------|------|--------|
| `Unauthenticated` | 401 | `unauthenticated` |
| `Forbidden` / 越权 | 404 | `not_found`(不泄露存在) |
| `Validation` | 422 | `validation_error` |
| `ModelNotConfigured` | 409 | `model_not_configured` |
| `ProviderAuthFailed` | 502(并标 invalid) | `provider_auth_failed` |
| `RateLimited`(供应商 429) | 502 | `rate_limited` |
| `QuotaExceeded`(用户并发/配额) | 429 | `quota_exceeded` |
| `TaskNotCancelable` | 409 | `invalid_state` |
| 其他未捕获 | 500 | `internal_error` |

---

## 11. 测试策略

- **分层**:`tests/unit`(core/crypto、security、states、prompts、仓储查询)、`tests/integration`(端到端用例、任务执行器、WS)、`tests/llm`(接缝假实现)。
- **`core/llm` 替身**:测试用 `FakeTextModel`/`FakeImageModel`/`FakeVideoModel`(确定输出),不真调供应商;自检/生成行为用替身验证。
- **数据库**:MySQL 一律经 env 配置(`DS_DATABASE_URL`/`DS_TEST_DATABASE_URL`)注入;`tests/conftest.py` session 夹具自动 `CREATE DATABASE`(`<db>_test`)+ `alembic upgrade head`,每用例 `TRUNCATE` 隔离(CI / 本地同源,DSN 由环境提供,不另起 testcontainers / docker-compose)。
- **任务执行器**:用假 LLM + 内存/临时 FileStore,验证状态机、取消、恢复(`recover` 单测)。
- **隔离用例**:构造两用户数据,断言跨用户访问 404。
- **质量门**:`ruff check`、`mypy`、`pytest --cov`(核心模块覆盖率阈值)。

---

## 12. 待定 / 后续

- 视频适配器的**统一轮询抽象**(超时、退避、最大轮询次数)随首批接入供应商定。
- WS 鉴权:**子协议** vs **query token**(安全权衡,见 [architecture §7](./architecture.md))。
- 多实例部署时执行器外移到队列(Celery/RQ),`executor.submit` 接口预留。
- 结构化日志升级 structlog / 接链路追踪。
