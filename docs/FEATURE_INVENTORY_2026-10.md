# 功能全量清单与阶段对照（M0–M4）

核对日期：2026-10-05。依据：毕业设计任务书、PRD V2.2、M0–M3 设计与验收文档，以及当前工作树的静态检查（`api/app/` 全部路由、`api/app/core/models.py` 表定义、`api/alembic/versions/` 迁移序列 `0001`–`0022`、`web/src/` 视图与 `api/scripts/` 验证脚本）。

本文回答两个问题：**现在是不是只剩第四阶段**，以及**已实现的功能是否都能在阶段文档中找到归属**。凡是此前只存在于代码、未写入任何阶段文档的功能，在本文补齐，并同步回 [数据库字典](DATABASE_DICTIONARY.md)、[接口设计](API_DESIGN.md) 与[开发与验收说明](DEVELOPMENT_AND_ACCEPTANCE.md)。

## 一、结论

1. **只剩第四阶段。** 三个阶段（M1 基础系统与检索、M2 Agent 赋能、M3 多格式笔记与网页草稿）的需求都已在代码中落地。M1 已验收，M2 已由项目负责人确认验收，M3 集成验收已于 2026-10-05 完成（唯余 1 项环境受限）。产品阶段之后只剩 **M4：测试与论文**（云端演示部署、综合测试与对照实验、结果分析、论文与答辩）。
2. **三阶段必做范围内的功能 100% 有阶段归属**，逐项见第四至第六节，均有接口、数据表、代码位置与验证脚本。
3. **另有 11 项扩展功能**在 M1–M3 开发窗口内一并落地，但**不属于三阶段必做验收门槛**（第七节）。其中 3 项（回收站、复习提醒、每周知识周报）在 PRD §3 被列为"后续扩展"，实际已经实现；此前只散落在接口文档、前端页面与迁移文件中，缺统一登记，本文补齐。
4. 尚未实现的后续扩展只剩 5 项（第八节）：基于笔记的学习推荐、图片与扫描 PDF 的 OCR、浏览器剪藏扩展、含分类与版本的系统备份、笔记自动保存。它们不进入 M1–M3 验收，也不阻塞 M4。
5. M3 除环境受限项外，尚有 **2 项代码级遗留**（第九节），与阶段归属无关，但需在 M4 前处理。

## 二、阶段对照总表

| 阶段 | 状态 | 需求来源 | 主要代码入口 | 验收证据 |
| --- | --- | --- | --- | --- |
| M0：开题与设计 | 已完成 | 开题报告、任务书、PRD V2.2 | `api/app/main.py`（`/health/*`、`/docs`）、`compose.yaml` | [M0 与 M3 验收记录](ACCEPTANCE_M0_M3.md) §一 |
| M1：基础系统与 RAG 检索层 | **已验收（2026-10-02）** | 任务书（二）1–5；PRD §5 | `app/auth/`、`app/knowledge/notes.py`、`taxonomy.py`、`search.py`、`indexer.py`、`chunking.py`、`embeddings.py` | [M1 验证记录](M1_VERIFICATION.md) |
| M2：Agent 赋能 | **已确认验收** | 任务书（三）；PRD §6 | `app/assistant/model_connection.py`、`assistant.py`、`conversations.py`、`app/prompts/` | [M2 验证记录](M2_VERIFICATION.md) |
| M3：多格式笔记与网页草稿 | **集成验收完成**（唯余公网抓取环境受限未验证） | 任务书（四）；PRD §6.1 | `app/knowledge/m3.py`、`upload_sessions.py`、`file_ingest.py`、`archive.py`、`app/ops/link_fetch_worker.py` | [M0 与 M3 验收记录](ACCEPTANCE_M0_M3.md) |
| 扩展功能（跨阶段） | 已实现，不计入三阶段门槛 | PRD §3「后续扩展」中已落地部分 + 开发期增量 | 见第七节 | 各专项验证脚本，见第七节 |
| M4：测试与论文 | **唯一剩余阶段** | 任务书（五）；PRD §9、§10 | — | 待产出：测试报告、云端部署与资源记录、实验数据、论文、答辩材料 |

迁移序列与阶段的对应关系（`api/alembic/versions/`）：

| 迁移 | 阶段 | 内容 |
| --- | --- | --- |
| `0001`–`0004`、`0006` | M0/M1 | 初始表、片段来源、生命周期与审计、零外键与 `pkm_` 前缀改造、合并式内容索引任务 |
| `0005`、`0007`、`0008`、`0015` | M2 | 模型连接、持久化对话、对话生命周期、会话上下文摘要 |
| `0009`、`0010`、`0012`、`0013`、`0014` | M3 | 多格式与网页草稿、对象上传与异步识别、移除旧视觉连接、抓取队列、合并迁移头 |
| `0011`、`0016`、`0017`、`0018`、`0019`、`0020`、`0021` | 扩展功能 | 归档保留索引、笔记模板、Agent 调用链、Markdown 图片引用及其回填、日报周报与提醒、提醒可独立于笔记 |
| `0022` | 扩展功能 | 审计可观测性（业务审计扩展 + 请求层访问日志） |

## 三、M0 基线（已完成）

| 功能 | 入口 | 说明 |
| --- | --- | --- |
| 服务健康检查 | `GET /health/live`、`/health/ready`、`/health/embedding` | 进程存活、数据库可连接且已迁移、Embedding 模型已安装；三者独立，Embedding 故障不阻塞 API 就绪 |
| 接口文档 | `GET /docs`、`GET /openapi.json` | OpenAPI 自动生成，业务路径统一 `/v1` 前缀 |
| 本地容器编排 | `compose.yaml`、`scripts/dev-up.py` | Web、API、worker、PostgreSQL 18 + pgvector、Ollama、MinIO、ONLYOFFICE（`office` profile）；只有 Web 映射宿主机端口 |
| 数据库迁移框架 | `api/alembic/` | `migrate` 服务在数据库健康后执行 `alembic upgrade head` |

## 四、M1 功能清单（已验收）

| 编号 | 功能 | 接口 | 数据/代码 | 状态 |
| --- | --- | --- | --- | --- |
| M1-1 | 注册、登录、退出、身份查询 | `POST /v1/auth/register`、`/login`、`/logout`、`GET /v1/auth/me` | Argon2id 密码哈希；服务端可撤销会话 Cookie（`pkm_user_sessions` 只存 SHA-256 摘要）；`app/auth/auth.py` | 已验收 |
| M1-2 | 账号数据隔离 | 所有业务接口从会话解析 `user_id` | 请求体不接受 `user_id`；跨账号资源 ID 一律 404；`app/auth/auth.py`（`UserId` 依赖） | 已验收 |
| M1-3 | Markdown 笔记 CRUD | `GET/POST /v1/notes`、`GET/PATCH/DELETE /v1/notes/{id}` | `pkm_notes`；版本号冲突返回 409；删除为逻辑删除 `deleted_at`；`app/knowledge/notes.py` | 已验收 |
| M1-4 | 笔记本 CRUD | `GET/POST /v1/notebooks`、`GET/PATCH/DELETE /v1/notebooks/{id}` | `pkm_notebooks`；单层；删除后笔记转为未分类 | 已验收 |
| M1-5 | 标签 CRUD | `GET/POST /v1/tags`、`GET/PATCH/DELETE /v1/tags/{id}` | `pkm_tags` + `pkm_note_tags`；删除后关联解除，笔记保留 | 已验收 |
| M1-6 | 列表筛选与排序 | `GET /v1/notes?notebook_id=&unclassified=&tag_id=&q=&updated_desc=` | 游标分页（`limit`/`cursor`） | 已验收 |
| M1-7 | 分段与向量索引 | 后台 worker，无对外接口 | `pkm_note_chunks`（1024 维）、`pkm_index_jobs`；内容版本递增、8 秒合并延迟、每篇笔记一个活跃任务；`app/knowledge/chunking.py`、`indexer.py`、`embeddings.py` | 已验收 |
| M1-8 | 关键词与混合检索 | `GET /v1/search?mode=keyword\|hybrid` | 倒数排名融合；`semantic_status` 降级为 `unavailable` 时仍返回关键词结果；`app/knowledge/search.py` | 已验收 |
| M1-9 | 检索结果原文定位 | 搜索响应含 `source_field`/`start_offset`/`end_offset` | 前端点击结果打开当前笔记并定位 | 已验收 |
| M1-10 | 版本快照与修订记录 | 内部，无对外接口 | `pkm_note_revisions`；每次成功保存一个快照 | 已验收 |
| M1-11 | 固定 20 题评测 | `scripts/evaluate_m1.py`、`scripts/evaluation_cases.json` | 精确词/同义改写/跨笔记综合/无答案各 5 题；比较关键词与混合检索来源命中 | 已验收 |

## 五、M2 功能清单（已确认验收）

| 编号 | 功能 | 接口 | 数据/代码 | 状态 |
| --- | --- | --- | --- | --- |
| M2-1 | 用户自备模型连接设置 | `GET/PUT/PATCH/DELETE /v1/model-connection`、`POST /v1/model-connection/test` | `pkm_model_connections`；Fernet 加密密文，页面不回显明文；每账号一个活跃连接；`app/assistant/model_connection.py` | 已确认验收 |
| M2-2 | 引用式知识库问答 | `POST /v1/assistant/ask` | LangChain `create_agent`；工具受当前账号约束且只读；回答引用经服务端重新核验；`app/assistant/assistant.py` | 已确认验收 |
| M2-3 | 指定笔记内容分析 | `POST /v1/assistant/analyze` | 只返回建议，不自动写入 | 已确认验收 |
| M2-4 | 分类建议与确认保存 | `POST /v1/assistant/classify`，用户确认后走 M1 笔记更新接口 | 确认时重新校验笔记与分类账号归属 | 已确认验收 |
| M2-5 | 持久化 AI 对话 | `GET/POST /v1/assistant/conversations`、`GET/PATCH/DELETE /v1/assistant/conversations/{id}`、`POST /v1/assistant/conversations/{id}/messages` | `pkm_assistant_conversations`、`pkm_assistant_messages`；引用快照不随笔记变化改写；对话软删除 | 已确认验收 |
| M2-6 | 长对话上下文摘要 | 内部，随消息接口生效 | `pkm_assistant_conversations` 摘要检查点（迁移 `0015`）；超过 16 条消息后压缩早期历史，摘要不作为笔记证据 | 已确认验收 |
| M2-7 | 模型连接不可用降级 | — | 未配置或调用失败时，M1 笔记与检索保持可用 | 已确认验收 |

## 六、M3 功能清单（集成验收完成）

| 编号 | 功能 | 接口 | 数据/代码 | 状态 |
| --- | --- | --- | --- | --- |
| M3-1 | 单文件上传与重复预检 | `POST /v1/notes/upload`、`POST /v1/notes/file-duplicate-check` | 前端算 SHA-256 预检，服务端完成时复核；`app/knowledge/m3.py`、`file_types.py` | 单项验收通过 |
| M3-2 | 分块上传会话、续传与取消 | `POST/GET /v1/file-uploads/sessions`、`GET /v1/file-uploads/sessions/{id}`、`POST .../parts/{n}/url`、`PUT .../parts/{n}/receipt`、`POST .../complete`、`POST .../retry`、`POST .../retry-ingest`、`DELETE .../{id}` | 5 MiB 分块、短期签名直传对象存储、幂等键去重、24 小时未完成会话清理；`pkm_file_upload_sessions`；`app/knowledge/upload_sessions.py` | UP-01~05 通过（前端并发 ≤3、断网恢复、并发冲突） |
| M3-3 | 对象存储与旧文件迁移 | `GET /v1/files/{storage_key}` | MinIO `minio_data` 卷；`pkm_note_file_versions`；`scripts/migrate_files_to_object_storage.py` 逐件核对大小与 SHA-256 | MIG-01~05 通过（含故障注入） |
| M3-4 | 文件当前版本读取与保存 | `GET/PUT /v1/notes/{id}/file` | 带 `version` 可下载保留的旧 Office 原件；写入用笔记预期版本，冲突 409 | 验收通过 |
| M3-5 | 内容识别与索引 | 无对外接口，随 `pkm_file_ingest_jobs` 状态查询 | DOCX 段落/表格行、XLSX 工作表与单元格坐标、文字型 PDF 页提取；`pkm_note_text_blocks` 保存位置；`app/knowledge/file_ingest.py` | 格式矩阵通过 |
| M3-6 | 图片语义描述 | 无对外接口 | PNG 与扫描 PDF 页由本地 Ollama `qwen3-vl:2b-instruct` 生成中文语义描述；**不做 OCR、不提取图中文字** | 验收通过 |
| M3-7 | ONLYOFFICE 在线编辑 | `GET /v1/notes/{id}/editor-config`、`POST /v1/integrations/onlyoffice/callback/{note_id}`、`GET /v1/files/{storage_key}` | 回调 JWT 签名校验，文档 key 绑定笔记版本/文件版本/SHA-256，保存后加锁复核，旧回调拒绝 | `status=2`/`status=6`/旧回调拒绝均通过 |
| M3-8 | 旧 DOC/XLS 转换 | 上传时 `convert_legacy` 确认 | 确认后生成 DOCX/XLSX 可编辑版本，原件单独保留下载；不把转换后文件称为原格式 | 转换确认流通过 |
| M3-9 | 图片笔记预览与缩放 | 前端 `ImageNoteEditor.vue` | 仅预览、25%–300% 缩放、重置与错误提示；**不含像素级编辑** | 范围按负责人确认 |
| M3-10 | 单篇/笔记本/全部内容导出 | `GET /v1/notes/{id}/export`、`GET /v1/notebooks/{id}/export`、`GET /v1/notes/export` | 单篇为当前格式；笔记本与全部为 ZIP；不注入 YAML front matter 或 ZIP 清单；未编辑上传文件导出字节一致 | 验收通过 |
| M3-11 | 网页链接草稿 | `GET/POST /v1/link-drafts`、`GET/PATCH/DELETE /v1/link-drafts/{id}` | 先持久化 `pending` 草稿并立即返回，`link_fetch_worker` 异步抓取；`pkm_link_drafts` 保存只读原文快照；草稿不进搜索、导出与 Agent 知识库 | 确定性用例通过 |
| M3-12 | 抓取安全门禁（SSRF） | 无对外接口 | 初始 URL、解析出的 IPv4/IPv6 与每次重定向逐跳校验，拒绝环回/私有/链路本地/云元数据地址，连接固定到通过校验的 IP，限制跳转次数、体积与时长 | 混合公网私网、目标 IP 固定、跳转内网拦截通过；**真实公网抓取因宿主代理 fake-IP DNS 污染环境受限未验证** |
| M3-13 | 草稿分析、改写与发布 | `POST /v1/link-drafts/{id}/analyze`、`/rewrite`、`/publish` | 分析返回摘要/要点/行动建议；改写只返回建议不自动应用；发布重新校验账号归属后建 Markdown 笔记并写 `source_url` | 验收通过 |
| M3-14 | 文件型结果检索定位 | 沿用 `GET /v1/search` | 增加 `content_kind` 与 `location`（DOCX 段落、XLSX 工作表/单元格、PDF 页码）；能稳定跳转则直达，否则打开文件并提供片段搜索 | 逐格式位置核对通过 |
| M3-15 | M1/M2 回归门槛 | — | 本机 Compose 重跑 `verify_m1`、`verify_m2`、`verify_conversations`、`verify_lifecycle`、`verify_m3_fixes`、`check_integrity`、`npm run build` | 全部通过 |

## 七、扩展功能清单（已实现，不计入三阶段必做验收门槛）

以下功能在 M1–M3 开发窗口内一并落地，超出任务书与 PRD 的三阶段必做范围。PRD §3「后续扩展」行列出了其中 3 项（回收站、复习提醒、每周知识周报），代码实际已实现，此前缺少统一登记，本表补齐。

| 编号 | 功能 | 接口 | 数据表/迁移 | 代码 | 专项验证 | PRD 定位 |
| --- | --- | --- | --- | --- | --- | --- |
| EX-1 | 回收站与归档保留 | `GET /v1/notes/archive`、`POST /v1/notes/archive/{note_id}/restore`、`DELETE /v1/notes/archive/{note_id}`、`POST /v1/notes/archive/purge` | 复用 `pkm_notes.deleted_at`；`0011_archive_retention` 增索引 | `app/knowledge/archive.py`、前端 `archive` 视图 | `scripts.check_integrity`、`verify_lifecycle` | §3「后续扩展·回收站」（已实现） |
| EX-2 | 归档到期自动清理 | worker 定时，无对外接口 | 保留期 30 天（`archive.RETENTION_DAYS`）；按 `deleted_at + 30 天` 计算 `purge_at`/`days_remaining` | `ingest-worker` 每日 00:00（北京时间）维护窗口调用 `purge_expired_archive()`；`app/knowledge/archive.py`、`app/ops/ingest_worker.py` | 同上 | 同上 |
| EX-3 | 笔记模板 | `GET/POST /v1/note-templates`、`PATCH/DELETE /v1/note-templates/{id}` | `pkm_note_templates`（`0016`） | `app/knowledge/templates.py`；前端内置空白/随笔/每日一记/工作纪要/课程摘要 + 导入 Markdown | 前端 `npm run build`、`verify_audit_coverage` | 任务书未列，开发期新增 |
| EX-4 | Markdown 图片引用与上下文增强检索 | `GET /v1/notes/{note_id}/image-references` | `pkm_markdown_image_references`（`0018`、`0020` 回填） | `app/knowledge/markdown_images.py` | `scripts/verify_markdown_image_context.py` | 任务书未列，开发期新增 |
| EX-5 | 索引片段预览（开发排障） | `GET /v1/notes/{note_id}/chunks` | 读 `pkm_note_chunks` | `app/knowledge/notes.py` | `scripts/preview_chunks.py` | 任务书未列，开发期新增 |
| EX-6 | 笔记日报 | `GET/PUT/PATCH /v1/digests/settings`、`GET /v1/digests`、`POST /v1/digests/{run_id}/retry` | `pkm_digest_settings`、`pkm_digest_runs`（`0019`） | `app/assistant/digests.py`、`app/ops/digest_worker.py` | `scripts/verify_digests_reminders.py` | 任务书未列（周报在 §3「后续扩展」） |
| EX-7 | 笔记周报 | 同上（`kind=weekly`） | 同上 | 同上；正文为可编辑 Markdown 笔记，证据键在服务端替换为笔记标题链接 | 同上 | §3「后续扩展·每周知识周报」（已实现） |
| EX-8 | 日程提醒 | `POST /v1/reminders`、`GET /v1/reminders`、`PATCH/DELETE /v1/reminders/{id}`、`POST /v1/notes/{note_id}/reminders` | `pkm_note_reminders`（`0019`、`0021` 允许独立提醒） | `app/knowledge/reminders.py`、前端 `ReminderDialog.vue` 与合并的「日程提醒」页 | `scripts/verify_digests_reminders.py` | §3「后续扩展·复习提醒」（已实现） |
| EX-9 | 知识工作台聚合 | `GET /v1/workbench` | 读提醒、日报/周报任务、归档笔记与最近笔记 | `app/knowledge/reminders.py`（`workbench_router`）、前端 `WorkbenchHome.vue` | `scripts/verify_workbench.py` | 任务书未列，开发期新增 |
| EX-10 | Agent 调用链（开发环境脱敏） | `GET /v1/dev/assistant-traces/enabled`、`GET /v1/dev/assistant-traces`、`GET /v1/dev/assistant-traces/{trace_id}`、`GET /v1/dev/assistant-traces/by-message/{assistant_message_id}` | `pkm_assistant_traces`（`0017`） | `app/assistant/tracing.py`、前端 `AssistantTraceExplorer.vue` | `scripts/verify_assistant_tracing.py` | §3 未列；只在 `ASSISTANT_TRACE_VIEW_ENABLED=true` 且开发环境开放 |
| EX-11 | 请求级审计与访问日志 | 无对外查询接口，排障用 `scripts.query_audit.py` | `pkm_audit_events`（扩展 `request_id`/`actor_id`/`outcome`/`before`/`after`）、`pkm_access_logs`（`0022`，保留 90 天） | `app/ops/audit_middleware.py`（纯 ASGI）、`app/core/lifecycle.py`、`app/ops/maintenance.py` | `verify_audit_coverage`、`verify_audit_observability`、`verify_audit_governance` | 任务书未列，开发期新增 |

补充说明：

- 扩展功能**不改变** M1–M3 的验收结论，也不把三阶段验收门槛抬高；它们的实现细节与专项验证单独维护。
- `POST /v1/assistant/conversations/{id}/messages/stream`（SSE 流式回答）与 `app/core/ollama_gate.py`、`app/core/rate_limit.py`（推理门禁与限流）属 M2 交互与资源保护的实现细节，验证入口为 `scripts/verify_inference_gate.py`。
- 回收站、提醒与日报/周报的正文都落在普通 `pkm_notes` 中，因此自动进入既有的笔记列表、搜索与导出路径。

## 八、尚未实现的后续扩展（PRD §3 剩余项）

| 功能 | 说明 | 是否阻塞 M4 |
| --- | --- | --- |
| 基于笔记的学习推荐 | 未实现 | 否 |
| 图片与扫描 PDF 的 OCR | 未实现；当前仅本地视觉模型生成语义描述，不识别图中文字 | 否 |
| 浏览器扩展剪藏 | 未实现；当前只有网页链接草稿 | 否 |
| 含分类与版本的系统备份 | 未实现；当前只有内容导出，不保证重新导入还原分类与历史 | 否 |
| 笔记自动保存 | 未实现；当前以显式保存为验收边界（ONLYOFFICE 自身的自动保存属文档服务行为） | 否 |

## 九、唯一剩余阶段 M4 与遗留事项

M4 交付物：云端演示环境部署与 Qwen3-Embedding 0.6B 验证、资源消耗记录、综合测试与 20 题对照实验、结果分析、论文、答辩材料。

M3 遗留（不影响阶段归属判定，但应在 M4 前处理）：

1. **真实公网网页抓取**：宿主本地代理（Clash Verge）fake-IP DNS 把目标域名解析到 `198.18.0.0/15`（RFC 2544）与 `2001:2::/48`（RFC 5180）benchmarking 段，逐条 `ipaddress.is_global=False`，被 SSRF 门禁按设计拒绝为 422。容器直连公网真实 IP 实测 TLS 握手返回 `HTTP/1.1 200 OK`（0.26–0.33s），属环境网络问题而非产品缺陷。取证见 `test-results/m3/web-dns-gate-2026-10-05.txt`；解除条件：宿主代理切 real-ip，或为 api 与 link-fetch-worker 容器注入真实解析。
2. **直传 API 的转换阻塞**：`POST /v1/notes/upload` 在 async 协程内同步执行格式转换，会阻塞事件循环。UI 链路走 `complete_session`（同步 `def`，FastAPI 放线程池）不受影响。建议改为 `await anyio.to_thread.run_sync(...)`。
3. **URL 尾斜杠去重**：规范化只应在 `len(path) > 1 and path.endswith("/")` 时裁剪，避免把根路径 `"/"` 归一化为空串。

既有验证：`scripts.verify_m1`、`verify_m2`、`verify_conversations`、`verify_lifecycle`、`verify_m3_fixes`、`check_integrity`（全 0）与 `npm run build` 均通过。

## 十、本次文档同步

- 本文新增：功能全量清单与阶段对照，服务端路由与数据表逐个核对。
- [数据库字典](DATABASE_DICTIONARY.md)：补 `pkm_markdown_image_references` 表结构；汇总表补 4 张缺失业务表；业务表计数由 21 修正为 25；修正误标的 `pkm_alembic_version` 小节标题；补充归档、图片引用相关迁移的边界说明。
- [数据库设计](DB_DESIGN.md) 与 [架构与阶段边界](ARCHITECTURE.md)：业务表计数由 21/16 统一修正为 25；补回收站保留与到期清除说明、扩展功能在阶段边界中的定位。
- [接口设计](API_DESIGN.md)：补回收站、开发环境调用链、笔记片段预览、图片引用、文件重复预检、流式回答与上传会话重试路由，并新增回收站与开发排障接口小节；M3 段补分块上传会话路由。
- [开发与验收说明](DEVELOPMENT_AND_ACCEPTANCE.md)：阶段进度表增列扩展功能并说明只剩 M4；文档索引加入本文。

后续补记（2026-10-05 晚）：修复永久删除笔记时遗留悬空引用——`purge_archived_note` 原先只清理文件、文本块、检索片段、索引任务、修订、图片引用与上传会话，遗漏了提醒（`pkm_note_reminders`）与周报运行记录（`pkm_digest_runs`），导致 `check_integrity` 的 `digest_runs_invalid_note` / `reminders_invalid_note` 非零。现按外键语义分两类处理：提醒随笔记删除，周报运行记录保留并清空 `note_id`（排期账本不可删）。`verify_digests_reminders.py` 已补永久删除路径的专项断言（含审计 `details` 计数）；上一节「既有验证」各项复跑通过，两套环境 `check_integrity` 现全 0。文档同步见 [接口设计](API_DESIGN.md) 的回收站小节与[数据库字典](DATABASE_DICTIONARY.md) 的 `pkm_digest_runs` / `pkm_note_reminders` 行。
- [版本兼容记录](VERSIONS.md)：更新 python-docx/openpyxl/BeautifulSoup/ONLYOFFICE 四行，从"待容器验证"改为 2026-10-05 集成验收状态。

各阶段验收签核仍以 [M1](M1_VERIFICATION.md)/[M2](M2_VERIFICATION.md)/[M0 与 M3 验收记录](ACCEPTANCE_M0_M3.md) 为准，本文不代替阶段签核。

## 十一、需求文档冲突修正（并入自原 `REQUIREMENTS_AUDIT_2026-10.md`）

核对日期：2026-10-05。依据根目录 PRD V2.2、毕业设计任务书及当前工作树的静态检查（`api/app/` 全部路由、`core/models.py` 表定义、`alembic/versions/0001–0022`、`web/src/` 视图与 `api/scripts/` 验证脚本）。该轮核对的阶段对照与复测结论已由本文第一至九节覆盖，此处只保留其独有的**两处需求描述与代码现状冲突的修正**。

| 冲突项 | 原描述 | 现行口径 |
| --- | --- | --- |
| 图片处理范围 | PRD 的 F01 写 PNG 支持裁剪、旋转、绘制与文字覆盖 | 实现与验收范围已收窄为**预览、缩放（25%–300%）与重置**；PRD 已同步，避免要求代码实现图像像素编辑 |
| 助手写入授权边界 | PRD/任务书「Agent 不直接写入」的表述，容易与「用户明确要求创建/修改」混淆 | 明确：检索问答**只读**；**用户明确的新建/修改指令本身可作为授权**；建议、分析或材料中的指令不能触发写入；当前无 Agent 删除能力。授权边界已补入 PRD 与 M2 设计 |

**扩展功能口径重申**：日报/周报、提醒、笔记模板、Markdown 图片引用、Agent 调用链与请求级审计属于开发窗口内一并落地的扩展功能，**不计入 M1–M3 必做验收门槛，也不抬高门槛**；其专项文档单独维护，不反向改变正式阶段验收范围（逐项见第七节）。

**变更边界**：该轮核对未改动业务逻辑或数据库结构。核对时有大量未提交改动，结论以当时工作树为对象。
