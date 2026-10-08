# 接口设计：M1–M3

状态：2026-10-05。M2 已由项目负责人确认验收。M3 的主要接口已实现，集成验收已于 2026-10-05 在隔离环境完成（唯余真实公网网页抓取因环境 DNS 污染未验证）；验收结果见 [M0 与 M3 验收记录](ACCEPTANCE_M0_M3.md)。所有业务路径以 `/v1` 开始，没有 `/api` 前缀。JSON 使用 UTF-8，ID 为 UUID 字符串，时间为带时区的 ISO 8601 字符串。M0 的 `/health/*`、`/docs` 和 `/openapi.json` 保持独立。本文的“已实现”表示当前后端提供该接口；未验收功能会明确标注。除三阶段必做接口外，本文也登记回收站、笔记模板、Markdown 图片引用、日报/周报与提醒、开发环境调用链等扩展功能接口，逐项阶段归属见 [功能全量清单与阶段对照](FEATURE_INVENTORY_2026-10.md)。

## 会话与通用错误

注册和登录成功后设置 `pkm_session` Cookie：随机 Token、`HttpOnly`、`SameSite=Lax`、有效期 7 天。数据库只保存其 SHA-256 摘要。登录态入口使用 FastAPI 自带的 `APIKeyCookie` 安全依赖，统一解析 Cookie 与声明 OpenAPI 安全方案；账号密码校验沿用 Argon2id，退出撤销服务端会话。浏览器同源请求自动附带 Cookie；后端不接受请求体中的 `user_id`。本机 HTTP 运行时 `Secure=false`；以后启用 HTTPS 时必须设置 `COOKIE_SECURE=1`。[FastAPI Cookie 安全依赖](https://fastapi.tiangolo.com/reference/security/)

本产品只有普通用户，不设管理员、角色、权限码、菜单授权或每项操作的权限矩阵。受保护业务接口统一确认已登录，再从会话取得 `user_id` 限定笔记、分类、索引、模型连接和 AI 对话；这是个人数据隔离所需的归属校验。`/health/*` 等基础健康接口不使用登录态。

| 状态码 | 含义 |
| --- | --- |
| 400 | 列表游标无效 |
| 401 | 未登录、会话过期或退出后使用旧会话 |
| 404 | 资源不存在，或属于其他账号 |
| 409 | 邮箱或分类名称重复；笔记版本过期 |
| 422 | 字段、类型、长度或查询参数校验失败 |
| 429 | 笔记助手或模型连接测试超过进程内频率限制 |
| 502 | 外部聊天模型失败、返回无效结构或无法提供可核对引用 |
| 503 | 仅基础健康接口报告数据库或 Embedding 故障；混合检索采用下述降级响应 |

错误体沿用 FastAPI 的 `{ "detail": "..." }`。删除成功返回 204，无响应体。M1 对同源本地 Web 开放，不配置跨域访问。

## CRUD 范围与约定

| 资源 | 创建 | 查询 | 更新 | 删除 | 说明 |
| --- | --- | --- | --- | --- | --- |
| 账号 | 注册 | `GET /auth/me` | 当前阶段不提供 | 当前阶段不提供 | 账号设置与删号不属于两阶段需求 |
| 笔记本 | `POST /notebooks` | 列表及单项 | `PATCH /notebooks/{id}` | `DELETE /notebooks/{id}` | 单层分类，删除后笔记转为未分类 |
| 标签 | `POST /tags` | 列表及单项 | `PATCH /tags/{id}` | `DELETE /tags/{id}` | 删除后解除关联，笔记保留 |
| 笔记 | `POST /notes` | 列表及单项 | `PATCH /notes/{id}` | `DELETE /notes/{id}` | 更新与删除要求版本号，删除为逻辑删除 |
| 模型连接 | `PUT /model-connection` | `GET /model-connection` | 同一路径 `PUT` 替换 | `DELETE /model-connection` | 每账号最多一个；不回显 Key |

资源 `id`、`user_id` 和审计时间由服务端控制；`user_id` 从登录 Cookie 解析，客户端不得提交。标题、正文、分类选择和模型连接凭据由用户在对应请求中提交。关联数据通过笔记的 `notebook_id`、`tag_ids` 一起维护，不提供 `pkm_note_tags` 的独立 CRUD。索引任务、笔记片段、修订快照和审计事件是内部数据；AI 对话消息只经专用的会话与消息接口读写，不提供通用消息 CRUD。

## 账号与会话

| 方法与路径 | 请求 | 成功响应 |
| --- | --- | --- |
| `POST /v1/auth/register` | `{ "email": "a@example.com", "password": "至少10字符" }` | 201，`{ "id": "UUID", "email": "a@example.com" }` 并设置 Cookie |
| `POST /v1/auth/login` | 同上 | 200，同上并设置新 Cookie；凭证错误返回 401 |
| `POST /v1/auth/logout` | Cookie | 204，撤销当前会话并清除 Cookie |
| `GET /v1/auth/me` | Cookie | 200，账号 ID 与邮箱 |

邮箱以小写保存；响应从不包含密码哈希或会话 Token。

账号资源当前支持注册创建和查询本人信息；登录是创建会话的动作，退出是撤销当前会话的动作。两阶段暂不提供个人资料修改、改密、账号删除或会话列表 API。会话表只用于服务端验证与撤销 Cookie，不开放通用会话 CRUD。

## 笔记本与标签 CRUD

笔记本和标签均提供集合读取、单项读取、新建、改名和逻辑删除。所有响应只包含 `{id,name}`；集合按名称升序返回。

| 方法与路径 | 请求 | 成功响应 |
| --- | --- | --- |
| `GET /v1/notebooks` | 无 | 200，`[{"id":"UUID","name":"项目"}]` |
| `GET /v1/notebooks/{id}` | 本人活跃笔记本 ID | 200，`{"id":"UUID","name":"项目"}` |
| `POST /v1/notebooks` | `{"name":"项目"}` | 201，创建后的对象 |
| `PATCH /v1/notebooks/{id}` | `{"name":"项目归档"}` | 200，更新后的对象 |
| `DELETE /v1/notebooks/{id}` | 本人活跃笔记本 ID | 204，无响应体 |
| `GET /v1/tags` | 无 | 200，`[{"id":"UUID","name":"待复习"}]` |
| `GET /v1/tags/{id}` | 本人活跃标签 ID | 200，`{"id":"UUID","name":"待复习"}` |
| `POST /v1/tags` | `{"name":"待复习"}` | 201，创建后的对象 |
| `PATCH /v1/tags/{id}` | `{"name":"已复习"}` | 200，更新后的对象 |
| `DELETE /v1/tags/{id}` | 本人活跃标签 ID | 204，无响应体 |

名称前后空格会移除；笔记本名称最多 120 字符，标签名称最多 80 字符，空名称返回 422。同账号活跃分类重名返回 409；跨账号、已删除或不存在的 ID 返回 404。删除使用 `deleted_at`，已删除名称可以再次使用。删除笔记本后活跃笔记保留且 `notebook_id=null`；删除标签后活跃笔记保留且标签关联解除。受影响笔记的修订版本递增并记录快照，不重建内容向量。

## 笔记模板

内置的随笔、每日一记、工作纪要和课程摘要由前端提供。用户导入的 Markdown 模板按当前账号保存在 `pkm_note_templates`，可在新建笔记时预览、复用、重命名或删除。模板只作为草稿初始标题和正文，不会直接创建笔记；选择模板后还需确认，真正的笔记仍通过既有笔记创建接口保存。

| 方法与路径 | 请求 | 成功响应 |
| --- | --- | --- |
| `GET /v1/note-templates` | 无 | 200，当前账号模板数组 |
| `POST /v1/note-templates` | `{ "name": "周报", "title": "工作周报", "body_md": "## 本周进展\\n" }` | 201，创建后的模板 |
| `PATCH /v1/note-templates/{id}` | `{ "name": "项目周报" }` | 200，更新后的模板 |
| `DELETE /v1/note-templates/{id}` | 当前账号模板 ID | 204，无响应体 |

模板名称最长 100 字符，标题最长 240 字符，Markdown 正文最长 100000 字符。同一账号内模板名称唯一，重名返回 409；其他账号的模板 ID 按不存在处理并返回 404。模板不会写入审计正文、笔记索引或搜索结果。

## 笔记

笔记 API 覆盖 CRUD。列表摘要省略正文；单项读取返回完整笔记。创建与更新时分类可选，服务端逐项校验笔记本和标签均属于当前账号且处于活跃状态。

| 方法与路径 | 请求与查询 | 成功响应 |
| --- | --- | --- |
| `POST /v1/notes` | `title` 必填；`body_md` 可空字符串；`notebook_id` 可空；`tag_ids` 数组 | 201，完整笔记 |
| `GET /v1/notes` | `limit` 1–100（默认 30）、`cursor`、`notebook_id`、`unclassified=true`、`tag_id`、`q`、`updated_desc`（默认 true） | `{ "items": [笔记摘要], "next_cursor": "UUID或null" }` |
| `GET /v1/notes/{id}` | 本人笔记 ID | 200，完整笔记 |
| `PATCH /v1/notes/{id}` | 必填 `version`，可选 `title`、`body_md`、`notebook_id`、`tag_ids` | 200，更新后的完整笔记；版本冲突返回 409 |
| `DELETE /v1/notes/{id}?version=N` | 必填当前版本 | 204；版本冲突返回 409 |

完整笔记格式：`{id,title,body_md,notebook_id,tag_ids,version,index_status,created_at,updated_at}`。列表摘要不包含 `body_md`。标题最长 240 字符，Markdown 正文最长 100000 字符，每条笔记最多 20 个标签。创建时版本为 1；每次成功 PATCH 版本递增。`index_status` 为 `pending`、`ready` 或 `error`，不影响笔记保存和关键词搜索。

创建请求示例：

```json
{
  "title": "复习计划",
  "body_md": "每周整理一次本周笔记。",
  "notebook_id": "UUID 或 null",
  "tag_ids": ["UUID"]
}
```

更新使用部分更新语义，但必须携带当前 `version`：未传字段保持原值；传 `notebook_id: null` 清除笔记本；传 `tag_ids: []` 清空标签。标题、正文、笔记本和标签一起在一个事务中保存，成功后返回完整笔记，修订版本加一并创建修订快照。只有标题或正文实际变化时，内容版本才递增并创建/更新合并索引任务；分类变更不重新计算向量。索引任务在最近一次内容保存 8 秒后才可领取。正文与标题不能用 `null` 清空；正文使用空字符串，标题必须为非空字符串。

```json
{
  "version": 3,
  "title": "复习计划（更新）",
  "notebook_id": null,
  "tag_ids": []
}
```

删除请求为 `DELETE /v1/notes/{id}?version=3`。版本不匹配返回 409；删除成功设置 `deleted_at`，不物理删除正文或修订。删除后列表、详情和搜索均不可见，再次读取或删除返回 404。

删除记录 `deleted_at`，保留内容和修订快照供未来回收站使用。删除后直接读取、列表与搜索均不可见，再次删除返回 404。当前没有恢复或永久删除接口；数据库中的 `pkm_note_revisions` 与 `pkm_audit_events` 也不对外开放。每次成功创建或编辑保存一份当前版本快照，审计只保存动作和有限元数据，不复制正文或凭据。

列表 `q` 对当前标题和正文做字面子串查询；筛选以交集生效。`cursor` 指上一页末尾笔记 ID，排序使用更新时间与 ID 作为稳定次序。筛选条件改变后应从第一页开始。
`unclassified=true` 只返回未加入笔记本的笔记；与 `notebook_id` 同时传入时以 `unclassified` 为准。

## 搜索

`GET /v1/search?q=文本&mode=keyword|hybrid&notebook_id=UUID&tag_id=UUID&limit=20`。`q` 最长 150 字符，`mode` 默认 `keyword`，`limit` 为 1–50。筛选条件同列表。返回：

```json
{
  "semantic_status": "ready",
  "items": [{
    "note_id": "UUID",
    "title": "示例笔记",
    "notebook_id": null,
    "version": 2,
    "source_field": "body",
    "start_offset": 12,
    "end_offset": 48,
    "snippet": "来自当前版本的原文片段",
    "match_source": "keyword",
    "score": 0.0164,
    "updated_at": "2026-10-01T19:00:00+00:00"
  }]
}
```

`source_field` 为 `title` 或 `body`，位置为原文 Unicode 码点的 `[start_offset,end_offset)`；前端点击结果读取当前笔记，并在编辑器中定位对应位置。`match_source` 为 `keyword`、`semantic` 或 `both`。关键词模式的 `semantic_status` 是 `not_requested`。混合模式优先返回当前账号当前版本的关键词与向量结果，按倒数排名融合；模型不可用时仍返回 200、关键词结果和 `semantic_status="unavailable"`，前端明确提示降级。无结果时 `items=[]`，不生成答案或虚构引用。

## 内容导出

| 方法与路径 | 行为 | 成功响应 |
| --- | --- | --- |
| `GET /v1/notes/{id}/export` | 导出当前账号的一篇活跃笔记 | 按当前已保存版本格式返回附件；不添加系统元数据 |
| `GET /v1/notebooks/{id}/export` | 导出当前账号一个笔记本 | ZIP 附件，包含该笔记本的当前内容 |
| `GET /v1/notes/export` | 导出当前账号全部活跃笔记 | ZIP 附件，按笔记本分目录；不添加 README 或清单文件 |

服务端只查询会话账号的笔记，不包含逻辑删除的笔记；跨账号 ID 返回 404。归档内的内容只使用原文件或正文，重名以序号区分。导出只读已保存版本，前端发现当前编辑内容未保存时会提示用户。

## 一致性与后续边界

搜索结果中的 `note_id`、`version` 和偏移只对当时版本有效；用户打开结果时读取最新笔记，若版本已变化，应提示重新搜索。聊天模型、Agent、API Key、建议接口及持久化会话的知识库问答均已实现；问答以笔记为首要依据，证据充分性不足时回退到模型通用知识，并通过 `answer_source` 区分知识库、混合回答和模型知识。引用使用相同的服务端核验规则，见 [M2 接口与数据设计](M2_DESIGN.md)。

`0004` 已按早期两阶段收缩方案实施（方案原文已归档，现行结构与约束以 [数据库设计](DB_DESIGN.md) 为准）：分类接口保持现有请求与响应，不增加分类版本字段。`user_id` 仍只取自会话，关联 UUID 在服务事务内按账号和活跃状态核验，跨账号或不存在的引用返回 404。数据库的枚举列存 `smallint` 数字代码，后端以 `IntEnum` 映射；API 的 `index_status`、`source_field` 等响应仍输出原有语义字符串。持久化对话保存用户问题和助手回答、引用快照及检索状态；旧版 `/v1/assistant/ask`、分析和分类建议接口仍即时返回，不保存其调用记录。该对话功能复用现有消息 JSONB，不新增表或数据库字段。Markdown 导出不新增表或数据库字段。

## 路由总览

### 笔记日报、周报和提醒

| 路径 | 用途 |
| --- | --- |
| `GET/PUT/PATCH /v1/digests/settings` | 读取或保存当前账号的日报、周报开关和北京时间计划；`PATCH` 只更新提供的字段，更新从下一个计划时间生效 |
| `GET /v1/digests`、`POST /v1/digests/{run_id}/retry` | 查询本人的报告任务，支持 `kind=daily/weekly`、`limit`、`offset`，返回 `next_offset`、`note_active`、`note_archived`；只重试失败且尚未生成笔记的任务 |
| `POST /v1/reminders` | 创建一次性提醒；`note_id` 可省略以创建独立提醒，提供时须是本人的活跃笔记 |
| `POST /v1/notes/{note_id}/reminders` | 为本人的一篇活跃笔记创建一次性提醒 |
| `GET /v1/reminders`、`PATCH/DELETE /v1/reminders/{reminder_id}` | 查询未完成或全部提醒，可按 `from_at`/`to_at` 查询月历，支持 `limit`/`offset` 分页；完成、重新开启、延期、取消；删除来源笔记后隐藏关联提醒 |
| `GET /v1/workbench` | 返回独立模块预览：`reminders` 为按到期时间升序的最多三条未完成提醒（包含未来提醒）；`latest_daily`、`latest_weekly` 分别为最新日报、周报任务及原笔记状态，包含 `kind`、从已保存正文提取的 `excerpt` 和可选三级主题标题 `topics`；生成中或失败时不返回旧正文预览；`archive` 为按自动清除时间升序的最多三条归档笔记；`recent_note` 为最近更新的活跃笔记。保留旧 `items` 聚合字段兼容既有调用 |

报告在普通笔记 API 中读取、编辑、搜索与导出；来源链接形如 `[来源笔记标题](#/notes?note={id})`，正文只出现笔记标题，不出现 `[S编号]` 等内部证据键。服务端验证引用账号和版本，来源变动后读取报告会返回 `digest_sources_changed` 供编辑器提示。

### 回收站（归档笔记）

`DELETE /v1/notes/{id}` 的笔记进入回收站，保留 30 天。归档列表复用 `pkm_notes.deleted_at`，无需新表。

| 路径 | 用途 |
| --- | --- |
| `GET /v1/notes/archive` | 列出本人已删除笔记，按删除时间倒序；`limit` 1–100（默认 100）、`cursor` 分页；每项含 `deleted_at`、`purge_at`（删除时间 + 30 天）与 `days_remaining` |
| `POST /v1/notes/archive/{note_id}/restore` | 恢复本人已删除笔记；原笔记本或标签已删除时自动降级为未分类/解除关联，必要时递增内容版本并重排队索引 |
| `DELETE /v1/notes/archive/{note_id}` | 立即永久删除单篇归档笔记及其文件、文本块、检索片段、索引任务、修订、图片引用与提醒；对象存储不可用时返回 502 |
| `POST /v1/notes/archive/purge` | 批量永久删除，请求体 `{ "note_ids": ["UUID"] }`（1–100 个）；返回 `{ "purged": [...], "failed": [{"id","error"}] }`，单项失败不影响其余项 |

永久删除是逐条独立事务执行的最不可逆动作，因此**不删除**该笔记的 `pkm_audit_events` 行；审计只在账号注销时清除。引用该笔记的其它记录按两类处理：**提醒（`pkm_note_reminders`）随笔记一并删除**——软删除阶段它被隐藏但保留，是为了让恢复笔记能把提醒带回来，走到永久删除这一步这个可逆性已不存在，而置空 `note_id` 会让它变成独立提醒重新出现在列表里；**周报运行记录（`pkm_digest_runs`）保留、只清空 `note_id`**——它是排期账本，删行会让同一 `(user_id, kind, slot_key)` 被重新排期，清空后 `/v1/digests` 返回的 `note_id`、`note_active`、`note_archived` 与悬空引用时表现一致，前端无感知。两类清理的数量记入该次删除的审计 `details`（`reminders_deleted`、`digest_runs_detached`），用于事后解释「这条报告记录为什么丢了笔记」。到期记录由 `ingest-worker` 每日 00:00（北京时间）维护窗口自动批量清除，不对外暴露接口。路径为 `/v1/notes/archive`，与 `GET /v1/notes` 的列表查询互不干扰。

### 笔记附加查询

| 路径 | 用途 |
| --- | --- |
| `GET /v1/notes/{note_id}/chunks` | 返回本人笔记当前版本的检索片段（`ordinal`、来源、Unicode 偏移与内容），用于索引排障与开发核对 |
| `GET /v1/notes/{note_id}/image-references` | 图片笔记被哪些 Markdown 笔记引用；返回 `items`、`total_notes`、`total_references`。非图片笔记返回空集 |

### 开发环境 Agent 调用链

仅在 `APP_ENV` 为 `dev`/`development`/`local` 且 `ASSISTANT_TRACE_VIEW_ENABLED=true` 时可用；其他环境一律返回 404，记录每 15 分钟清理 30 天前数据。链路只写入步骤名、耗时、状态、工具字段名、检索统计和异常类型，不保存模型输入输出、提示词或笔记正文。

| 路径 | 用途 |
| --- | --- |
| `GET /v1/dev/assistant-traces/enabled` | 查询本环境是否开启调用链记录 |
| `GET /v1/dev/assistant-traces` | 按入口、状态、时间等条件列出脱敏调用链 |
| `GET /v1/dev/assistant-traces/{trace_id}` | 读取单条调用链的步骤明细 |
| `GET /v1/dev/assistant-traces/by-message/{assistant_message_id}` | 由持久化回答消息反查产生它的调用链 |

### 路由总览：领域清单

| 领域 | 已实现路由 |
| --- | --- |
| 健康状态 | `GET /health/live`、`GET /health/ready`、`GET /health/embedding` |
| 账号与登录 | `POST /v1/auth/register`、`POST /v1/auth/login`、`POST /v1/auth/logout`、`GET /v1/auth/me` |
| 笔记本 CRUD | `GET /v1/notebooks`、`GET /v1/notebooks/{id}`、`POST /v1/notebooks`、`PATCH /v1/notebooks/{id}`、`DELETE /v1/notebooks/{id}` |
| 标签 CRUD | `GET /v1/tags`、`GET /v1/tags/{id}`、`POST /v1/tags`、`PATCH /v1/tags/{id}`、`DELETE /v1/tags/{id}` |
| 笔记 CRUD | `GET /v1/notes`、`GET /v1/notes/{id}`、`POST /v1/notes`、`PATCH /v1/notes/{id}`、`DELETE /v1/notes/{id}` |
| 笔记附加查询 | `GET /v1/notes/{note_id}/chunks`、`GET /v1/notes/{note_id}/image-references` |
| 笔记模板 | `GET/POST /v1/note-templates`、`PATCH/DELETE /v1/note-templates/{id}` |
| 回收站 | `GET /v1/notes/archive`、`POST /v1/notes/archive/{note_id}/restore`、`DELETE /v1/notes/archive/{note_id}`、`POST /v1/notes/archive/purge` |
| 搜索 | `GET /v1/search` |
| 导出 | `GET /v1/notes/{id}/export`、`GET /v1/notebooks/{id}/export`、`GET /v1/notes/export` |
| 模型连接 | `GET/PUT/DELETE /v1/model-connection`、`POST /v1/model-connection/test`，字段与行为见 [M2 设计](M2_DESIGN.md) |
| 笔记助手 | `GET/POST /v1/assistant/conversations`、`GET/PATCH/DELETE /v1/assistant/conversations/{id}`、`POST /v1/assistant/conversations/{id}/messages`、`POST /v1/assistant/conversations/{id}/messages/stream`（SSE 流式回答）；`POST /v1/assistant/ask`、`/analyze`、`/classify` 保留，详见 [M2 设计](M2_DESIGN.md) |
| 日报、周报与提醒 | `GET/PUT/PATCH /v1/digests/settings`、`GET /v1/digests`、`POST /v1/digests/{run_id}/retry`、`POST /v1/reminders`、`GET /v1/reminders`、`PATCH/DELETE /v1/reminders/{id}`、`POST /v1/notes/{note_id}/reminders`、`GET /v1/workbench` |
| 开发环境调用链 | `GET /v1/dev/assistant-traces/enabled`、`GET /v1/dev/assistant-traces`、`GET /v1/dev/assistant-traces/{trace_id}`、`GET /v1/dev/assistant-traces/by-message/{assistant_message_id}` |

## M3 接口

M2 已由项目负责人确认验收。M3 主要接口已实现，完整行为、数据流、异常、实现状态和验收见 [M3 设计](M3_DESIGN.md)。M3 集成验收已于 2026-10-05 在隔离环境完成（见 [M0 与 M3 验收记录](ACCEPTANCE_M0_M3.md)），唯余真实公网网页抓取因环境 DNS 污染未验证。

| 领域 | 开发路径 | 契约方向 |
| --- | --- | --- |
| 文件型笔记 | `POST /v1/notes/upload`、`POST /v1/notes/file-duplicate-check`、`GET/PUT /v1/notes/{id}/file` | 上传前按账号做 SHA-256 重复预检，服务端完成时复核；保存文件时保留原件和不可变版本，按登录账号隔离；DOC/XLS 转换需要显式确认及文档服务。 |
| 分块上传会话 | `POST/GET /v1/file-uploads/sessions`、`GET /v1/file-uploads/sessions/{id}`、`POST .../parts/{n}/url`、`PUT .../parts/{n}/receipt`、`POST .../complete`、`POST .../retry`、`POST .../retry-ingest`、`DELETE .../{id}` | 单文件上限 25 MiB、5 MiB 分块直传对象存储；按账号与幂等键去重；未完成会话 24 小时后中止清理；`retry` 重试会话，`retry-ingest` 重试识别或索引。 |
| 文档编辑服务 | `GET /v1/notes/{id}/editor-config`、`POST /v1/integrations/onlyoffice/callback/{id}`、`GET /v1/files/{storage_key}` | 签发短期文件链接与编辑配置；服务端验证回调 token 和文档版本。 |
| 内容导出 | `GET /v1/notebooks/{id}/export`；沿用 `GET /v1/notes/{id}/export` 与 `GET /v1/notes/export` | 单篇为当前文件格式，笔记本与全部为 ZIP；正文不注入 YAML，ZIP 无 README 或清单。 |
| 网页草稿 | `GET/POST /v1/link-drafts`、`GET/PATCH/DELETE /v1/link-drafts/{id}`、`POST /v1/link-drafts/{id}/analyze`、`POST /v1/link-drafts/{id}/rewrite`、`POST /v1/link-drafts/{id}/publish` | POST 先保存 `pending` 草稿；抓取 Agent 在后台完成后状态变为 `ready` 或 `failed`，客户端可通过 GET 查询。分析返回可单独采纳的摘要、要点和行动建议；发布确认后才成为 Markdown 笔记。 |
| 搜索与引用 | 沿用 `GET /v1/search` 及 M2 Agent 路径 | 文件型结果增加类型、内容版本与段落/单元格/页码位置；Markdown 现有位置字段保持兼容。 |

当前导出已切换为内容导出，不再附加 YAML front matter 或 ZIP README；上述 M3 接口均已通过集成验收，唯余公网网页真实抓取一项因环境 DNS 污染未验证。


## AI 对话安全修复兼容扩展

`POST /v1/assistant/ask` 与对话 `messages` / `messages/stream` 请求增加可选UUID `request_id`、`confirmation_id` 和整数 `selection`。确认仅消费服务器已有提议；不接受客户端差异、目标版本或新增权限。两个入口均限制10000字符，纯空白422；资料总上下文超过64000 UTF-8字节拒绝而不截断当前请求。

回答保留 answer、answer_source、semantic_status、citations；新增 retrieval_status（not_requested/no_results/retrieved/error；旧消息unknown）、pending_operation（selection候选或confirmation差异）、operation_receipts（提交后created/updated回执）。引用公开字段仅 citation_id、note_id、title；内部原文、偏移与版本不返回。note_id供浏览器打开已鉴权来源，模型只见本轮N#/S#。

SSE事件类型保持status、delta、complete、error。delta来自已校验且已成功保存的完整答案；提交后断流可用同一request_id重试恢复，不再次写笔记。相同编号不同请求409，越权和不存在404，输入/预算422，版本/上下文冲突409，模型空输出或无效输出502，限流429。普通笔记接口语义不变。

## AI 对话通用数据边界（2026-10-08 修复）

问答正文、历史读取、请求幂等重放和 SSE 结果采用当前用户响应投影。`messages[].content` 不再是任意对象，而是用户文本、助手回答或兼容旧版检索结果三种显式内容类型；引用、候选、差异预览及回执也具有完整嵌套类型。未登记的历史服务器扩展字段不返回。模型工具信封逐层核验字段与实际类型，不接受以对象替换标题等文本字段，也不开放任意 metadata 容器。正文中的 JSON、HTML、代码与 UUID 保持文字资料的语义。

助手生成文本不能凭核验器自行标注 general、interaction 或 uncertain 就绕过个人笔记依据检查。需要笔记依据时保留有效引用支持的结论；未支持的附加陈述剔除，无有效结论则使用服务器的证据不足提示。明确请求一般建议时仍可提供通用补充。内部控制元数据仅供服务器验证或具体用途的来源卡片使用，不进入自然语言回答、历史模型上下文或摘要。

正文来源证明只存服务器内部，用于后续历史读取时核验账号、版本及原文摘要，保留合法文档型文本；该证明不属于公开响应。读取历史采用当前规则投影，不重写已有消息原文。明确提供标题和正文的新建请求可由服务端按解析后的数量直接暂存，仍经既有原子事务、归属及幂等检查提交，成功提示来自回执。

本段描述源码行为，发布与验收状态以 `test-results/assistant-security-remediation/general-fix-2026-10-08/REPORT.md` 为准。

历史引用卡片在页面返回、模型上下文和幂等重放时重新核验 UUID、当前账号及未删除状态；不可信旧标题由实际笔记标题替换，移除无效卡片后来源类别降为 unknown。此检查只控制资源指针，不以历史回答替代当前笔记证据。回答核验结果结构无效或依据不足时最多纠正一次；纠正仍经过引用、数值、执行状态及格式检查。模型连接失败直接返回服务错误，不把连接故障描述为笔记证据不足。
