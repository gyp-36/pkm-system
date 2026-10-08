  # 数据库完整字段字典（M1/M2 已实施并验收；M3 集成验收完成）

仓库迁移序列已推进至 Alembic `0023_assistant_operations`（当前源码；个人运行数据库尚未执行该迁移）。M3 已逐步增加文件版本、文本块、网页草稿、分块上传会话和异步识别任务等结构；当前共 26 张业务表和 1 张迁移元数据表（其中 4 张为扩展功能表：笔记模板、Markdown 图片引用、日报/周报任务与设置、日程提醒）。M3 主要功能已实现，集成验收已于 2026-10-05 完成（唯余真实公网网页抓取因环境 DNS 污染未验证）。文件字节存入 S3 兼容 MinIO，迁移期间保留从历史 `note_files` 卷读取的能力。数据库没有外键；时间均为 `timestamptz`，UUID 主键由应用生成。

| 表 | 用途 | 物理索引数 |
| --- | --- | ---: |
| `pkm_accounts` | 账号 | 2 |
| `pkm_user_sessions` | 可撤销登录态 | 3 |
| `pkm_notebooks` | 单层笔记本 | 2 |
| `pkm_tags` | 单层标签 | 2 |
| `pkm_notes` | 当前笔记 | 3 |
| `pkm_note_templates` | 用户导入的 Markdown 笔记模板 | 3 |
| `pkm_note_tags` | 当前笔记标签关联 | 2 |
| `pkm_note_chunks` | 当前或待清理检索片段 | 3 |
| `pkm_index_jobs` | 异步向量索引任务 | 3 |
| `pkm_note_revisions` | 笔记版本快照 | 3 |
| `pkm_audit_events` | 业务动作日志 | 5 |
| `pkm_access_logs` | 请求层访问日志（含失败请求，保留 90 天） | 4 |
| `pkm_model_connections` | 本人聊天模型连接 | 2 |
| `pkm_assistant_conversations` | 持久化的本人 AI 对话 | 2 |
| `pkm_assistant_messages` | 用户问题、Agent 回答与引用快照 | 2 |
| `pkm_assistant_traces` | 开发环境 Agent 脱敏调用链 | 4 |
| `pkm_note_file_versions` | 笔记原文件不可变版本元数据 | 4 |
| `pkm_note_text_blocks` | 文件提取文本与页/段落/单元格位置 | 3 |
| `pkm_markdown_image_references` | Markdown 笔记对同账号图片笔记的引用与位置 | 3 |
| `pkm_link_drafts` | 本人网页导入草稿与抓取快照 | 3 |
| `pkm_file_upload_sessions` | 分块上传会话、幂等信息与续传状态 | 5 |
| `pkm_file_ingest_jobs` | 文件版本的异步识别与索引任务 | 3 |
| `pkm_digest_settings` | 本人日报/周报开关与北京时间计划 | 1 |
| `pkm_digest_runs` | 日报/周报任务、周期与来源快照 | 4 |
| `pkm_note_reminders` | 一次性提醒，可关联笔记或独立存在 | 3 |
| `pkm_alembic_version` | 迁移版本元数据 | 1 |

## `pkm_accounts`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4，主键 |
| `email` | `varchar(320)` | 否 | 登录邮箱，应用转小写 |
| `password_hash` | `varchar(255)` | 否 | Argon2id 哈希 |
| `created_at` | 时间 | 否 | 数据库 `now()` |
| `updated_at` | 时间 | 否 | 数据库 `now()`；更新触发器维护 |
| `deleted_at` | 时间 | 是 | 逻辑删除时间，当前无删号接口 |

索引：`accounts_pkey(id)`；`accounts_email_key(email)` 全局唯一。已删除账号仍占用邮箱。

## `pkm_user_sessions`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4，主键 |
| `user_id` | `uuid` | 否 | 会话所属账号 ID |
| `token_hash` | `varchar(64)` | 否 | 随机 Cookie Token 的 SHA-256 摘要 |
| `expires_at` | 时间 | 否 | 应用计算，当前为登录后 7 天 |
| `revoked_at` | 时间 | 是 | 退出时写入；空值表示未撤销 |
| `created_at` | 时间 | 否 | 数据库 `now()` |
| `updated_at` | 时间 | 否 | 数据库 `now()`；更新触发器维护 |

索引：`user_sessions_pkey(id)`；`user_sessions_token_hash_key(token_hash)` 唯一；`ix_user_sessions_user_id(user_id)`。每次登录新增一行，每次退出仅更新对应行；普通请求只查询，不写会话表。有效登录态还需 `revoked_at IS NULL AND expires_at > now()` 且账号未删除。

## `pkm_notebooks`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4，主键 |
| `user_id` | `uuid` | 否 | 所属账号 ID |
| `name` | `varchar(120)` | 否 | 名称 |
| `created_at` | 时间 | 否 | 数据库 `now()` |
| `updated_at` | 时间 | 否 | 数据库 `now()`；更新触发器维护 |
| `deleted_at` | 时间 | 是 | 逻辑删除时间 |

索引：`notebooks_pkey(id)`；`uq_notebooks_active_user_name(user_id,name) WHERE deleted_at IS NULL`，同账号活跃名称唯一，删除后可复用。

## `pkm_tags`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4，主键 |
| `user_id` | `uuid` | 否 | 所属账号 ID |
| `name` | `varchar(80)` | 否 | 名称 |
| `created_at` | 时间 | 否 | 数据库 `now()` |
| `updated_at` | 时间 | 否 | 数据库 `now()`；更新触发器维护 |
| `deleted_at` | 时间 | 是 | 逻辑删除时间 |

索引：`tags_pkey(id)`；`uq_tags_active_user_name(user_id,name) WHERE deleted_at IS NULL`。

## `pkm_notes`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4，主键 |
| `user_id` | `uuid` | 否 | 所属账号 ID |
| `notebook_id` | `uuid` | 是 | 当前笔记本 ID；空值为未分类 |
| `title` | `varchar(240)` | 否 | 当前标题 |
| `body_md` | `text` | 否 | Markdown 正文或文件提取出的检索文本，应用默认空字符串 |
| `content_kind` | `varchar(16)` | 否 | `markdown`、`docx`、`xlsx`、`pdf`、`png` 等 |
| `source_url` | `text` | 是 | 网页草稿发布后保留的来源地址；导出不附加该字段 |
| `version` | `integer` | 否 | 应用初值 1；笔记内容或分类变更时递增，用于并发更新与修订 |
| `content_version` | `integer` | 否 | 初值 1；仅标题或正文变化时递增，向量索引按此版本校验 |
| `index_status` | `smallint` | 否 | 应用默认 1；1 待索引、2 已索引、3 错误 |
| `created_at` | 时间 | 否 | 数据库 `now()` |
| `updated_at` | 时间 | 否 | 数据库 `now()`；用户可见变更由应用写入 |
| `deleted_at` | 时间 | 是 | 逻辑删除时间 |

索引：`notes_pkey(id)`；`ix_notes_active_user_updated(user_id,updated_at,id) WHERE deleted_at IS NULL`；`ix_notes_active_user_notebook_updated(user_id,notebook_id,updated_at,id) WHERE deleted_at IS NULL`。API 把数字状态映射回 `pending/ready/error`。

## `pkm_note_templates`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4，主键 |
| `user_id` | `uuid` | 否 | 所属账号 ID；所有读取、创建和删除均按当前会话账号校验 |
| `name` | `varchar(100)` | 否 | 模板名称，同账号唯一 |
| `title` | `varchar(240)` | 否 | 使用模板新建笔记时的初始标题 |
| `body_md` | `text` | 否 | Markdown 初始正文，应用默认空字符串，最多 100000 字符 |
| `created_at` | 时间 | 否 | 数据库 `now()` |
| `updated_at` | 时间 | 否 | 数据库 `now()`；当前模板创建后不提供编辑接口 |

索引：`note_templates_pkey(id)`；`uq_note_templates_user_name(user_id,name)` 唯一；`ix_note_templates_user_updated(user_id,updated_at)`。内置模板由前端定义，不写入此表。

## `pkm_note_tags`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `note_id` | `uuid` | 否 | 当前笔记 ID |
| `tag_id` | `uuid` | 否 | 当前标签 ID |
| `user_id` | `uuid` | 否 | 两端共同所属账号 ID |
| `created_at` | 时间 | 否 | 数据库 `now()` |

索引：复合主键 `note_tags_pkey(note_id,tag_id,user_id)`；`ix_note_tags_user_tag_note(user_id,tag_id,note_id)`。解除标签时物理删除关联，历史标签 ID 保留在修订快照。

## `pkm_note_chunks`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4，主键 |
| `user_id` | `uuid` | 否 | 所属账号 ID，检索时再次限定 |
| `note_id` | `uuid` | 否 | 来源笔记 ID |
| `note_version` | `integer` | 否 | 生成片段时的笔记内容版本，对应 `pkm_notes.content_version` |
| `ordinal` | `integer` | 否 | 同一版本内顺序，从 0 开始 |
| `start_offset` | `integer` | 否 | 原文 Unicode 起始位置，包含 |
| `end_offset` | `integer` | 否 | 原文 Unicode 结束位置，不包含 |
| `content` | `text` | 否 | 原文片段 |
| `source` | `smallint` | 否 | 应用默认 2；1 标题、2 正文 |
| `location` | `jsonb` | 是 | 原文位置，如 PDF 页、DOCX 段落或 XLSX 单元格 |
| `embedding` | `vector(1024)` | 是 | 1024 维向量 |
| `created_at` | 时间 | 否 | 数据库 `now()` |

索引：`note_chunks_pkey(id)`；`uq_chunk_position(note_id,note_version,ordinal)` 唯一；`ix_chunks_user_note_version(user_id,note_id,note_version)`。当前执行精确向量距离查询，未建 HNSW。检索只返回当前版本、本人、活跃笔记的片段；API 将 `source` 映射为 `title/body`。

## `pkm_index_jobs`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4，主键 |
| `user_id` | `uuid` | 否 | 所属账号 ID |
| `note_id` | `uuid` | 否 | 目标笔记 ID |
| `target_version` | `integer` | 否 | 待生成向量的笔记内容版本 |
| `status` | `smallint` | 否 | 应用默认 1；1 待处理、2 处理中、3 完成、4 过期 |
| `attempts` | `integer` | 否 | 应用默认 0，重试计数 |
| `last_error` | `text` | 是 | 最近错误摘要，应用截断到 500 字符 |
| `available_at` | 时间 | 否 | 可领取时间；内容编辑后延迟 8 秒，失败时指数退避 |
| `created_at` | 时间 | 否 | 数据库 `now()` |
| `updated_at` | 时间 | 否 | 数据库 `now()`；worker 写入状态变化 |

索引：`index_jobs_pkey(id)`；`uq_jobs_active_note(note_id) WHERE status IN (1,2)` 部分唯一，确保每篇笔记最多一个待处理或处理中任务；`ix_jobs_status_created(status,created_at)`。新编辑更新活跃任务的目标版本与延迟时间；领取任务使用行锁并跳过被锁行。

## `pkm_note_revisions`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4，主键；历史回填使用 `gen_random_uuid()` |
| `user_id` | `uuid` | 否 | 所属账号 ID |
| `note_id` | `uuid` | 否 | 来源笔记 ID |
| `version` | `integer` | 否 | 快照版本 |
| `title` | `varchar(240)` | 否 | 该版本标题 |
| `body_md` | `text` | 否 | 该版本完整 Markdown 正文 |
| `notebook_id` | `uuid` | 是 | 当时笔记本 ID，历史引用可已失效 |
| `tag_ids` | `uuid[]` | 否 | 当时标签 ID，应用默认空数组 |
| `created_at` | 时间 | 否 | 数据库 `now()` |

索引：`note_revisions_pkey(id)`；`uq_revision_note_version(note_id,version)` 唯一；`ix_revisions_user_note_version(user_id,note_id,version)`。此表按版本追加，不提供恢复 API；`0003` 为既有笔记仅回填迁移时的当前版本。

## `pkm_audit_events`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4，主键 |
| `user_id` | `uuid` | 否 | 事件所属账号 ID |
| `actor_type` | `smallint` | 否 | 应用默认 1；1 用户、2 系统 |
| `action` | `smallint` | 否 | 1 注册、2 登录、3 退出、4 创建、5 更新、6 重命名、7 删除、8 恢复、9 连接测试 |
| `entity_type` | `smallint` | 否 | 1 账号、2 会话、3 笔记、4 笔记本、5 标签、6 提醒、7 模板、8 对话、9 模型连接、10 上传会话、11 网页草稿、12 摘要、13 助手消息、14 请求（中间件补记的失败动作） |
| `entity_id` | `uuid` | 否 | 动作对象 ID，多实体引用；`entity_type=14` 时复用 `request_id` |
| `entity_version` | `integer` | 是 | 笔记动作的版本 |
| `request_id` | `uuid` | 是 | 迁移 0022；由请求中间件注入，关联 `pkm_access_logs` |
| `actor_id` | `uuid` | 是 | 迁移 0022；实际操作者，用户动作下等于 `user_id` |
| `outcome` | `smallint` | 是 | 迁移 0022；1 成功、2 失败；历史数据为空，等同成功 |
| `before` / `after` | `jsonb` | 是 | 迁移 0022；变更前后快照，当前仅有承载能力 |
| `details` | `jsonb` | 否 | 数据库默认 `{}`；登记键严格校验，未登记键放行 |
| `created_at` | 时间 | 否 | 数据库 `now()` |

索引：`audit_events_pkey(id)`；`ix_audit_user_created(user_id,created_at)`；`ix_audit_entity_created(entity_type,entity_id,created_at)`；`ix_audit_request(request_id)`；`ix_audit_user_action_created(user_id,action,created_at)`。不存正文、密码、Cookie Token、API Key、向量或 IP（IP 与 UA 记在 `pkm_access_logs`）。当前无面向用户的审计查询接口。

写入路径有两条：业务代码经 `record_event` 写入，**事务与业务共享，业务回滚即消失**；中间件经独立会话写入失败记录（`outcome=2`、`entity_type=14`），不受回滚影响。密码错误等无会话凭据的失败，由 `record_failure_isolated()` 走独立会话补记。

**保留策略：不设自动过期。** 与 `pkm_access_logs` 的 90 天保留期不同，审计事件是变更账本，事后追责时需要长期可得。`purge_archived_note` 物理清除笔记时**不再删除**该笔记的审计行——永久删除本身最需要留痕，`entity_id` 指向已不存在的笔记是预期行为。唯一的例外是**账号注销**：`purge_accounts` 会清除该账号的全部审计行，因为数据主体消失后再留存其行为记录失去正当理由。排障查询见 `python -m scripts.query_audit`（按 `user_id` / `entity_id` / `request_id`，枚举已还原、敏感键已脱敏），仍不提供面向用户的查询接口。

`details` 的登记键：`fields`（笔记变更字段名，值域受控）、`changed`（其他实体的变更字段名，仅校验标识符形状）、`affected_notes`（影响笔记计数，非负整数）、`source`（来源标记，取 `assistant`/`system`/`worker`/`onlyoffice`）。未登记键一律放行，避免审计约束击穿调用方事务。

## `pkm_access_logs`

请求层全量访问日志（迁移 0022）。由 API 中间件用**独立会话**写入，与业务事务解耦，因此失败请求也能留痕。

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4，主键 |
| `request_id` | `uuid` | 否 | 与 `pkm_audit_events.request_id` 对应；同时回写响应头 `X-Request-Id` |
| `user_id` | `uuid` | 是 | 从会话 Cookie 反查；未登录请求为空 |
| `method` | `varchar(8)` | 否 | HTTP 方法 |
| `path` | `varchar(255)` | 否 | 请求路径；**不记录查询串** |
| `status_code` | `smallint` | 否 | 含 4xx / 5xx 失败请求 |
| `duration_ms` | `integer` | 否 | 请求耗时 |
| `ip` | `varchar(45)` | 是 | 兼容 IPv6 |
| `user_agent` | `text` | 是 | 截断至 512 字符 |
| `created_at` | 时间 | 否 | 数据库 `now()` |

索引：`access_logs_pkey(id)`；`ix_access_request(request_id)`；`ix_access_user_created(user_id,created_at)`；`ix_access_created(created_at)`。不存请求体、查询串、Cookie 或凭据。`/health/*`、`/docs`、`/openapi.json`、`/favicon.ico` 不记录。随账号删除一并清理。

**保留期：默认 90 天**，由环境变量 `ACCESS_LOG_RETENTION_DAYS` 覆盖（下限 1 天，配成 0 或负数会被夹到 1，避免误删当天取证素材）。清理逻辑在 `app/ops/maintenance.purge_access_logs`，随 `ingest-worker` 的每日维护窗口（北京时间 00:00）执行，也可手动跑 `python -m scripts.purge_access_logs`（支持 `--dry-run` / `--days`）。这是与 `pkm_audit_events` 的关键差异：**访问日志有保留期，业务审计没有**。

## `pkm_model_connections`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4，主键 |
| `user_id` | `uuid` | 否 | 连接所属账号 ID |
| `provider` | `smallint` | 否 | `1=DeepSeek`，代码 `ModelProvider` 映射 |
| `model_name` | `varchar(120)` | 否 | 服务端允许的模型名称 |
| `base_url` | `text` | 是 | 预留；当前固定官方服务地址，此列为空 |
| `credential_ciphertext` | `bytea` | 否 | Fernet 加密的 API Key；删除时清空为零长度 |
| `credential_key_id` | `varchar(64)` | 否 | 当前为 `local-v1`，供将来密钥轮换识别 |
| `created_at` | 时间 | 否 | 数据库 `now()` |
| `updated_at` | 时间 | 否 | 数据库 `now()`；更新触发器维护 |
| `deleted_at` | 时间 | 是 | 逻辑删除时间 |

索引：`model_connections_pkey(id)`；`uq_model_connections_active_user(user_id) WHERE deleted_at IS NULL`。每账号至多一个活跃连接。主密钥位于本地 `.env.local`，不写入数据库。删除连接清空密文并记录 `deleted_at`；新连接可再次创建。

## `pkm_assistant_conversations`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4 主键 |
| `user_id` | `uuid` | 否 | 所属账号 ID |
| `title` | `varchar(120)` | 否 | 初始为“新对话”；首条问题后由服务端更新 |
| `created_at` | 时间 | 否 | 数据库 `now()` |
| `updated_at` | 时间 | 否 | 创建或消息追加时由服务端更新 |
| `deleted_at` | 时间 | 是 | 删除时间；非空时不出现在列表且不能读取 |
| `context_summary` | `text` | 是 | 长对话较早消息的派生摘要；不是原始记录或知识库证据 |
| `summary_through_message_id` | `uuid` | 是 | 摘要覆盖到的最后一条消息 ID；不设置外键，由服务校验 |
| `summary_updated_at` | 时间 | 是 | 最近一次成功生成摘要的时间 |

索引：`assistant_conversations_pkey(id)`；`ix_assistant_conversations_user_updated(user_id,updated_at,id)`。会话列表按更新时间倒序返回；支持标题编辑及软删除，删除保留消息快照。

## `pkm_assistant_messages`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4 主键 |
| `user_id` | `uuid` | 否 | 所属账号 ID，查询时再次限定 |
| `conversation_id` | `uuid` | 否 | 所属对话 ID，由服务校验账号归属 |
| `role` | `smallint` | 否 | `1=user`、`2=assistant`，映射见 `AssistantMessageRole` |
| `content` | `jsonb` | 否 | 用户为 `{text}`；新助手消息为 `{answer,citations,semantic_status,answer_source}`；兼容旧 `{items,semantic_status}` 检索快照 |
| `created_at` | 时间 | 否 | 数据库默认 `now()`；本轮双方消息由应用设置递增微秒时间 |

索引：`assistant_messages_pkey(id)`；`ix_assistant_messages_user_conversation_created(user_id,conversation_id,created_at,id)`。助手消息保存当时返回的片段、笔记版本和 Unicode 原文偏移；之后笔记变化不改写快照。

## `pkm_assistant_traces`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 调用链 UUID 主键 |
| `user_id` | `uuid` | 否 | 发起调用的账号 ID，用于开发排错定位 |
| `conversation_id` | `uuid` | 是 | 持久化会话 ID；即时问答、分析和分类为空 |
| `assistant_message_id` | `uuid` | 是 | 成功持久化的回答消息 ID，用于从回答定位调用链 |
| `entrypoint` | `varchar(32)` | 否 | `ask`、`conversation`、`conversation_stream`、`analyze` 或 `classify` |
| `model_name` | `varchar(120)` | 是 | 本轮模型名称 |
| `status` | `varchar(16)` | 否 | `running`、`success`、`error` 或 `cancelled` |
| `error_type` | `varchar(120)` | 是 | 脱敏后的异常类型，不含异常正文 |
| `started_at` | `timestamptz` | 否 | 运行开始时间 |
| `finished_at` | `timestamptz` | 是 | 运行结束时间；进程中断时可为空 |
| `duration_ms` | `integer` | 是 | 运行总耗时毫秒 |
| `steps` | `jsonb` | 否 | 有序模型、工具、检索和错误步骤摘要；不存提示词、回答或笔记正文 |

索引：`pkm_assistant_traces_pkey(id)`；`ix_assistant_traces_started(started_at,id)`；`ix_assistant_traces_entry_status_started(entrypoint,status,started_at)`；`ix_assistant_traces_conversation_message(conversation_id,assistant_message_id)`。仅 `APP_ENV=development|dev|local` 且 `ASSISTANT_TRACE_VIEW_ENABLED=true` 时写入并开放开发者查询；开发环境由开发者独占使用，其他环境默认关闭。维护 worker 每 15 分钟清理 30 天前的记录。

## `pkm_note_file_versions`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4 主键 |
| `user_id` | `uuid` | 否 | 所属账号 ID |
| `note_id` | `uuid` | 否 | 文件笔记 ID |
| `version` | `integer` | 否 | 该笔记的文件版本序号 |
| `filename` | `varchar(255)` | 否 | 原始文件名 |
| `extension` | `varchar(16)` | 否 | 版本格式 |
| `media_type` | `varchar(120)` | 否 | 响应 MIME 类型 |
| `storage_key` | `varchar(80)` | 否 | API 私有持久卷的随机存储键，不含文件内容 |
| `size_bytes` | `integer` | 否 | 文件字节数 |
| `sha256` | `varchar(64)` | 否 | 当前原文件内容校验值 |
| `created_at` | 时间 | 否 | 数据库 `now()` |

索引：主键、`uq_note_file_version(note_id,version)`、唯一存储键、`ix_note_file_user_note_version(user_id,note_id,version)`。

## `pkm_note_text_blocks`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4 主键 |
| `user_id` | `uuid` | 否 | 所属账号 ID |
| `note_id` | `uuid` | 否 | 文件笔记 ID |
| `content_version` | `integer` | 否 | 提取文本版本 |
| `ordinal` | `integer` | 否 | 版本内顺序 |
| `start_offset` / `end_offset` | `integer` | 否 | 检索文本 Unicode 字符范围 |
| `locator` | `jsonb` | 否 | PDF 页、DOCX 段落、XLSX 工作表/单元格等位置 |

索引：主键、`uq_text_block_position(note_id,content_version,ordinal)`、`ix_text_blocks_user_note_version(user_id,note_id,content_version)`。

## `pkm_markdown_image_references`

记录 Markdown 笔记正文里对同账号图片笔记的引用（形如 `![说明](/v1/notes/{图片笔记ID}/file)`），用于生成「被哪些笔记引用」提示，并把图片的语义描述并入引用笔记的检索上下文。引用按正文位置保存，编辑后按新正文重建，不需要数据迁移。

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `markdown_note_id` | `uuid` | 否 | 引用方 Markdown 笔记 ID，复合主键之一 |
| `start_offset` | `integer` | 否 | 图片链接在正文中的 Unicode 起始位置，复合主键之一 |
| `end_offset` | `integer` | 否 | 图片链接结束位置（不含） |
| `user_id` | `uuid` | 否 | 所属账号 ID |
| `image_note_id` | `uuid` | 否 | 被引用的图片笔记 ID |
| `alt_text` | `text` | 否 | 链接的替代文字，默认空字符串 |
| `created_at` | `time` | 否 | 数据库 `now()` |

索引：主键 `(markdown_note_id,start_offset)`；`ix_markdown_image_refs_image(user_id,image_note_id)`；`ix_markdown_image_refs_markdown(user_id,markdown_note_id)`。图片笔记归档、永久删除或正文改动时，相关引用行同步失效；`0018_markdown_image_references` 建表并回填存量引用，`0020_backfill_archived_markdown_image_references` 补齐归档笔记的存量引用。

## `pkm_link_drafts`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4 主键 |
| `user_id` | `uuid` | 否 | 所属账号 ID |
| `source_url` | `text` | 否 | 提交的网页来源 |
| `title` | `varchar(240)` | 否 | 草稿标题 |
| `snapshot_text` | `text` | 否 | 抓取原文快照或用户补齐正文 |
| `body_md` | `text` | 否 | 用户可以继续修改的草稿正文 |
| `fetch_status` / `fetch_error` | `varchar(24)` / `varchar(500)` | 否/是 | 抓取状态与错误摘要 |
| `status` | `varchar(24)` | 否 | `draft` 或 `published` |
| `notebook_id` | `uuid` | 是 | 发布目标笔记本 |
| `created_at` / `updated_at` | 时间 | 否 | 数据库创建时间、应用更新草稿时间 |

索引：主键、`ix_link_drafts_user_updated(user_id,updated_at)`、活跃草稿 URL 唯一索引。此表不参与笔记检索或内容导出。

## `pkm_file_ingest_jobs`

| 字段 | 类型 | 可空 | 默认/用途 |
| --- | --- | --- | --- |
| `id` | `uuid` | 否 | 应用 UUID4 主键 |
| `user_id` / `note_id` / `file_version_id` | `uuid` | 否 | 任务归属与文件版本 |
| `status` / `attempts` / `last_error` | `varchar(24)` / `integer` / `varchar(500)` | 否/否/是 | 持久任务状态、重试次数与错误摘要 |
| `vision_results` | `jsonb` | 否 | 按页记录视觉识别结果；任务恢复时跳过已成功页，只重试未成功页 |
| `available_at` / `created_at` / `updated_at` | 时间 | 否 | 重试调度、创建时间与租约心跳时间 |

索引：主键、`uq_file_ingest_version(file_version_id)`、`ix_file_ingest_jobs_status_available(status,available_at)`。

## 扩展功能相关迁移（`0011`/`0016`/`0018`–`0022`）

这些迁移对应 [功能全量清单](FEATURE_INVENTORY_2026-10.md) 第七节的扩展功能，不属于 M1–M3 必做验收门槛，但结构已随主线迁移落地，均以会话账号 `user_id` 隔离，无数据库外键。

- `0011_archive_retention`：为归档列表与到期清理增加 `(user_id, deleted_at)` 相关索引，回收站复用 `pkm_notes.deleted_at`，不新增表。
- `0016_note_templates`：新增 `pkm_note_templates`。
- `0018_markdown_image_references`：新增 `pkm_markdown_image_references` 并回填存量引用；`0020_backfill_archived_markdown_image_references` 补齐归档笔记的存量引用。
- `0017_assistant_traces`：新增 `pkm_assistant_traces`（字段见上）。
- `0019_note_digests_reminders` 增加以下业务表：

| 表 | 主键与主要字段 | 约束或索引 |
| --- | --- | --- |
| `pkm_digest_settings` | `user_id uuid` 主键；`daily_enabled/weekly_enabled boolean`；`daily_time/weekly_time varchar(5)`；`weekly_weekday smallint`；`daily_next_at/weekly_next_at/updated_at timestamptz` | 每账号一行；时间为 UTC 存储，计划按北京时间计算 |
| `pkm_digest_runs` | `id uuid` 主键；`user_id uuid`、`kind varchar(8)`、`slot_key varchar(16)`、`scheduled_at/period_start/period_end timestamptz`、`status varchar(16)`、`note_id uuid` 可空、`source_refs jsonb`、`error varchar(500)` 可空、`attempts integer`、创建/更新时间 | `uq_digest_user_kind_slot`；状态与计划时间、账号与创建时间索引。`note_id` 指向产出的报告笔记；笔记被永久删除时该列被清空而**运行记录保留**（排期账本必须比报告活得久，删行会导致同一 slot 被重新排期），因此 `status='ready'` 且 `note_id` 为空表示「已生成但报告已被删除」 |
| `pkm_note_reminders` | `id uuid` 主键；`user_id uuid`、`note_id uuid` 可空（`0021_optional_reminder_note`）、`text varchar(200)`、`due_at timestamptz`、`status varchar(16)`、`completed_at` 可空、创建/更新时间 | 账号、状态、到期时间索引；账号、笔记索引；空 `note_id` 为独立提醒。关联笔记被软删除时提醒被列表过滤但行保留（恢复笔记即带回）；笔记被永久删除时该行随之删除，不置空 `note_id`（置空会让它作为独立提醒重新出现） |

`pkm_note_templates` 结构见上文独立小节。

`0022_audit_observability` 增加审计可观测性结构：

| 表 | 主键与主要字段 | 约束或索引 |
| --- | --- | --- |
| `pkm_access_logs` | `id uuid` 主键；`request_id uuid`、`user_id uuid` 可空、`method varchar(8)`、`path varchar(255)`、`status_code smallint`、`duration_ms integer`、`ip varchar(45)` 可空、`user_agent text` 可空、`created_at timestamptz` | `ix_access_request`；`ix_access_user_created`；`ix_access_created` |
| `pkm_audit_events`（扩展） | 追加 `request_id uuid`、`actor_id uuid`、`outcome smallint`、`before jsonb`、`after jsonb`，全部可空 | `ix_audit_request`；`ix_audit_user_action_created` |

## `pkm_alembic_version`

仅 `version_num varchar(32) NOT NULL`，主键索引由 Alembic 管理。它不是业务表，不人为补第二个索引。

## 关联、删除与阶段边界

数据库零外键；`user_id` 与各关联 UUID 仅为普通列。业务服务在事务中按登录态 `user_id` 校验目标对象和活跃状态；无效或跨账号 ID 返回 404。删除笔记本时将活跃笔记移为未分类；删除标签时解除当前关联；永久清理必须按子表到父表的顺序显式执行。直接 SQL 写入能绕开应用校验，因此需要定期巡检孤儿及跨账号关联。

M1、M2 能力已实施；M3 迁移已加入文件版本、提取文本和网页草稿结构，M3 集成验收已于 2026-10-05 完成（唯余真实公网网页抓取因环境 DNS 污染未验证）。扩展功能表（笔记模板、Markdown 图片引用、Agent 调用链、日报/周报、提醒、访问日志）随主线迁移一并落地，不计入 M1–M3 验收门槛，逐项归属见[功能全量清单与阶段对照](FEATURE_INVENTORY_2026-10.md)。

归档笔记复用 `pkm_notes.deleted_at`，保留期 30 天，由 `ingest-worker` 每日 00:00（北京时间）维护窗口按 `deleted_at + 30 天` 到期批量永久清除；单篇与批量清除也可由用户主动触发。永久清除按子表到父表的顺序显式删除笔记的文件版本、文本块、检索片段、索引任务、修订、标签关联与图片引用，**但不删除该笔记的 `pkm_audit_events` 行**——审计必须比笔记活得久，`entity_id` 指向已不存在的实体是预期行为；只有账号注销才清除其审计与访问日志。

当前接口字段与响应见 [接口设计](API_DESIGN.md)、[M2 设计](M2_DESIGN.md)和 [M3 设计](M3_DESIGN.md)。


## pkm_assistant_operations（0023，内部操作账本）

UUID主键 `id`；账号 `user_id`（必填）；`conversation_id`（可空）；UUID `request_id`（必填）；`request_hash` varchar(64)；`context_fingerprint` varchar(64)可空；`status` varchar(24)；JSONB `intent`、`proposal` 默认空对象；JSONB `receipt` 可空；时区时间 `created_at`、`expires_at`。同账号request_id唯一，账号+对话及过期时间索引。字段用途、事务及保留策略见 DB_DESIGN.md 的 AI 对话操作记录部分。该表没有向客户端开放原始查询接口。

2026-10-08 补充：助手消息 `content` 的服务器内部 `_literal_sources` 用于合法文档型文字的来源复核，包含笔记归属所需标识、版本、字段、范围及 SHA-256 摘要。读取时验证当前账号和实际原文，API 投影剔除该字段及任意未登记扩展；模型上下文只接收投影后的文字。公开引用卡片仅包含 `citation_id`、`note_id`、`title`，不再公开内部版本、原文范围或摘要。此兼容扩展无需数据库迁移，也不重写旧行。
