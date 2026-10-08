# M2 本地验证记录

日期：2026-10-02。环境：Apple Silicon Mac、本地 Docker Compose、PostgreSQL 18 + pgvector 0.8.6、Ollama 0.35.0。外部聊天模型使用本地 OpenAI 兼容模拟服务，未使用真实 DeepSeek Key 或产生外部调用费用。

本记录保存 M2 的本地模拟服务及历史回归证据。第二阶段已由项目负责人确认验收完成；真实 DeepSeek 服务验证未包含在本记录中，不影响该签核。云端演示部署及 Embedding 资源、检索验证记录归入最后的 M4 测试与论文阶段。M3 进度见 [M3 设计](M3_DESIGN.md)。

第二阶段目标现增加“持久化 AI 对话接入个人知识库”。原检索会话只保存结果快照，不代表已完成 Agent 对话接入；新目标需完成实现和独立验收后才能签核。

本节记录的 2026-10-03 验收版本将持久化消息接口接入只读问答 Agent：使用账号配置的聊天模型、本人笔记检索、当前轮引用核验和最近 8 条有界历史；无模型连接时提示配置，模型失败不保存半轮消息。此后当前代码增加了按本轮明确用户指令启用的新建/修改工具，未改变问答检索工具只读的边界；该写入扩展不属于本节历史验收证据。前端展示模型配置入口、回答及可打开引用。真实 DeepSeek 服务验证仍待完成。

## 知识库对话接入验收（2026-10-03）

更新后的 `scripts.verify_conversations` 通过：模拟 Agent 结果随双方消息一同保存，回答与来源引用可恢复；旧引用编号不会作为本轮引用传入；历史从 6 条增长至 8 条后保持上限，超长历史消息截断至 1600 字符；模拟未配置模型返回 409 时，消息数不变。会话重命名、删除、跨账号 404、未登录拦截及长问题保存也通过。该脚本使用受控 Agent 响应，不单独证明真实模型质量。

同轮回归结果：`scripts.verify_m2` 通过（Key 密文、模型连接、Agent 引用核验、分析、分类确认/拒绝及账号隔离）；`scripts.verify_m1`、`scripts.verify_lifecycle` 通过；`scripts.check_integrity` 的 14 项均为 0。`web/npm run build`（包含 `vue-tsc --noEmit` 与 Vite production build）通过，修改后的 Python 文件 `compileall` 通过。未调用真实 DeepSeek 服务。

## 本机回归复验（2026-10-03）

在当前 Docker Compose 环境重新运行 `scripts.verify_m1`、`scripts.verify_lifecycle`、`scripts.verify_m2`、`scripts.verify_conversations` 和 `scripts.check_integrity`，均通过；完整性检查 14 项计数均为 0。于 `web/` 运行 `npm run build`，`vue-tsc --noEmit` 与 Vite production build 均通过。本次复验覆盖本地模拟模型和 M1/M2 API 回归；未运行真实 DeepSeek 服务，也未模拟聊天模型服务故障，因此这两项仍需分别验证。

## 数据迁移与结构

| 检查 | 结果 |
| --- | --- |
| 迁移前备份 | `.local-backups/pre-0005-2026-10-02.dump`（本地忽略提交） |
| 临时库从旧迁移 `0003` 经 `0004` 到 `0005`，再回退 `0004` | 通过；旧数据与数字状态映射验证通过 |
| 本地库迁移版本 | `0005_model_connections` |
| Alembic 模型一致性 | `No new upgrade operations detected` |
| 当前应用表 | 11 张业务表及 `pkm_alembic_version`，全部 `pkm_` 前缀 |
| 外键与索引预算 | 外键 0；每张业务表 2–3 个物理索引；模型连接表 2 个 |
| 数据完整性巡检 | 12 项均为 0，包括模型连接无孤儿账号 |

## 功能验收

`docker compose --env-file .env.local exec -T api /app/.venv/bin/python -m scripts.verify_m2` 使用本地模拟模型执行实际 HTTP 兼容调用与 LangChain 工具循环，结果通过：

- 两账号隔离；其他账号的笔记分析返回 404。
- API Key 密文不包含明文；GET 仅返回遮罩；连接测试可调用模型；删除清空密文并软删，之后 Agent 请求返回 409。
- 问答先调用本人笔记搜索工具，回答中的引用由服务端重新核对笔记归属、版本和原文位置；模拟模型输出不存在的 `[S999]` 时，服务端丢弃回答并返回无可核对依据。
- 分析先调用本人笔记读取工具，返回分析、建议和引用。
- 分类只返回建议；拒绝时笔记未变；接受时通过原有 `PATCH /v1/notes/{id}` 带版本号提交。服务端重新检查分类 ID 的账号归属和活跃状态。
- 模拟服务验证模型请求携带输出 Token 上限及关闭思考模式的参数。

M1 回归：`verify_m1` 和 `verify_lifecycle` 均通过。前端 `npm run build` 与 `docker compose build web` 通过；API 镜像包含 M2 依赖且构建通过。五个常驻服务运行，API/Web/数据库/Ollama 健康；通过 Web 代理请求 `/health/ready` 返回健康，未登录访问 M2 设置接口返回 401。

## 尚需真实服务验证

没有用户的 DeepSeek API Key，因此未实测真实服务商的鉴权、额度、费用、响应延迟或实际回答质量。用户可在本地页面“笔记助手”配置 Key 后先运行“测试连接”，再用自己的笔记检查问答和引用。当前本地模拟服务证明的是协议和应用流程，不代表外部服务可用性或回答正确率。

## 持久化检索对话补充验收（2026-10-03）

Alembic `0007_assistant_conversations` 新增两张对话业务表并成功升级本机数据库；`alembic check` 无模型差异。`scripts.verify_conversations` 使用临时双账号和受控检索结果验证创建、发送、双方消息原子保存、历史恢复、检索降级状态、151 字拒绝、未登录拦截及跨账号 404；验收账号与消息在脚本结束时清理。`scripts.check_integrity` 14 项均为 0。既有 `scripts.verify_m1`（包括实际 Ollama 同义检索）和 `scripts.verify_m2` 回归通过，前端 `npm run build` 通过。

该部分是接入 Agent 前的历史验收基线：当时检索对话不调用聊天模型，UI 展示服务端保存的检索快照。当前持久化 AI 对话目标已调整为 Agent 回答；旧消息仍按其检索快照格式兼容展示。

## 查询改写与 Top 5 证据验收（2026-10-03）

本次改造后重建 API 镜像，并在本地 Docker Compose 数据库上重新运行 `scripts.verify_m2` 与 `scripts.verify_conversations`，两项均通过。M2 验收覆盖完整原问题传入改写器、改写 JSON 无效时回退原问题、检索结果限制为 5 条、引用服务端核验及账号隔离；持久化会话验收覆盖改造后的共享问答流程、引用、历史长度、失败回滚和账号隔离。日志中的 `JSONDecodeError` 是 M2 脚本主动注入的无效改写响应，用于验证降级，不代表验收失败。未调用真实聊天模型服务；真实模型下的改写质量与回答质量仍待配置服务后验证。

## 对话列表与输入补充验收（2026-10-03）

迁移 `0008_assistant_lifecycle` 已增加会话软删除字段。会话 API 验收新增标题重命名、空标题拒绝、软删除后列表隐藏和详情 404、跨账号修改/删除 404，以及超过 150 字的问题成功提交；会话验收脚本通过。`alembic check` 无模型差异，`scripts.check_integrity` 14 项均为 0，`npm run build` 通过。前端列表提供行内重命名和二次确认删除；输入框无字符上限，Enter 发送、Shift+Enter 换行，并展示账号当前配置的模型名称。该验收记录描述接入知识库 Agent 前的状态。
