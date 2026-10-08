# 个人知识管理系统 · M1–M3 阶段开发与验收

本目录是 Python/Vue 工程。M1 提供注册登录、Markdown 笔记、笔记本和标签、关键词与向量混合检索，已完成验收。M2 提供用户自备模型 API Key、知识库问答、笔记分析、分类建议与持久化对话，已由项目负责人确认验收完成。M3 文件导入、对象存储、内容识别、图片语义描述与网页草稿已实现，集成验收已于 2026-10-05 在隔离环境完成，唯余**真实公网网页抓取**因宿主本地代理 fake-IP DNS 污染环境受限未验证（非产品缺陷）；验收记录与证据索引见 [M0 与 M3 阶段验收记录](ACCEPTANCE_M0_M3.md)。各阶段分别签核。

## 阶段进度

| 阶段 | 状态 | 依据 |
| --- | --- | --- |
| M0：开题与设计 | 已完成 | [M0 与 M3 验收记录](ACCEPTANCE_M0_M3.md) §一 |
| M1：第一阶段演示 | **已验收（2026-10-02，项目负责人确认）** | [M1 验收记录](M1_VERIFICATION.md) |
| M2：第二阶段演示 | **已验收（项目负责人确认）** | [M2 验证记录](M2_VERIFICATION.md) |
| M3：多格式笔记与网页草稿 | **集成验收完成（唯余公网网页抓取环境受限未验证）** | [M3 设计与进度](M3_DESIGN.md)、[M0 与 M3 验收记录](ACCEPTANCE_M0_M3.md) |
| 扩展功能（跨阶段，不计入三阶段验收门槛） | 已实现：回收站与归档保留、笔记模板、Markdown 图片引用、笔记日报/周报、日程提醒、知识工作台、Agent 调用链、请求级审计 | [功能全量清单与阶段对照](FEATURE_INVENTORY_2026-10.md) |
| M4：测试与论文 | 后续推进：云端演示部署、综合测试、结果分析与论文 | [毕业设计任务书](../../毕业设计任务书-基于AI%20Agent的个人知识管理信息系统.md) |

三个阶段（M1 基础系统与检索、M2 Agent 赋能、M3 多格式笔记与网页草稿）的需求均已落地实现，**产品阶段之后只剩 M4（测试与论文）**。三阶段必做范围内的功能全部有阶段归属；另有 11 项扩展功能在同一开发窗口内一并落地但不属必做门槛，逐项编号、接口、数据表与验证脚本见[功能全量清单与阶段对照](FEATURE_INVENTORY_2026-10.md)。

各阶段需求与当前代码/验收证据的集中核对见[功能全量清单与阶段对照](FEATURE_INVENTORY_2026-10.md)，其中第十一节记录了两处需求描述与代码现状冲突的修正。该清单区分代码缺漏与尚未完成的环境集成验收，不代替各阶段验收签核。

M3 集成验收的环境准备、用例组结果、通过标准、遗留事项与证据索引，见[M0 与 M3 阶段验收记录](ACCEPTANCE_M0_M3.md)与 [M3 验收证据索引](../test-results/m3/EVIDENCE_INDEX.md)。

M1 已完成本机验收。M3 已接入上传 SHA-256 重复预检和服务端复核；文件原件存入 S3 兼容 MinIO 对象存储的 `minio_data` 持久卷，历史本地文件仍可从 `note_files` 读取，并由迁移脚本逐件校验哈希后切换。DOCX/XLSX/PDF 在线编辑与旧版 Office 转换使用 ONLYOFFICE `office` profile，本地启动脚本会一并启动该服务。上述能力仍需按 [M3 设计与进度](M3_DESIGN.md)完成集成验收；云端部署与综合验收列入 M4。

## 本地启动

日报在设置页管理，周报在独立周报页管理，均按北京时间定时生成可编辑的 Markdown 笔记。用户可在合并的“日程提醒”页创建独立提醒或关联已有笔记，也可在笔记编辑器创建关联提醒；两处共用居中弹窗。选中月历日期后，右侧面板分别显示当天未完成和已完成提醒，状态可以双向切换；下方保留全部未完成提醒。月历、提醒列表和工作台读取同一份服务端数据。`digest-worker` 负责报告调度，模型调用失败时保留失败任务，工作台和周报页可重试。验证命令：`docker compose --env-file .env.local exec -T api /app/.venv/bin/python -m scripts.verify_digests_reminders`。

需要已启动的 Docker Desktop、Docker Compose 和宿主机 Python 3（只用于选择空闲端口并调用 Compose）。应用、数据库、模型和前端进程全部在容器中运行。

```bash
cd pkm-system
python3 scripts/dev-up.py
```

脚本选择空闲 Web 与对象存储端口，写入权限为 `0600` 的 `.env.local`（包含对象存储凭据和模型连接加密主密钥），再构建并启动应用、MinIO、识别 worker 和 ONLYOFFICE 文档服务。打开脚本打印的 Web 地址；本机 S3 API 地址也会一并打印。API 文档位于 Web 地址的 `/docs`。数据库、API、worker 和 Ollama 不映射宿主机端口。

首次启动后，使用一次性容器拉取文本嵌入模型和图片描述模型，再运行嵌入模型验证：

```bash
docker compose --env-file .env.local --profile model-setup run --rm model-init
docker compose --env-file .env.local exec api /app/.venv/bin/python -m app.ops.probe
```

手动使用 Compose 启动应用时，可通过 profile 一并启动 ONLYOFFICE 服务：

```bash
docker compose --env-file .env.local --profile office up -d documentserver
```

文档服务首次启动需要额外下载镜像并占用较多内存；本地启动脚本会生成随机签名密钥，部署环境应在 `.env.local` 中设置随机 `ONLYOFFICE_JWT_SECRET`。

模型下载容器首先调用 Ollama 官方拉取接口。若本地网络把模型文件重定向地址解析为受限地址，脚本会从官方注册表下载并校验 SHA256，再通过 Ollama 的 Blob API 导入，最后登记官方模型清单。

首次启动时完成模型下载后，刷新网页并注册账号。模型初始化会从 Ollama 拉取文本嵌入模型 `qwen3-embedding:0.6b` 和本地图片描述模型 `qwen3-vl:2b-instruct`。上传面板合并文件与链接导入，文件支持多选、拖拽、最多 3 个并行上传、5 MiB 分块和会话恢复；后端按文件版本运行提取、图片语义描述与索引任务。PNG 和扫描 PDF 页由本地 Ollama 生成可检索的图像描述，不提取图片中的文字。业务接口统一从 `/v1` 开始，见 [接口设计](API_DESIGN.md)。

登录后点击侧边栏“AI 对话”，配置聊天模型后即可与本人笔记进行引用式问答。对话历史与经核验的答案来源按账号隔离保存；模型未配置时页面会提示配置。笔记分析和分类建议也使用个人设置中的 DeepSeek API Key；Key 在服务端加密保存，页面不会回显。分类建议不会自动写入笔记，需检查后确认。聊天模型不可用不会影响笔记、关键词搜索和普通混合检索。请妥善备份 `.env.local` 与数据库卷：丢失其中的加密主密钥会使已保存的连接无法解密，可重新填写 Key 恢复使用。

常用检查：

```bash
docker compose --env-file .env.local config --quiet
docker compose --env-file .env.local ps
docker compose --env-file .env.local logs --tail=100 api db ollama web
docker compose --env-file .env.local down
```

本地 M1 验收与固定 20 题评测（临时账号和资料会自动清理）：

```bash
docker compose --env-file .env.local exec -T api /app/.venv/bin/python -m scripts.verify_m1
docker compose --env-file .env.local exec -T api /app/.venv/bin/python -m scripts.verify_lifecycle
docker compose --env-file .env.local exec -T api /app/.venv/bin/python -m scripts.check_integrity
docker compose --env-file .env.local exec -T api /app/.venv/bin/python -m scripts.evaluate_m1 > evaluation/latest.json
```

M2 接口与数据验收使用容器内的本地模拟模型，不需要真实 Key；真实服务联通需在页面填写自己的 Key：

```bash
docker compose --env-file .env.local exec -T api /app/.venv/bin/python -m scripts.verify_m2
docker compose --env-file .env.local exec -T api /app/.venv/bin/python -m scripts.verify_conversations
docker compose --env-file .env.local exec -T api /app/.venv/bin/python -m scripts.check_integrity
```

`down` 不删除数据卷。请勿使用 `down -v` 清理实际笔记数据。修改源码后重新运行启动脚本构建镜像。本地 Docker 中的 Ollama 在 Apple Silicon 上使用 CPU，延迟按实际测量记录。

## 服务状态

| 路径 | 意义 | 失败影响 |
| --- | --- | --- |
| `/health/live` | API 进程存活 | 无 |
| `/health/ready` | 数据库可连接且已迁移 | 基础服务不可用 |
| `/health/embedding` | Ollama 可连接且指定模型已安装 | 语义检索不可用，基础服务仍可用 |

## 文档

核心事实源：

- [项目总览与系统架构](../README.md)
- [架构与阶段边界](ARCHITECTURE.md)
- [功能全量清单与阶段对照（M0–M4）](FEATURE_INVENTORY_2026-10.md)
- [数据库设计](DB_DESIGN.md)
- [完整数据库设计表与字段字典](DATABASE_DICTIONARY.md)
- [API 接口设计与 CRUD 路由总览](API_DESIGN.md)
- [M2 接口与数据设计](M2_DESIGN.md)
- [M3 多格式笔记与网页草稿设计及进度](M3_DESIGN.md)
- [版本兼容记录](VERSIONS.md)
- [云端演示部署（M4）](DEPLOYMENT_CLOUD.md)

验收与证据：

- [阶段验收记录：M0 与 M3](ACCEPTANCE_M0_M3.md)
- [M1 验证记录](M1_VERIFICATION.md)
- [M2 验证记录](M2_VERIFICATION.md)
- [M3 验收证据索引](../test-results/m3/EVIDENCE_INDEX.md)

设计与参考：

- [设计决策记录（前端页面）](../design/DESIGN_DECISIONS.md)
- [枫叶纸感视觉规范](../design/maple-style.md)
- [固定评测题集](../api/scripts/evaluation_cases.json)

归档：

- [操作日志能力评估与改造方案（已落地，留档）](archive/AUDIT_LOG_REDESIGN.md)
- [文档清点与处置清单](DOC_INVENTORY_2026-10.md)
