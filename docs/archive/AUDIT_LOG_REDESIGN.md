# 操作日志（审计）能力评估与改造方案

> 评估对象：`pkm_audit_events` 及其调用链
> 评估时间：2026-10-05
> 评估结论：**改造前，系统没有做到「记录每一个操作的详细日志」。它记录的是「部分业务变更的元数据」，不是操作日志。**
> 当前状态：**P0 已完成**——白名单缺陷修复，写接口覆盖率从 18/54（33%）提升到 47/54（87%）。

---

## 一、现状盘点

### 1.1 表结构

> 本节记录**改造前**的原貌，作为问题依据保留。改造后的结构见 1.3。

`pkm_audit_events`（迁移 `0003_lifecycle_history_audit`，模型 `api/app/core/models.py:309`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | uuid | 主键 |
| `user_id` | uuid | 事件归属账号 |
| `actor_type` | smallint | 1 用户 / 2 系统 |
| `action` | smallint | 1 注册 2 登录 3 退出 4 创建 5 更新 6 重命名 7 删除 8 恢复 |
| `entity_type` | smallint | 1 账号 2 会话 3 笔记 4 笔记本 5 标签 |
| `entity_id` | uuid | 动作对象 ID |
| `entity_version` | integer | 笔记版本号 |
| `details` | jsonb | **仅允许 `fields`、`affected_notes` 两个键** |
| `created_at` | timestamptz | 数据库 `now()` |

索引：`ix_audit_user_created(user_id, created_at)`、`ix_audit_entity_created(entity_type, entity_id, created_at)`。

### 1.2 改造后的表结构（迁移 `0022_audit_observability`）

`pkm_audit_events` 追加 5 列，**全部可空**，旧代码与历史数据无需迁移：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `request_id` | uuid | 由中间件注入，关联同一次 HTTP 请求的访问日志 |
| `actor_id` | uuid | 实际操作者；用户动作下等于 `user_id`，为将来 API Token 等身份预留 |
| `outcome` | smallint | 1 成功 / 2 失败；历史数据为空，语义等同成功 |
| `before` / `after` | jsonb | 变更前后快照，承载能力已就绪 |

`pkm_access_logs`（新表）——请求层全量日志，由中间件用**独立会话**写入：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | uuid | 主键 |
| `request_id` | uuid | 与 `pkm_audit_events.request_id` 对应 |
| `user_id` | uuid | 可空：未登录请求同样记录 |
| `method` / `path` | varchar | 不记录查询串与请求体 |
| `status_code` | smallint | 含 4xx / 5xx 失败请求 |
| `duration_ms` | integer | 请求耗时 |
| `ip` | varchar(45) | 兼容 IPv6 |
| `user_agent` | text | 截断至 512 字符 |
| `created_at` | timestamptz | 数据库 `now()` |

索引：`ix_access_request(request_id)`、`ix_access_user_created(user_id, created_at)`、`ix_access_created(created_at)`。

`/health/*`、`/docs`、`/openapi.json`、`/favicon.ico` 在中间件内直接跳过，避免心跳淹没日志表。

以下统计的是**业务审计**（`record_event`）的覆盖率；请求层的覆盖由 1.2 的访问日志独立承担。

### 1.3 覆盖率现状

全后端 **86 个路由，其中写操作（POST/PUT/PATCH/DELETE）54 个**。逐个核对函数体内是否存在 `record_event` 调用（含间接调用）：

| 模块 | 写接口数 | 改造前覆盖 | 改造后覆盖 |
| --- | --- | --- | --- |
| `auth` 认证 | 3 | 3 | 3 |
| `notes` 笔记 | 3 | 3 | 3 |
| `taxonomy` 笔记本/标签 | 6 | 6 | 6 |
| `archive` 回收站 | 3 | 1 | 3 |
| `m3` 多格式与文件笔记 | 10 | 3 | 7 |
| `digests` 日报周报 | 3 | 1 | 3 |
| `upload_sessions` 分块上传 | 7 | 1 | 6 |
| `conversations` AI 对话 | 6 | 0 | 6 |
| `reminders` 提醒 | 3 | 0 | 3 |
| `templates` 模板 | 3 | 0 | 3 |
| `model_connection` 模型连接 | 4 | 0 | 4 |
| `assistant` AI 助手 | 3 | 0 | 0 |
| **合计** | **54** | **18（33%）** | **47（87%）** |

业务审计仍未覆盖的 7 个接口全部是**不改变持久化状态**的调用。P1 的请求中间件已在**请求层**统一记录它们（成功与失败都记），无需逐个补 `record_event`：

- `POST /v1/assistant/ask`、`/analyze`、`/classify` — 无状态 AI 调用，已有 `pkm_assistant_traces` 记录调用链
- `POST /v1/link-drafts/{id}/analyze`、`/rewrite` — 只返回 AI 建议，不落库
- `POST /v1/notes/file-duplicate-check` — 纯查询
- `POST /v1/file-uploads/sessions/{id}/parts/{n}/url` — 仅签发预签名 URL

**敏感读操作全部无记录**：`GET /v1/notes/export`、`GET /v1/notebooks/{id}/export`、`GET /v1/notes/{id}/file`、`GET /v1/files/{storage_key}`、`GET /v1/search`。这些是数据外泄的主要通道，日志里完全查不到「谁在什么时候导出了什么」。

---

## 二、七个具体缺陷

### 缺陷 1：失败的操作不会被记录（最严重）

`record_event()` 在业务请求的同一个 `Session` 里 `db.add(...)`，随后由 `db.commit()` 一起提交（`app/core/lifecycle.py:44`）。一旦业务事务 `rollback`，**审计事件也随之消失**。

后果：越权访问、版本冲突、参数校验失败、连续登录失败——这些最需要被审计的行为，一条都不会留下。
典型链路：路由抛出 `HTTPException`（如越权 404、版本冲突 409）→ 服务层 `db.rollback()` → 本次尝试的痕迹连同审计行一起消失。

> **✅ 已修复（P1，2026-10-05）**：新增 `pkm_access_logs` 与请求中间件，日志改写**独立会话**，与业务事务彻底解耦；被拒的写请求另补一条 `outcome=FAILED` 的业务审计。验证脚本实测越权 404、版本冲突 409、重复注册 409、密码错误 401 四类失败均留痕。

### 缺陷 2：`details` 白名单过严，已导致线上功能失效 ✅ 已修复（2026-10-05）

`lifecycle.py:35` 硬编码校验：

```python
if set(safe_details) - {"fields", "affected_notes"}:
    raise ValueError("审计详情包含未登记字段")
```

而 `app/assistant/assistant.py:513` 传入了第三个键：

```python
details={"fields": ["title", "body_md", "source_url"], "source": "assistant"}
```

**实测结果：抛 `ValueError`** → 被 `assistant.py:519` 的 `except Exception` 吞掉 → 用户看到「创建笔记失败，未能保存。」，且 session 处于未回滚的脏状态。
这是已存在的 P0 功能缺陷，不只是日志问题。

**修复方式**：把「未登记键一律抛错」改为「登记键严格校验 + 未登记键放行」，并将 `source` 正式登记为受控键（值域 `assistant` / `system` / `worker`）。根本原则是**审计属于旁路逻辑，任何约束都不应击穿调用方的事务**。同时在 `assistant.py` 的两处笔记异常日志中补上 `exc` 详情——原代码只打 `type(exc).__name__`，导致这个 bug 长期无人察觉。

修复后回归验证（容器内挂载本地代码执行，8 个用例全 PASS）：原崩溃点通过、未登记键放行、非法字段名/来源/计数/类型仍被拦截。

### 缺陷 3：只记「改了哪个字段」，不记「从什么改成什么」

`notes.py:371` 记录的是：

```python
details={"fields": sorted(body.model_fields_set - {"version"})}
```

即 `{"fields": ["title"]}`——只有字段名列表，没有旧值、没有新值。
无法回答「谁把这段正文删掉了、原文是什么」这类真正的审计问题。笔记有 `NoteRevision` 全量快照可补，但提醒、模板、草稿、连接配置都既无快照也无前后值。

> **部分改善（P1，2026-10-05）**：`pkm_audit_events` 已新增 `before` / `after` 两个 JSONB 列，承载能力就绪，新增调用方可直接写入前后值。存量调用点尚未回填；由于正文属于敏感内容，建议只在**删除、批量清理等不可逆动作**上填充，且排除大字段正文。

### 缺陷 4：缺少全部请求上下文 ✅ 已修复（P1，2026-10-05）

表中没有：`request_id`、`trace_id`、`IP`、`User-Agent`、HTTP method、请求路径、响应状态码、耗时。
没有 `request_id` 就无法把「数据库里的这条审计」和「Nginx/uvicorn 里的那行访问日志」串起来，排障和取证都断链。

> **修复方式**：`pkm_audit_events` 补 `request_id` / `actor_id` / `outcome`；新增 `pkm_access_logs` 承担 method / path / 状态码 / 耗时 / IP / UA。中间件为每个响应回写 `X-Request-Id`，前端与网关可用同一个值对账。

### 缺陷 5：`entity_type` 枚举只有 5 类，无处安放新实体 ✅ 已修复

`AuditEntityType` 只有 ACCOUNT / SESSION / NOTE / NOTEBOOK / TAG。
新增的实体——提醒、模板、对话、模型连接、上传会话、网页草稿、摘要——**没有任何枚举值可用**，这是它们没被记录的根本原因之一（想记也记不了）。

### 缺陷 6：日志写入后没有可用的追溯手段 ✅ 已修复（P2，2026-10-05）

- `pkm_audit_events` 目前唯一的消费者是 `digests.py:236`（生成日报周报时当证据源）。
- 后端没有任何返回审计事件的接口，`web/src/` 全量搜索 `audit` **零命中**。

> 按产品决策，**不向终端用户提供「操作历史」界面**。但缺少追溯手段仍然是缺陷：一旦需要排查「这条笔记是谁删的」「导出失败发生在哪一步」，只能连数据库手写 SQL，且没有 `request_id` 可串联。因此改造后的查询出口只面向运维与排障，不作为产品功能交付。

已由 `api/scripts/query_audit.py` 提供（详见阶段三第 1 节）：枚举还原、按键名脱敏、强制选择器、支持相对时间。仍未新增任何 HTTP 接口——「不向用户开放」这条产品决策保持不变。

### 缺陷 7：审计记录会被业务操作删除 ✅ 已修复（P2，2026-10-05）

两处主动删除：
- `archive.py:205` — 永久删除笔记时连带 `DELETE FROM pkm_audit_events` → **已移除**
- `maintenance.py:42` — 数据清理时按账号抹除全部审计事件 → **有意保留**（账号注销属个人数据删除，理由见阶段三第 2 节）

违反审计日志「不可篡改、不可删除」的基本原则。另外 `app/ops/` 下 7 个 worker 脚本**完全没有 logging 调用**，异步任务（索引、摘要生成、网页抓取）的执行情况不可观测 → **已补齐**，并让 worker 用被处理单元 ID 作为 `request_id`，与请求层共用检索入口。

---

## 三、改造方案

### 设计原则

**不要试图让 `pkm_audit_events` 一张表承担所有职责。** 它现在是「业务变更事实表」且已被日报/周报依赖，改动风险高。采用双轨制：

| 表 | 职责 | 谁来写 |
| --- | --- | --- |
| `pkm_audit_events`（扩展） | **业务语义层**：谁对哪个对象做了什么变更，前后值是什么 | 业务代码显式调用 |
| `pkm_access_logs`（新增） | **请求层**：全量 HTTP 访问，含失败请求 | FastAPI 中间件自动写 |

两张表用 `request_id` 关联。这样既保证「每个操作都有记录」（中间件兜底），又保留了可读的业务语义。

---

### 阶段一：止血与补齐（P0，约 0.5 天）

#### 1. 修复 `details` 白名单 ✅ 已完成

`lifecycle.py` 的白名单校验从「行列」改为分级：保留已知键的类型校验，未登记键降级为放行而非抛错。

已落地实现（`api/app/core/lifecycle.py`）：

```python
AUDIT_FIELDS = {"title", "body_md", "notebook_id", "tag_ids", "taxonomy", "content_kind", "source_url"}
AUDIT_SOURCES = {"assistant", "system", "worker"}

def _validate_details(details: dict) -> None:
    """Validate registered detail keys; unknown keys pass through.

    未登记键只放行、不抛错。审计属于旁路逻辑，任何约束都不应击穿调用方的事务。
    """
    if "fields" in details and (
        not isinstance(details["fields"], list)
        or not all(field in AUDIT_FIELDS for field in details["fields"])
    ):
        raise ValueError("审计字段名称无效")
    if "affected_notes" in details and (
        not isinstance(details["affected_notes"], int) or details["affected_notes"] < 0
    ):
        raise ValueError("审计计数无效")
    if "source" in details and details["source"] not in AUDIT_SOURCES:
        raise ValueError("审计来源标记无效")
```

`source` 由此正式成为受控键，值域限定为 `assistant` / `system` / `worker` / `onlyoffice`。
同时新增 `changed` 键承载非笔记实体的变更字段名（只校验标识符形状），`fields` 保留为笔记专属的受控键。

#### 2. 扩充 `entity_type` 枚举 ✅ 已完成

```python
class AuditEntityType(IntEnum):
    ACCOUNT = 1
    SESSION = 2
    NOTE = 3
    NOTEBOOK = 4
    TAG = 5
    REMINDER = 6
    TEMPLATE = 7
    CONVERSATION = 8
    MODEL_CONNECTION = 9
    UPLOAD_SESSION = 10
    LINK_DRAFT = 11
    DIGEST = 12
    ASSISTANT_MESSAGE = 13
```

`IntEnum` 追加成员不改变已有编号，**向后兼容，无需数据迁移**。

#### 3. 补齐未覆盖的写接口 ✅ 已完成（29 个）

| 模块 | 实际补入的调用点 |
| --- | --- |
| `model_connection` | PUT（区分 create/update）、PATCH、DELETE、POST /test（新增 `AuditAction.TEST`） |
| `reminders` | POST（笔记内 + 独立两条路径）、PATCH、DELETE |
| `templates` | POST、PATCH、DELETE |
| `conversations` | POST、PATCH、DELETE、DELETE message，以及发消息（含流式，统一在 `save_question_result` 内） |
| `m3` | link-drafts 的 POST/PATCH/DELETE、OnlyOffice 回调 |
| `archive` | 永久删除与批量清理（在 `purge_archived_note` 内一处覆盖两条路由） |
| `upload_sessions` | POST /sessions、分块回执、complete（含失败/重复/校验失败各分支）、retry、retry-ingest、DELETE |
| `digests` | PUT/PATCH /settings、POST /{run_id}/retry |

安全约束：

- `model_connection` 只记录「凭据被替换」这一事实与模型名，**绝不写入 `api_key` 明文**。
- 发消息只记录提问长度、是否重问与回答来源，**不落问题原文**。
- OnlyOffice 回调无登录态，事件归属笔记所有者并标记 `actor_type=SYSTEM`。
- `purge_archived_note` 中的审计必须写在该函数已有的 `delete(AuditEvent)` 之后，否则新记录会被同批清理抹掉。

#### 4. 验证结果

新增 `api/scripts/verify_audit_coverage.py`，逐个触发各类写操作后断言每个实体都有对应的审计行与动作类型：

```
实体类型                 期望动作                               结果
------------------------------------------------------------------------
account              register                           通过
notebook             create, rename, delete             通过
tag                  create, rename, delete             通过
note                 create, update, delete             通过
template             create, rename, delete             通过
reminder             create, update, delete             通过
conversation         create, rename, delete             通过
model_connection     create, update, delete             通过
digest               update                             通过

共 24 条审计记录，覆盖 9 种实体类型。
结构化变更记录 11 条；未发现正文或凭据泄露。
```

脚本同时断言 `details` 中不含笔记正文、登录密码、`api_key` 占位串。link-draft 一项因容器内 DNS 无法解析公网地址而跳过（`_resolve_public_addresses` 主动拒绝），该路径的覆盖由静态核对确认。

既有回归全部保持通过：`verify_lifecycle`、`verify_m1`、`verify_conversations`、`check_integrity`。

---

### 阶段二：表结构升级与自动记录（P1）✅ 已完成（2026-10-05）

实际落地的文件：

| 文件 | 职责 |
| --- | --- |
| `api/alembic/versions/0022_audit_observability.py` | 加 5 列 + 2 索引，建 `pkm_access_logs`（3 索引），downgrade 可逆 |
| `api/app/core/request_context.py` | `request_id` / `actor_id` 两个 ContextVar 与读取函数 |
| `api/app/ops/audit_middleware.py` | 纯 ASGI 中间件，独立会话写访问日志与失败审计 |
| `api/app/core/lifecycle.py` | `record_event` 自动取上下文；新增 `record_failure_isolated` |
| `api/app/main.py` | 注册中间件 |

**实现与下方设计稿的三处偏差**（设计稿保留作决策记录，实际以代码为准）：

1. **中间件改为纯 ASGI，未用 `BaseHTTPMiddleware`。** 后者会介入响应体流转，对项目里的 SSE 流式接口（`/v1/conversations/{id}/messages/stream`）不友好；纯 ASGI 版本只旁听 `send` 消息、零缓冲。附带好处：纯 ASGI 中间件与业务处于同一上下文，`ContextVar` 天然传递，无需依赖 task 复制语义。
2. **失败审计统一由中间件补记，未逐个改业务 `except` 分支。** 中间件已掌握状态码与用户身份，一次覆盖全部路由；逐个改 20 多处 `except` 既易漏又易错。只有「中间件拿不到身份」的场景才需业务侧补记——目前仅登录密码错误一处（见下）。
3. **请求上下文用 `ContextVar` 显式读取，而非透传参数。** 实测 `ContextVar` 能穿过 FastAPI 的线程池（同步路由）到达业务代码，因此 29 个既有调用点**零改动**即可获得 `request_id`。

**失败留痕的两个层次**：

- 有会话 Cookie 的失败请求 → 中间件写 `pkm_access_logs`（含状态码、IP、UA），并在 `pkm_audit_events` 补一条 `outcome=FAILED`、`entity_type=REQUEST`、`entity_id=request_id` 的记录；
- 无有效 Cookie 的失败（典型如密码错误）→ 中间件只能留下匿名 401 访问日志，业务侧改用 `record_failure_isolated()` 走独立会话补记，`details={"reason": "bad_credentials"}`。该函数**不接收 `db` 参数**，避免被误用成事务内写入。

> 注意：`record_failure_isolated` 虽用独立会话，仍会带上 `request_id`——独立会话只是换事务边界，不该丢请求上下文。

#### 1. 新建迁移 `0022_audit_observability.py`

```python
revision = "0022_audit_observability"
down_revision = "0021_optional_reminder_note"

def upgrade() -> None:
    # 审计表扩展（全部可空，旧代码无需改动）
    op.add_column("pkm_audit_events", sa.Column("request_id", sa.UUID(), nullable=True))
    op.add_column("pkm_audit_events", sa.Column("actor_id", sa.UUID(), nullable=True))
    op.add_column("pkm_audit_events", sa.Column("outcome", sa.SmallInteger(), nullable=True))
    op.add_column("pkm_audit_events", sa.Column("before", postgresql.JSONB(), nullable=True))
    op.add_column("pkm_audit_events", sa.Column("after", postgresql.JSONB(), nullable=True))
    op.create_index("ix_audit_request", "pkm_audit_events", ["request_id"])
    op.create_index("ix_audit_user_action_created", "pkm_audit_events",
                    ["user_id", "action", "created_at"])

    # 全量请求日志
    op.create_table(
        "pkm_access_logs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),      # 未登录也记录
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("path", sa.String(255), nullable=False),
        sa.Column("status_code", sa.SmallInteger(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(45), nullable=True),        # 兼容 IPv6
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_access_request", "pkm_access_logs", ["request_id"])
    op.create_index("ix_access_user_created", "pkm_access_logs", ["user_id", "created_at"])
    op.create_index("ix_access_created", "pkm_access_logs", ["created_at"])

def downgrade() -> None:
    op.drop_table("pkm_access_logs")
    for col in ("request_id", "actor_id", "outcome", "before", "after"):
        op.drop_column("pkm_audit_events", col)
```

#### 2. 用 `contextvars` 贯穿 `request_id`

新建 `app/core/request_context.py`：

```python
from contextvars import ContextVar
import uuid

request_id_var: ContextVar[uuid.UUID | None] = ContextVar("request_id", default=None)
actor_id_var: ContextVar[uuid.UUID | None] = ContextVar("actor_id", default=None)
```

`lifecycle.record_event` 改为自动取值，调用方无需传——**这是让 34 个遗漏点补齐时改动最小的关键**。

#### 3. 中间件自动记录（解决「失败不留痕」）

关键点：**用独立的 Session 写日志**，不受业务事务回滚影响。

```python
# app/ops/audit_middleware.py
import time, uuid
from starlette.middleware.base import BaseHTTPMiddleware

class AuditAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = uuid.uuid4()
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-Id"] = str(request_id)
        except Exception:
            status_code = 500
            raise
        finally:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            self._write(request_id, request, status_code, elapsed_ms)
            request_id_var.reset(token)
        return response

    def _write(self, request_id, request, status_code, elapsed_ms):
        from app.core.db import SessionLocal
        from app.core.models import AccessLog
        try:
            with SessionLocal() as db:          # 独立会话，独立事务
                db.add(AccessLog(
                    request_id=request_id,
                    user_id=_extract_user_id(request),   # 从 cookie 摘要查 session，失败则 None
                    method=request.method,
                    path=request.url.path[:255],
                    status_code=status_code,
                    duration_ms=elapsed_ms,
                    ip=request.client.host if request.client else None,
                    user_agent=(request.headers.get("user-agent") or "")[:512],
                ))
                db.commit()
        except Exception:
            pass   # 日志写入失败绝不能影响主流程
```

在 `main.py` 注册：

```python
app.add_middleware(AuditAccessMiddleware)
```

> 注意：`/health/*`、`/docs`、`/openapi.json`、静态资源应在中间件里直接跳过，否则日志表会被心跳请求淹没。

#### 4. 让业务审计记录成败

在业务的 `except` 分支补一条 `outcome=FAILED` 的审计（同样走独立会话），使「尝试删除被拒」「版本冲突」等可追溯。

---

### 阶段三：治理与排障出口（P2，已完成）

> **产品决策：终端用户不需要看到自己的操作历史。** 因此不提供用户侧「活动记录」页面，也不开放 `GET /v1/activity` 之类的用户可见接口。本阶段只做让日志「可运维、可追溯」的最小工作。

#### 1. 排障查询出口（仅面向运维，不向用户开放）✅

不新增任何面向终端用户的接口。追溯通过 `api/scripts/query_audit.py` 完成，按
`--user-id` / `--entity-id` / `--request-id` / `--action` / `--entity-type` / `--failed` /
`--since` / `--until` 查询，并把 `smallint` 枚举还原成语义字符串：

```bash
# 一次请求的全链路：业务审计 + 访问日志
python -m scripts.query_audit --request-id <uuid>

# 谁动过这篇笔记（含已被永久删除的）
python -m scripts.query_audit --entity-id <uuid> --since 180d

# 某账号最近的失败动作
python -m scripts.query_audit --user-id <uuid> --failed --since 7d
```

几条有意为之的约束：

- **脱敏按键名判断，不扫值的字面量**。键名含 `key` / `password` / `token` / `secret` /
  `cipher` / `credential` 一律替换为 `***`；不扫描值是为了避免误伤正文（正文里出现
  「密码」二字不该被涂掉）。这一点在 `verify_audit_governance` 里有断言覆盖。
- **必须至少给一个选择器**（`--user-id` / `--entity-id` / `--request-id` / `--failed`），
  否则拒绝执行——防止误操作把整张表刷到终端。
- 默认 `--limit 50`，上限 2000；`--json` 用于管道处理。
- 时间参数接受相对量（`7d` / `24h` / `30m`），排障时不用现算时间戳。

#### 2. 保留与清理策略 ✅

**核心决策：访问日志有保留期，业务审计没有。** 两者价值曲线不同：

| | `pkm_access_logs` | `pkm_audit_events` |
| --- | --- | --- |
| 定位 | 取证素材 | 变更账本 |
| 增长速度 | 每请求一行 | 每写操作一行 |
| 价值衰减 | 快（回滚、并发冲突类痕迹很快失效） | 慢（事后追责时需要长期可得） |
| 保留策略 | 默认 90 天，可配 `ACCESS_LOG_RETENTION_DAYS` | **不自动过期** |

- **停止物理删除审计事件**：`archive.py` 的 `purge_archived_note` 里原本会在物理清除笔记时
  一并 `DELETE FROM pkm_audit_events`。已移除。理由：永久删除是最不可逆的动作，恰恰最需要
  留痕；审计行必须比笔记本身活得久。`entity_id` 指向已不存在的笔记是允许的——审计的职责
  本就是证明「它曾经存在过、被谁在何时删掉了」。唯一的例外是**账号注销**：`purge_accounts`
  仍会清除该账号的全部审计行，因为数据主体消失后再留存其行为记录失去正当理由。
- **访问日志清理**：逻辑在 `app/ops/maintenance.purge_access_logs`（worker 与脚本共用），
  CLI 入口 `api/scripts/purge_access_logs.py`，支持 `--dry-run` 与 `--days` 覆盖。
  分批提交，避免长事务持锁。下限 1 天——配成 0 或负数会连当天的取证素材一起删掉。
- **调度**：接入 `ingest_worker` 的每日维护窗口（北京时间 00:00，与到期归档清理同批），
  失败只记异常、不影响下一项。

#### 3. worker 侧结构化日志 ✅

后台任务没有 HTTP 请求，但同样需要一条能把「日志行—审计行—被处理实体」串起来的线索。
`core/request_context.correlation()` 让 worker 用**被处理单元自身的 ID** 作为关联 ID：

| worker | 关联 ID |
| --- | --- |
| 索引 worker | `IndexJob.id` |
| 文件识别 worker | `FileIngestJob.id` |
| 摘要 worker | `DigestRun.id` |
| 网页抓取 worker | `LinkDraft.id` |

这样 worker 产生的审计行也带上 `request_id`，与它自己的日志行一一对应。
字段名沿用 `request_id` 而非新造一个，是为了让两层日志共用同一个查询入口——
语义上「一次可追责的处理单元」，HTTP 请求是它最常见的形态，后台任务也算。

关键步骤改为 `key=value` 结构化格式，便于 grep 与后续接日志系统：

```
index_job_claimed      job=… queue_wait_seconds=… attempts=…
index_job_finished     request_id=… note=… version=… chunks=… elapsed_seconds=…
index_job_skipped      request_id=… reason=stale|superseded|not_claimed
index_job_retry        request_id=… attempts=… retry_in_seconds=… error=…
file_ingest_extract_started  request_id=… note=… extension=… bytes=…
file_ingest_finished   request_id=… note=… status=… content_changed=… blocks=… extracted_chars=…
file_ingest_abandoned  request_id=… note=… attempts=… error=…        # 达到重试上限
digest_evidence_collected  request_id=… user=… kinds=… activities=… sources=… omitted=…
digest_run_finished    request_id=… note=… sources=… body_chars=… elapsed_seconds=…
link_draft_fetch_failed / link_draft_fetch_finished  request_id=… host=… elapsed_seconds=…
```

「跳过」路径（`stale` / `superseded` / `preserved`）是刻意补的：用户报「我改了笔记但搜不到」
时，先要回答的就是「任务是不是被判定过期丢掉了」。**网页抓取日志只记域名，不记完整 URL**——
查询串可能带敏感参数。

---

## 四、改造后的能力对照

| 问题 | 改造前 | 现在 |
| --- | --- | --- |
| 谁在哪台机器上删了笔记 | 查不到 | ✅ `pkm_access_logs` 记 IP + User-Agent，按 `request_id` 关联到审计行 |
| 删除操作失败了几次 | 查不到（事务回滚） | ✅ 全部记录，含状态码；被拒写请求另补 `outcome=FAILED` 审计 |
| 这段正文被改成了什么 | 只有字段名 | ⏳ `before` / `after` 列已就绪，存量调用点待回填 |
| 用户什么时候导出了全部笔记 | 查不到 | ✅ 中间件记录全部读操作（含导出、下载、检索） |
| AI 生成笔记的过程 | 只有 trace | ✅ `request_id` 串联 trace + 审计 + 访问日志 |
| 排障时追溯一次删除 | 连库手写 SQL | ✅ `scripts/query_audit` 按 request_id / entity_id 一次取全，枚举已还原、敏感键已脱敏 |

> 用户侧不提供操作历史界面。日志的用途限定为安全追溯与问题排查。

---

## 五、工作量与验收

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| P0 ✅ | 修白名单 bug、扩枚举、补 29 个调用点 | 已完成 |
| P1 ✅ | 迁移 0022、contextvars、中间件、失败记录 | 已完成 |
| P2 ✅ | 排障脚本、保留策略、worker 日志 | 已完成 |

验证脚本（均已实际执行通过）：

| 脚本 | 验证内容 |
| --- | --- |
| `scripts.verify_audit_coverage` | 每种实体、每种 action 都有对应审计行；详情不泄露正文与凭据 |
| `scripts.verify_audit_observability` | 失败留痕；业务审计与访问日志按 `request_id` 关联；健康检查被跳过 |
| `scripts.verify_audit_governance` | 永久删除后审计完整留存；查询出口脱敏；访问日志按保留期清理且不动审计；后台任务关联 ID 落库 |

回归：`verify_lifecycle`、`verify_m1`、`verify_conversations`、`check_integrity` 全部通过。

改造涉及持久化数据结构变更，已同步更新 `docs/DATABASE_DICTIONARY.md`（新增 `pkm_access_logs` 表与 `pkm_audit_events` 的 5 个新列；并补回此前遗漏的 `action` 8 号枚举 `RESTORE`）。
