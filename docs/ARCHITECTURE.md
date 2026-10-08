# 系统架构与阶段边界

依据根目录 PRD V2.2。M1 的字段、事务与请求响应细节分别见 [数据库设计](DB_DESIGN.md) 和 [接口设计](API_DESIGN.md)；M2 见 [M2 设计](M2_DESIGN.md)。M1 已完成本地验收，M2 已由项目负责人确认验收。 [M3 多格式笔记与网页草稿](M3_DESIGN.md) 的主要功能已有初版，集成验收已于 2026-10-05 在隔离环境完成（见 [M0 与 M3 验收记录](ACCEPTANCE_M0_M3.md)），唯一剩余项为真实公网网页抓取（宿主本地代理 fake-IP DNS 污染导致环境受限未验证，非产品缺陷）；各阶段分别签核。原测试与论文阶段顺延为 M4。

```text
浏览器 → Web（本地 Vite；后期云端静态服务） → 路径代理 → FastAPI
                                                    ├─ PostgreSQL 18 + pgvector
                                                    ├─ Ollama / Qwen3-Embedding 0.6B
                                                    ├─ M2：用户配置的外部聊天模型
                                                    └─ M3：MinIO 对象存储、文件解析与 ONLYOFFICE Docs
索引 worker → PostgreSQL 索引任务 → Ollama → 当前版本的笔记片段
迁移容器 → PostgreSQL                    模型下载容器 → Ollama 数据卷
```

## 服务与数据

- `web` 是本地唯一映射宿主机端口的服务，使用 Vite 将 `/health`、`/docs`、`/openapi.json` 和 `/v1` 代理到后端，保持浏览器同源。`api`、`worker`、`db`、`ollama` 只通过 Compose 网络通信。
- `api` 使用同步 SQLAlchemy Session 与 Psycopg 3。`migrate` 在数据库健康后运行 Alembic；API 和 worker 在迁移成功后启动。Embedding 健康不阻塞 API 就绪。
- `db` 的卷保存账号、笔记及向量；`ollama` 的卷保存模型；M3 文件原件和不可变版本存入 S3 兼容 MinIO 的 `minio_data` 卷。迁移期间仍可从历史 `note_files` 卷读取旧文件，逐件核对大小和 SHA-256 后切换。ONLYOFFICE Docs 通过 `office` profile 启动，推荐本地启动脚本会自动启用。云端阶段需要另定备份和 HTTPS 入口。当前仅本机运行。
- M2 的 LangChain Agent 位于后端应用边界内，问答场景调用受当前账号约束的只读搜索和读取服务。用户明确要求新建或修改时才按本轮意图启用对应写入工具；分类建议仍须用户确认后再由笔记业务接口保存，助手不提供删除工具。AI 对话页使用账号配置的聊天模型生成知识库回答，将问题、回答和经核验的引用一并持久化；近期历史有长度限制，引用仍须来自本轮检索。API 镜像已安装 Agent 依赖。
- 开发环境可通过 `ASSISTANT_TRACE_VIEW_ENABLED=true` 开启本地 Agent 调用链记录页。链路只写入步骤名、耗时、状态、工具字段名、检索统计和异常类型，不保存模型输入输出或笔记正文；生产环境默认关闭，维护 worker 每 15 分钟清理 30 天前记录。

## 账号与数据约束

- 注册、登录和退出由现有 FastAPI 服务提供；FastAPI 内置 `APIKeyCookie` 统一读取登录 Cookie，Argon2id 校验密码，服务端会话可撤销。系统只有普通用户，不设计角色、管理员或按操作划分的权限。业务请求仍从登录会话解析 `user_id` 并只读写本人数据；前端传入或 Agent 生成的用户 ID 不参与归属判定，跨账号资源 ID 返回 404。
- `0009` 中的 `pkm_notes` 保存 Markdown 正文或文件提取文本、类型、来源链接、修订版本、内容版本和索引状态；`pkm_notebooks`、`pkm_tags` 均归属账号。25 张业务表（含笔记模板、Markdown 图片引用、日报/周报与提醒 4 张扩展功能表）统一使用 `pkm_` 前缀，数据库无外键，由服务事务验证同账号归属并定期巡检。
- `pkm_note_revisions` 保存各成功版本的 Markdown 快照，为以后恢复提供数据；`pkm_audit_events` 只记录动作及有限元数据，不保存正文或凭据。当前未开放恢复和永久删除接口。
- 日志分两层：业务审计（`pkm_audit_events`）与业务共事务、随业务回滚一并撤销；请求层访问日志（`pkm_access_logs`）由中间件用独立会话写入，失败请求也留痕，两层按 `request_id` 关联。审计属旁路逻辑，写入失败只记 warning，绝不击穿调用方事务。改造过程归档于 [操作日志能力评估与改造方案](archive/AUDIT_LOG_REDESIGN.md)。
- `pkm_note_chunks` 保存原文 Unicode 字符偏移、顺序、内容版本及 1024 维向量。标题或正文实际变化时，在同一事务内递增内容版本并合并到该笔记唯一的活跃 `pkm_index_jobs`，静默 8 秒后由 worker 为最新内容生成向量。分类变更只递增修订版本，不触发 Embedding。查询按账号与当前内容版本过滤；旧片段在重建完成前也不会被展示。
- `pkm_assistant_conversations` 与 `pkm_assistant_messages` 保存当前账号的 AI 对话。每次模型回答成功后，在一个事务中写入用户问题、Agent 回答、引用快照和语义状态；读取和写入都校验 conversation ID 与当前账号匹配。超过 16 条消息后，较早对话按需压缩为 PostgreSQL 中的会话级摘要检查点，仍保留完整消息供恢复；每轮带入摘要和最近消息，摘要不作为笔记事实证据。摘要仅属于单个会话。标题可编辑，对话以软删除方式从活跃列表隐藏。旧版检索快照消息仍兼容读取。
- M3 文件字节放入 MinIO 对象存储，`pkm_note_file_versions` 保存版本元数据；上传前进行 SHA-256 重复预检，服务端完成时再次校验。单篇按当前格式导出，笔记本与全部笔记导出为 ZIP，正文不加系统字段。
- 标题和正文关键词检索直接针对当前笔记；Embedding 失败只影响语义召回。混合检索分别取关键词和向量候选，再按排名融合并返回原文位置。[固定评测记录](M1_VERIFICATION.md)比较了两种召回。

## M1 接口契约

业务接口统一前缀 `/v1`，下表路径均相对于该前缀；JSON 请求与响应。列表使用 `limit`、`cursor` 和 `updated_desc` 排序；笔记写入时带版本，冲突返回 409。以下是已实现端点；完整字段见 [接口设计](API_DESIGN.md)：

| 领域 | 端点 | 关键输入与输出 |
| --- | --- | --- |
| 账号 | `POST /auth/register`、`POST /auth/login`、`POST /auth/logout`、`GET /auth/me` | 邮箱与密码；服务端会话 Cookie；不返回密码哈希 |
| 笔记 | `GET/POST /notes`、`GET/PATCH/DELETE /notes/{id}` | 标题、Markdown 正文、可空笔记本 ID、标签 ID 列表；返回当前版本及索引状态 |
| 笔记本 | `GET/POST /notebooks`、`PATCH/DELETE /notebooks/{id}` | 单层名称；删除后笔记保留且变为未分类 |
| 标签 | `GET/POST /tags`、`PATCH/DELETE /tags/{id}` | 名称；删除后关联解除，笔记保留 |
| 搜索 | `GET /search?mode=keyword|hybrid&q=...` | 可选笔记本、标签筛选；命中笔记 ID、标题、片段、起止偏移、当前版本、召回来源 |

未登录返回 401；其他账号的资源返回 404；笔记版本冲突返回 409；语义检索不可用时混合搜索返回明确降级状态及关键词结果。M2 已追加模型连接、引用问答、分析和分类建议接口，详见 [M2 接口契约](M2_DESIGN.md)。

## 阶段边界

M0 建立了 `/health/*` 与 `/docs`（OpenAPI 文档位于 `/openapi.json`）、初始表及 `vector` 扩展。M1 增加了 `/v1` 业务接口、标题和正文分段、后台索引与检索。M2 增加用户自备聊天模型连接、Agent 问答、分析与分类建议。分类写入仍经 M1 笔记更新接口。

M3 已落地主要功能初版，接口、数据模型与已实现项见 [M3 设计](M3_DESIGN.md)。集成验收已于 2026-10-05 完成，结果、用例组明细与证据索引见 [M0 与 M3 验收记录](ACCEPTANCE_M0_M3.md)；唯一剩余项为真实公网网页抓取（环境受限未验证，非产品缺陷）。云端部署、综合测试与论文归入 M4。

三个阶段之外，回收站与归档保留、笔记模板、Markdown 图片引用、笔记日报/周报、日程提醒、知识工作台、Agent 调用链与请求级审计在同一开发窗口内一并落地，**不属 M1–M3 必做验收门槛**；逐项编号、接口、数据表与验证脚本见 [功能全量清单与阶段对照](FEATURE_INVENTORY_2026-10.md)。`app/ops/audit_middleware.py` 提供请求层访问日志（纯 ASGI 实现，不介入响应体流转以免影响 SSE 流式接口），与业务审计分两层按 `request_id` 关联。
