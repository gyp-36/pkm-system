# M3 设计：多格式笔记与网页草稿

状态：**主要功能已实现，集成验收已于 2026-10-05 在隔离环境完成**（唯余真实公网网页抓取一项因环境 DNS 污染受限未验证）。第二阶段已由项目负责人确认验收完成；M3 按独立验收门槛推进。验收结论见 [M0 与 M3 验收记录](ACCEPTANCE_M0_M3.md)。原“测试与论文”里程碑顺延为 M4。

## 实现进度

- 已落地：`0009`–`0012` 数据迁移；S3 兼容 MinIO 对象存储、分块上传会话/幂等键/过期清理、对象迁移校验脚本；上传前 SHA-256 重复预检和服务端复核；统一文件/链接导入面板、多文件进度/续传/单项重试；持久文件识别任务；DOCX 表格、XLSX 行列、PDF 页定位；本地 Ollama 视觉模型为 PNG 与扫描 PDF 生成图片语义描述，不提取图片中文字；ONLYOFFICE、PNG 图片预览、导出和链接草稿流程。
- 已完成初步校验：前端 `npm run build`、Python 源码编译、Alembic head 检查、API 镜像构建已验证。2026-10-04 的功能核对抽样通过了 MD/DOCX/XLSX/PDF/PNG 上传和原件读取、DOCX/XLSX/PDF 搜索位置、PNG Ollama 语义描述、分块上传续传与重复复核、笔记本 ZIP 字节一致、链接草稿发布边界和部分双账号隔离。
- 集成验收状态（2026-10-05）：旧本地文件迁移（MIG-01~05，含本地文件缺失/校验不符/对象存储写入失败等故障注入）、ONLYOFFICE 真实浏览器编辑与保存回调（`status=2`/`status=6`、旧回调拒绝）及 DOC/XLS 转换确认流、批量断网续传与并发竞态（UP-01~05，含前端并发 ≤3）、完整格式矩阵（MD/DOCX/XLSX/PDF/PNG 站内编辑、索引位置核对与导出）均已在隔离环境通过。**唯一未闭环项是真实公网网页抓取**——宿主本地代理 fake-IP DNS 污染使解析落到 RFC 2544 / RFC 5180 benchmarking 保留段，被 SSRF 门禁按设计拒绝（环境网络问题，非产品缺陷），取证见 `test-results/m3/web-dns-gate-2026-10-05.txt`。DNS 固定连接、恶意重定向拦截、草稿分类归属、单篇/ZIP 导出和过期回调等专项缺陷已修复，详情见 [M0 与 M3 验收记录](ACCEPTANCE_M0_M3.md)「修复项与数据处置」。
- 2026-10-05 本轮在运行中的 Compose 验证环境重跑 `verify_m1`、`verify_m2`、`verify_conversations`、`verify_lifecycle`、`verify_m3_fixes`，全部通过；`check_integrity` 全项为 0，Web `npm run build` 通过。同日完成 M3 集成验收（结果见 [M0 与 M3 验收记录](ACCEPTANCE_M0_M3.md)）；尚余真实公网网页抓取 1 项因环境 DNS 污染未验证。
- 部署：本地对象存储采用 MinIO，通过 `minio_data` 持久卷保存对象；旧文件在校验迁移后仍保留在 `note_files` 卷。ONLYOFFICE Docs 通过 `office` Compose profile 提供。其他主机部署前须配置对象存储凭据、随机 `ONLYOFFICE_JWT_SECRET` 及可互通的 ONLYOFFICE URL。

## 目标与边界

- 一个笔记条目可保存 Markdown 正文，或以文件为主要内容；两类条目继续共用当前账号、笔记本、标签和列表。支持 `.md`、`.docx`、`.xlsx`、`.pdf`、`.png`、`.doc`、`.xls` 上传及站内查看；DOCX/XLSX/PDF 可编辑，图片支持预览和缩放。
- DOCX/XLSX 由自托管文档编辑服务处理；PDF 验收批注、填写和页面操作；图片验收预览和缩放，不包含图片修改与保存。`.doc`/`.xls` 上传时先提示转换，用户确认后生成 DOCX/XLSX 可编辑版本，原件单独保留下载；不能把转换后的文件称为仍是 DOC/XLS 原格式。
- ONLYOFFICE Docs 由 `office` Compose profile 提供；推荐启动脚本会自动启用。编辑配置、文档取件及保存回调验证签名和版本。[官方打开文件流程](https://api.onlyoffice.com/docs/docs-api/get-started/how-it-works/opening-file/)与[回调说明](https://api.onlyoffice.com/docs/docs-api/usage-api/callback-handler/)是实施参考。社区版限制 20 个同时编辑连接；外部自动化 Connector 属 Developer 版，因此不承诺所有格式自动跳至精确位置。[社区版限制](https://helpcenter.onlyoffice.com/zh/docs/faq/docs-community.aspx)、[自动化接口](https://api.onlyoffice.com/docs/docs-api/usage-api/methods/)
- PNG 与扫描 PDF 页通过本地 Ollama 上的视觉模型生成简短中文语义描述；不对图片或扫描页执行 OCR，也不提取图片中文字。模型服务不可用时保留原件并允许重试。图片向量检索、DOCX/XLSX 内嵌图片识别、浏览器扩展剪藏、系统完整备份和协作编辑不在本阶段验收内。

## 文件与检索数据流

1. 浏览器先计算文件 SHA-256 并请求账号范围内的重复预检；命中时提示已有文件。上传仍由服务端在完成时复核哈希和重复状态，不能只依赖浏览器预检。浏览器将文件切成 5 MiB 分块，经带短期签名的 URL 直传 S3 兼容对象存储；API 持久化上传会话和已确认分块。每个会话按账号和幂等键去重。单文件上限 25 MiB，未完成会话 24 小时后由 worker 中止和清理。
2. 原件与不可变版本保存在对象存储；数据库只记录对象键、类型、原名、大小、哈希、账号、笔记和版本。迁移脚本按件核对本地文件与对象的大小和 SHA-256，通过后再切换读取后端。检索文本写入笔记正文和带来源位置的文本块，不改写原二进制文件。
3. MD 提取正文；DOCX 按段落与表格行、XLSX 按工作表和带单元格坐标的行、文字型 PDF 按页提取；PNG 与扫描 PDF 页由本地 Ollama 视觉模型生成简短图像语义描述，不提取图中文字。解析任务持久化并在后台执行；单文件失败不影响同批其他文件，旧版本任务不能覆盖新版本内容。
3. 关键词、混合检索和 Agent 只使用当前账号、当前文件版本的提取文本。文件型结果返回片段、文件类型、内容版本及位置对象（DOCX 段落、XLSX 工作表/单元格、PDF 页码）；现有 Markdown 的 `source_field` 与 Unicode 偏移字段保持兼容。可稳定跳转时直接跳转，其他情况打开文件并提供片段搜索。Agent 引用在返回前重新核验原文、版本和账号；Agent 可分析提取文本、建议分类，但不直接改写二进制文件。
4. 文档服务故障时允许下载已存文件和修改标题、笔记本或标签；未保存的编辑不能显示为已保存。文档保存回调与浏览器 PNG 保存都使用当前版本校验，冲突时保留旧版与新提交内容供用户处理，不能静默覆盖。云端 M4 部署前需再核定文档服务资源、存储备份与 HTTPS 入口。

## 内容导出

| 范围 | 计划行为 |
| --- | --- |
| 单篇 | `GET /v1/notes/{id}/export` 继续使用，按当前版本格式返回文件；从未编辑的上传文件按原字节返回。 |
| 笔记本 | 新增 `GET /v1/notebooks/{id}/export`，ZIP 中仅包含该笔记本的当前活跃笔记文件。 |
| 全部 | `GET /v1/notes/export` 保持路径，ZIP 中按笔记本目录容纳本人所有活跃笔记。 |

导出文件本身不注入系统 ID、标签、时间或新的 YAML front matter。ZIP 不放 README 或清单；笔记本路径保留基本组织结构，重名文件以普通序号消歧。草稿、已删除笔记及未保存编辑不进入导出；此处“内容导出”不保证重新导入后还原分类和历史版本；系统备份另列后续需求。

## 网页链接草稿

1. 用户主动提交公开 HTTP(S) URL 后，API 先持久化 `pending` 草稿并立即返回，由独立 `link-fetch-worker` Agent 从数据库队列领取任务；worker 对初始 URL、DNS 返回的 IPv4/IPv6 地址及每次重定向重新校验，拒绝环回、私有、链路本地和云元数据地址，并限制跳转次数、下载体积与抓取时长。网页内容只按文本提取，不在系统内执行网页脚本。Agent/worker 崩溃留下的 `processing` 任务可在超时后重新领取。[OWASP SSRF 指引](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
2. 保存本人可继续编辑的草稿、来源 URL、抓取状态以及不可由 Agent 覆盖的只读原文快照。仅凭 URL 抓取可能缺失登录后或动态加载的正文，故抓取不完整时用户可校正或粘贴正文；抓取失败可建立“未获取原文”的手工草稿，界面不得声称已经识别网页。按规范化 URL 在本账号活跃草稿和已发布链接笔记中提示重复。[Readwise 抓取说明](https://docs.readwise.io/reader/docs/faqs/parsing)
3. 草稿与正式笔记分开列示，不进入笔记导出、搜索或 Agent 知识库。现有聊天模型连接可对**用户草稿**生成改写建议；建议不自动应用、不改变原文快照，不增加第二个 Agent。模型未配置或失败时，手动编辑与发布仍可用。用户确认发布后才生成 Markdown 笔记，保留来源 URL 供查看；删除草稿不删除已发布笔记。
4. 链接草稿在独立工作区中编辑和预览，助手在右侧手动生成摘要、关键要点与行动建议。用户逐项选择后，建议以对应标题追加到草稿正文；分析基于只读原文快照。窄屏将建议面板移至编辑区下方。抓取失败或正文为空时允许手动补充；模型不可用不影响编辑、保存和发布。

## 已实现接口（集成验收结果见 [M0 与 M3 验收记录](ACCEPTANCE_M0_M3.md)）

| 路径 | 主要输入/输出 |
| --- | --- |
| `POST /v1/notes/upload` | `multipart/form-data`：文件、可选笔记本和 `convert_legacy` 确认；返回笔记、当前文件与解析状态。 |
| `POST/GET /v1/file-uploads/sessions`、`GET /v1/file-uploads/sessions/{id}` | 创建幂等上传会话、恢复分块进度并查询识别/索引状态。 |
| `POST /v1/file-uploads/sessions/{id}/parts/{number}/url`、`PUT .../receipt`、`POST .../complete`、`DELETE .../{id}` | 签发分块 URL、持久化分块回执、完成校验/保存、取消未完成会话；`POST .../retry-ingest` 可重试识别或索引。 |
| `GET/PUT /v1/notes/{id}/file` | 查看或保存当前文件；带 `version` 时可下载保留的原始旧版 Office 文件。写入使用笔记预期版本，冲突返回 409。 |
| `GET /v1/notes/{id}/editor-config`、`POST /v1/integrations/onlyoffice/callback/{id}`、`GET /v1/files/{storage_key}` | 为本人签发短期文档取件链接与编辑配置；验证服务回调并保存新版本。回调使用服务签名，不接受浏览器伪造身份。 |
| `GET /v1/notebooks/{id}/export` | 当前账号该笔记本 ZIP；单篇和全部导出沿用现有路径。 |
| `GET/POST /v1/link-drafts`、`GET/PATCH/DELETE /v1/link-drafts/{id}` | 创建、列出、读取、修改和删除本人草稿；创建先入队并返回 `pending` 状态，独立 Agent worker 异步抓取，前端轮询状态；草稿与正式笔记分开保存。 |
| `POST /v1/link-drafts/{id}/analyze`、`POST /v1/link-drafts/{id}/rewrite`、`POST /v1/link-drafts/{id}/publish` | 分析返回摘要、关键要点和行动建议；改写只返回建议；发布再次校验本人分类后创建正式笔记。 |

接口中 `user_id` 一律从登录会话取得；其他账号资源仍返回 404。文件型搜索结果增加 `location` 与 `content_kind`，现有 Markdown 搜索及引用字段保持有效。具体契约以 OpenAPI 与实现为准。

## 验收门槛

- 五种主格式逐一完成上传、站内查看、范围内的编辑、保存、重新打开与同格式导出；DOC/XLS 转换有明确确认和原件下载。文件版本、编辑冲突与文档服务故障行为可复现。
- 文字型文件的当前版本可检索，结果呈现可核对的位置与片段；旧版或已删除内容不进入搜索与 Agent 引用。逐格式记录直接跳转可用性及片段搜索兜底。
- 单篇、笔记本与全部导出不含系统注入的文件内元数据或 ZIP 附加清单；未编辑上传文件导出字节一致。双账号交叉访问文件、原件、草稿、索引和导出均被拒绝。
- 网页正常、不完整、失败、重复和恶意内网/重定向 URL 均有验证；草稿刷新后保留，Agent 建议不自动应用，发布前不进入正式知识库。
- M1、M2 的 Markdown CRUD、分类、检索、引用和持久化会话回归通过。当前有历史回归记录，但需在 M3 验收轮次重新运行并记录；不能仅凭初版实现将 M3 标记为完成。
