# M2 接口与数据设计

依据根目录 PRD V2.2 的 M2 范围。M2 在现有 M1 检索服务上新增用户自备聊天模型连接、笔记助手 Agent，以及持久化的知识库问答对话。问答检索工具只读；同一助手还允许用户明确要求新建或修改笔记时调用写入工具，工具按本轮意图启用并由业务层校验账号、分类和版本。建议、分析或聊天内容本身不构成写入授权；Agent 不提供删除工具。会话消息由 Agent 检索当前用户笔记、生成并核验引用；当前本地运行。第二阶段已由项目负责人确认验收完成；本地模拟服务和历史回归证据见 [M2 验证记录](M2_VERIFICATION.md)。M3 具体状态见 [M3 设计](M3_DESIGN.md)；云端系统与 Embedding 部署及验证列入最后的 M4 测试与论文阶段。

## 模型连接

预置服务商为 DeepSeek（`provider=1`），服务端固定官方 Chat Completions 入口 `https://api.deepseek.com`，页面可选择 `deepseek-flash` 或 `deepseek-v4-pro`。前端不能提交任意目标 URL，避免服务端请求被导向内网。官方接口为 OpenAI 兼容格式，具体模型名称以后以服务商公告为准。

Alembic `0005_model_connections` 已新增 `pkm_model_connections`，且仅此一张 M2 表：

| 字段 | 类型 | 可空 | 用途 |
| --- | --- | --- | --- |
| `id` | uuid | 否 | 应用 UUID4 主键 |
| `user_id` | uuid | 否 | 登录账号 ID，普通列，不设外键 |
| `provider` | smallint | 否 | `1=DeepSeek`，由代码 `IntEnum` 映射 |
| `model_name` | varchar(120) | 否 | 服务端允许列表内的模型名 |
| `base_url` | text | 是 | 预留；预置服务商使用服务端常量，此列为空 |
| `credential_ciphertext` | bytea | 否 | Fernet 加密的 API Key；删除时清空为零长度 |
| `credential_key_id` | varchar(64) | 否 | 本地密钥标识 `local-v1`，支持以后轮换 |
| `created_at` | timestamptz | 否 | 数据库 `now()` |
| `updated_at` | timestamptz | 否 | 数据库 `now()`；更新触发器维护 |
| `deleted_at` | timestamptz | 是 | 删除时间；空值为活跃 |

索引恰好两个：主键 `(id)`；部分唯一索引 `(user_id) WHERE deleted_at IS NULL`。同账号只有一个活跃连接；不设置任何外键、PG ENUM 或枚举 CHECK。`PKM_CREDENTIAL_KEY` 是 `.env.local` 中的 Fernet 主密钥，Compose 只注入 API，不能进入数据库、前端或日志；本地备份需同时保护该文件，丢失密钥后旧连接无法解密。已有 `.env.local` 由启动脚本补充密钥，新安装时自动生成。

Alembic 迁移脚本 `0007_persistent_assistant_conversations.py`（revision `0007_assistant_conversations`）新增 `pkm_assistant_conversations` 与 `pkm_assistant_messages`；`0008_assistant_conversation_lifecycle.py` 为会话增加软删除时间。每表各有主键索引和一个按当前账号查询的复合索引。消息角色用 `smallint`（`1=user`、`2=assistant`），`content` 使用 JSONB；数据库不设外键，服务在每次请求中同时校验 `user_id` 与 conversation ID。

## 接口契约

业务路径继续用 `/v1`，均使用现有 `pkm_session` Cookie；没有角色权限矩阵。所有笔记和分类 ID 按会话 `user_id` 与活跃状态重新校验。错误沿用 `{detail:...}`，敏感凭据绝不写入响应或日志。

| 方法与路径 | 请求 | 成功响应 | 错误 |
| --- | --- | --- | --- |
| `GET /v1/model-connection` | 无 | `{configured,provider,model_name,key_masked,updated_at}`；未配置字段为空 | 401 |
| `PUT /v1/model-connection` | `{api_key,model_name}` | 同 GET，Key 只存密文；替换会覆盖旧密文 | 401、422 |
| `POST /v1/model-connection/test` | `{api_key?,model_name?}`；不填用已保存连接 | `{ok:true,model_name}`；实际向服务商发出短提示 | 401、404（未配置）、502（模型服务拒绝或故障） |
| `DELETE /v1/model-connection` | 无 | 204，清空密文并软删连接 | 401、404 |
| `POST /v1/assistant/ask` | `{question}`，1–500 字 | `{answer,citations,semantic_status,answer_source}` | 401、409（未配置）、429、502 |
| `POST /v1/assistant/analyze` | `{note_id}` | `{analysis,suggestions,citations}`；只读 | 401、404、409、429、502 |
| `POST /v1/assistant/classify` | `{note_id}` | `{note_id,note_version,notebook_id,tag_ids,reason}`；只建议 | 401、404、409、429、502 |
| `GET /v1/assistant/conversations` | 无 | `{items:[{id,title,created_at,updated_at}]}`，当前账号会话按更新时间倒序 | 401 |
| `POST /v1/assistant/conversations` | 无 | 创建并返回空会话摘要 | 401 |
| `GET /v1/assistant/conversations/{id}` | 会话 UUID | 会话摘要及时间正序消息 | 401、404 |
| `PATCH /v1/assistant/conversations/{id}` | `{title}`，1–120 字 | 更新后的会话摘要 | 401、404、422 |
| `DELETE /v1/assistant/conversations/{id}` | 会话 UUID | 204，软删除会话并保留消息 | 401、404 |
| `POST /v1/assistant/conversations/{id}/messages` | `{question}`，去除首尾空白后非空；无字数上限 | 会话摘要及本轮用户消息、Agent 回答、经核验引用与语义状态 | 401、404、409（未配置模型）、422、429、502 |

持久化 AI 对话要求当前账号已配置聊天模型；未配置时返回 409 并提示先配置，不保存本轮问题。Agent 使用与 `/v1/assistant/ask` 相同的账号限定搜索工具和引用核验流程。助手消息内容为 `{answer,citations,semantic_status,answer_source}`；`answer_source` 为 `knowledge_base`、`mixed` 或 `model_knowledge`。每条引用保存笔记 ID、版本、来源字段、偏移、原文和标题，打开时客户端重新读取当前笔记并按版本校验。旧版 `{items,semantic_status}` 检索消息仍可读取并显示。

每次请求优先使用本会话最近 8 条消息作为原文历史，每条最多 1600 个字符。消息超过 16 条后，对较早历史按需生成会话摘要，并将摘要及其覆盖到的消息 ID 持久化在会话行中；摘要每累积至少 8 条尚未覆盖的旧消息后更新。摘要最多保留 1600 个字符，是可从完整消息重建的派生上下文，不替代原始记录。首次摘要生成失败时，使用最近 16 条原文继续回答；后续更新失败时，继续使用上一个摘要，并把尚未摘要的消息作为原文上下文。重新打开会话时从 PostgreSQL 恢复摘要和消息，无需依赖进程内缓存。历史助手引用编号不带入模型，引用原文仅用于理解上下文，本轮回答仍须重新检索并使用本轮工具生成的编号。模型调用和笔记检索完成后，服务端在一个数据库事务中一起保存用户问题与助手回答；模型连接缺失、限流或调用失败时不保存半轮消息。会话归属始终由登录态确定，不接收客户端 `user_id`。

较早对话摘要仅帮助理解本会话的目标、用户明确约束、决定、待办及指代；摘要和历史回答均不作为个人笔记事实的证据。删除消息或从旧问题重新提问时清除摘要检查点，以便后续按剩余对话重建。对话摘要不跨会话共享，也不构成用户画像或长期记忆。

`citations` 元素为 `{citation_id,note_id,note_version,title,source_field,start_offset,end_offset,quote}`。后端只从当前账号当前版本的真实笔记片段构建引用，拒绝模型凭空给出的 ID、版本、偏移或引用文本。引用中的 Unicode 偏移沿用 M1 规则。打开引用时客户端重新读取笔记并比对版本；版本变化时提示重新提问。

分类建议只从本人活跃笔记本和标签中选择，不写数据库。接受时客户端调用现有 `PATCH /v1/notes/{note_id}`，带服务端返回的 `note_version` 及最终选择的分类 ID；后端再次校验版本、归属和活跃状态。拒绝时不发写请求。分析与问答同样没有笔记写工具。

## Agent 边界与异常

后端使用 LangChain `create_agent`，模型为从本人连接解密后创建的 `ChatOpenAI`，所有工具均按闭包固定 `user_id`，用户或模型不能传 `user_id` 修改作用域。问答场景只暴露搜索和笔记读取；用户在当前消息中明确要求新建或修改时才启用相应写入工具，修改前须查找并读取目标、使用当前版本并遵守冲突检查。分类建议仍只返回候选，由用户确认后走既有笔记更新接口；工具不提供删除笔记。问答最多两次搜索、两次笔记读取，单次上下文裁剪；设置模型超时、输出 Token、递归深度和每账号短时请求频率限制。模型未配置/服务不可用时不影响 M1 路径。普通检索仍由本地 Ollama Embedding 完成；若其不可用，Agent 仅可使用关键词证据并返回降级状态。

问答搜索工具接收完整问题，不调用远程聊天模型做查询改写或证据重排。关键词检索使用原问题和后端生成的有界关键词变体，向量检索只对原问题调用本地 Embedding；每个查询每路最多取 20 个候选，向量采用当前账号、活跃笔记、当前内容版本过滤及余弦距离 `≤ 0.48`。关键词匹配优先标题命中，再按更新时间排序。初召回候选按同一原文范围去重，关键词与向量按 `k=60` 倒数排名融合，最终最多向 Agent 提供 5 个不同原文范围的证据片段。Agent 在最终回答时判断证据是否直接且充分；若相关但不足，可用不同表达再次调用搜索工具，最多两次。此上限覆盖本轮问答的搜索与笔记读取工具；普通 `/v1/search` 的响应结构不变。

Agent 根据检索片段在最终回答时判断证据覆盖度：笔记足够时以本人笔记为依据；部分足够时引用笔记支持的部分，只对缺失部分用模型通用知识补充；没有合适笔记时用模型通用知识回答并说明个人笔记未找到合适依据。通用知识不伪造笔记引用。响应 `answer_source` 指明 `knowledge_base`、`mixed` 或 `model_knowledge`，前端相应标记来源。当前只实现模型已有知识兜底，尚未配置联网搜索服务。服务端逐条校验引用必须来自本轮工具、对应当前笔记版本及原文偏移和内容；无效引用会被忽略而不使整条答案作废。`/v1/assistant/ask` 与持久化会话使用同一流程。

语义 Embedding 故障时保留关键词检索结果并显示降级状态。常规单次问答包含一次 Agent 工具选择调用和一次最终回答调用；只有 Agent 认为需要换词重查或读取笔记时才增加 Agent 循环调用。查询改写与证据评估不再额外调用远程聊天模型。发送给外部服务商的文本包含当前问题、有限的本会话历史及 Agent 按需取得的本人笔记片段；页面提示这一数据流。`/v1/assistant/ask`、分析和建议接口仍即时返回；持久化 AI 对话在会话消息接口中调用同一 Agent 能力并保存双方消息。服务异常日志仅记录异常类型，不记录 Key、笔记正文或模型完整输出。

## 验收

开发排错可选启用本地 Agent 调用链。`pkm_assistant_traces` 在 `APP_ENV=development|dev|local` 且 `ASSISTANT_TRACE_VIEW_ENABLED=true` 时保存每次 Agent 运行的有序脱敏步骤，并提供开发者专用的查询接口和页面；页面可从持久化对话回答打开详情，所有 Agent 入口均可从记录列表定位。输入、输出正文及笔记内容不入链路记录，维护 worker 每 15 分钟清理 30 天前的链路。

先在临时库演练迁移升降级，再备份并迁移本地库。检查业务表零外键、每表 2–3 个索引、会话和消息跨账号隔离及消息事务完整性；模型连接仍验证密文非明文、GET 不回显和删除清空。用本地伪造的 OpenAI 兼容服务验证持久化对话的笔记检索、有限历史上下文、当前轮引用核验、无模型配置/模型故障时不留下半轮消息，以及分类确认/拒绝；真实 DeepSeek API 需用户自行配置可用 Key 才能联通测试。M1 全套回归必须继续通过。

本地验收结果见 [M2 验证记录](M2_VERIFICATION.md)。
