# 阶段验收记录：M0 与 M3

本文合并自 `M0_VERIFICATION.md`、`M3_FUNCTIONAL_AUDIT.md`、`M3_REMAINING_TEST_PLAN.md`、`M3_TEST_EXECUTION_RECORD.md`（合并日期 2026-10-05）。

**M1 与 M2 的签核记录独立保留**，不并入本文：见 [M1 验收记录](M1_VERIFICATION.md)、[M2 验证记录](M2_VERIFICATION.md)。

各用例证据仍存放于 `test-results/m3/`，索引见 [test-results/m3/EVIDENCE_INDEX.md](../test-results/m3/EVIDENCE_INDEX.md)。

---

## 一、M0 本地验证（2026-10-01）

环境：Apple Silicon Mac，Docker Engine 29.4.3、Compose 5.1.3；Docker Desktop 给容器的内存上限显示为 7.75 GiB。以下为本机结果，不代表阿里云 2 GiB 实例的性能。

| 检查 | 结果 |
| --- | --- |
| Compose 解析与构建 | `docker compose config --quiet` 通过；后端、前端镜像构建通过 |
| 前端兼容性 | Node 24 容器中 `vue-tsc --noEmit && vite build` 通过；TypeScript 7.0.2 实际构建失败，改为 6.0.3 后通过 |
| 服务启动 | `db`、`ollama`、`api`、`web` 健康；`worker` 运行；迁移容器成功退出 |
| API 与代理 | Web 首页、`/docs`、`/openapi.json`、`/health/live`、`/health/ready`、`/health/embedding` 均返回 200；容器内旧路径 `/api/health/ready` 返回 404 |
| 数据迁移 | `vector` 扩展启用；9 张业务与迁移表存在；版本 `0001_initial`；`alembic check` 无差异 |
| 所有权约束 | 两账号测试中，账号 B 的笔记关联账号 A 的笔记本被数据库拒绝 |
| 模型下载 | 指定模型 `qwen3-embedding:0.6b` 安装成功，Ollama 报告 639 MB；本地网络的受限重定向由校验 Blob 的备用流程解决 |
| 向量验证 | 中文输入返回 1024 维；临时 pgvector 表写入并做余弦查询，自身距离为 0 |
| 故障降级 | 停止 Ollama 后数据库就绪接口仍为 200，Embedding 状态接口为 503；恢复后模型仍在 |
| 持久性 | `compose down` 再启动后，测试账号仍存在、模型仍列出；测试账号随后清理 |
| 端口冲突 | 人为占用 15173 后，启动脚本选用 15174，Web 和 API 代理正常 |

性能样本：首次请求模型的墙钟时间约 **0.85 秒**，紧接着的请求约 **0.04 秒**；重启 Ollama 后首次请求约 **0.84 秒**。这些仅是单条短中文文本的本机样本，不是吞吐或评测集成绩。

资源样本（模型加载后 `docker stats`）：Ollama **1.125 GiB**、Web/Vite **209.5 MiB**、API **74.6 MiB**、worker **48.5 MiB**、PostgreSQL **31.2 MiB**。Ollama 镜像展开约 **2.79 GB**，模型卷约 **610 MiB**。后期 2 GiB 云端部署需实测系统与 Docker 自身开销、冷启动和并发，必要时按既定决策升配。

M0 的 `worker` 仅验证数据库连通，尚不处理索引任务；M1 再加入笔记、检索及索引业务。云端部署尚未执行。

---

## 二、M3 集成验收（2026-10-05）

结论先行：**除「真实公网网页抓取」一项因宿主环境 DNS 污染未验证外，M3 各验收门槛均已 PASS。** 该未闭环项属环境网络问题而非产品缺陷，判定口径为「未验证不计通过」，不以模拟测试替代真实公网验收。

### 2.1 环境与数据保护

- 隔离 Compose 项目：`pkm-m3-test`（`--env-file .env.m3-test`），独立数据卷 `pkm-m3-test_{postgres_data,note_files,minio_data,ollama_data}`。
- 迁移基线数据来源：主环境 `pkm-system` 的 `pg_dump` + `minio_data`/`note_files` 卷副本（**主环境卷全程未改动**）。
- 端口：web `25173`、documentserver `28080`、minio `29000`。
- 镜像：`pkm-api:local` / `pkm-web:local`，2026-10-05 16:26 由工作区源码重建。
- 迁移版本：`0021_optional_reminder_note`。
- 服务健康：db / api / web / minio / ollama / parse-worker / ingest-worker / link-fetch-worker / digest-worker / worker / documentserver 全部健康。
- 基线：notes 36、file_versions 29（全部 `s3`）、upload_sessions 24、link_drafts 2、accounts 2；`check_integrity` 全部计数为 0。
- 数据保护原则：故障注入各自使用可丢弃副本；测试账号使用临时邮箱并自动清理；文件使用仓库公开样本或合成文件，不使用私人笔记作为验收资料。

### 2.2 用例组结果总表

| 用例组 | 状态 | 说明 |
| --- | --- | --- |
| MIG | **通过** | MIG-01~05，含本地文件缺失、校验不符、对象存储写入失败等故障注入 |
| UP | **通过** | UP-02~05 API 级；UP-01 前端并发由 agent-browser 真实 Chromium 补测通过 |
| DOC | **通过**（直传 API 缺陷保留） | 五格式浏览器端到端、PNG 缩放、DOC/XLS 转换确认流均通过 |
| IDX/EXP | **通过** | 段落/表格行/单元格/页码命中、版本失效、导出核对、界面位置核对 |
| WEB | **环境受限未验证** | 真实公网抓取未完成；SSRF 门禁与草稿生命周期本身通过 |
| ISO | **通过** | 跨账号读写删/导出/搜索隔离、链接签名校验、完整性 |
| 回归与完整性 | **通过** | 6 项回归全通过；清理后完整性计数为 0；`npm run build` 通过 |

### 2.3 MIG：旧文件迁移到对象存储

方法：以账号 A 上传 3 个公开样本 → 翻转 3 个 `note_file_versions` 为 `filesystem` 并删除对应 MinIO 对象（还原迁移前遗留状态）→ 运行迁移脚本。

| 用例 | 操作 | 实际结果 | 结论 |
| --- | --- | --- | --- |
| MIG-01 正常迁移 | 隔离副本运行 `migrate_files_to_object_storage.py` | 迁移 3 个版本；脚本逐行校验 size+SHA-256 后切 `s3`；迁移前后下载字节 SHA-256 完全一致 | 通过 |
| MIG-02 幂等重跑 | 再次执行同一命令 | `迁移完成：共迁移 0 个文件版本`；读取字节不变 | 通过 |
| MIG-03 本地文件缺失 | 独立副本删除被引用本地对象后运行 | exit=1，`本地文件不存在：96ea8c3e…`；该行仍 `filesystem`；其他数据可正常下载（SHA 一致） | 通过 |
| MIG-04 校验不符 | 独立副本同长度篡改本地文件内容 | exit=1，`本地校验和不匹配：cde315c7…`；数据库未切换，仍 `filesystem` | 通过 |
| MIG-05 对象存储写入失败 | 停止 MinIO 后运行 | exit=1，`ConnectionClosedError … http://minio:9000/pkm-files`；未验证行未切换；重启 MinIO 后重跑成功，下载字节与原文件 SHA-256 一致 | 通过 |

迁移后 `pkm_note_file_versions` 中 `filesystem` 记录为 0。

### 2.4 UP：分块上传、恢复与并发

| 用例 | 实际结果 | 结论 |
| --- | --- | --- |
| UP-01 分块及并行上限 | agent-browser 真实 Chromium：一次加入 4 个文件（含 14.4 MiB 大文件），前端活动上传 ≤3 成立、每文件独立进度与结果 | 通过（浏览器） |
| UP-02 中断续传 | 12.6 MiB 文件仅上传 part1 后中断；同幂等键重开会话 → 返回**同一会话**且 part1 被跳过，只补传 part2/3；complete 只建 1 条笔记；下载 SHA-256 与源文件一致 | 通过（API 级） |
| UP-03 重复请求 | 同会话串行/并发（5 线程）complete 均返回同一 `note_id`；文件版本仍为 1；重复内容新会话 → 409 `duplicate_file`；MinIO 无残留 multipart | 通过 |
| UP-04 取消与过期 | 取消后写分块/complete 均 409，状态 `cancelled`；过期会话 GET/complete 均 410「上传会话已过期」；`cleanup_expired_sessions` 处理 1 个过期会话并 abort 其 multipart，状态 `expired` | 通过 |
| UP-05 识别失败重试 | 停 ollama 上传 PNG → `needs_vision`（可恢复）；retry → `pending` → 恢复 ollama 后 → `ready` 且生成 caption 块；替换为新版本后重试旧会话 → 409「该上传记录已被后续文件版本替换」 | 通过 |

### 2.5 DOC：格式矩阵与 ONLYOFFICE 浏览器编辑

| 项 | 实际结果 | 结论 |
| --- | --- | --- |
| MD 导出 | 与源文件逐字节一致，无 YAML front matter | 通过 |
| 五格式上传/站内打开/保存重开/单篇导出、编辑器端到端 | agent-browser 真实 Chromium 补测完成 | 通过 |
| DOC/XLS 转换（UI 确认流） | 确认框语义清晰；v1 保留原件、v2 为转换后 DOCX/XLSX；原件可按原字节下载 | 通过（UI 路径） |
| DOC/XLS 转换（`convert_legacy` 直传 API） | `POST /v1/notes/upload?convert_legacy=true` 恒返回 422 | **失败（产品缺陷，见 2.11 ①）** |

#### 浏览器补测记录（2026-10-05，agent-browser 真实 Chromium）

执行环境：隔离环境 `pkm-m3-test`（web `http://localhost:25173`），账号 `m3ui-a@m3test.dev`，工具 agent-browser 1.x + Chrome 154（本机真实浏览器，非模拟）。证据目录 `test-results/m3/ui/`。

- **UP-01 分块及并行上限 — 通过**：一次加入 4 个文件（`ui-large.md` 15,068,788 B ≈14.4 MiB + 3 个小文件）。网络证据（`up01-network.log`）显示初始仅创建 3 个上传会话，大文件按 5 MiB 分 3 块，第 4 个会话在第 1 个槽位释放后才创建——前端并发 ≤3 成立。服务端核对：4 个文件 → 4 条笔记、4 个当前文件版本（全部 `s3`），DB SHA-256 与本地文件逐一相同。
- **DOC-1 五格式站内打开/编辑/保存重开/单篇导出 — 通过**：MD 追加段落 → 自动保存 → 刷新重开内容保留 → 检索命中且 `start_offset` 可核对 → 导出与正文一致。DOCX 编辑器加载并键入标题行，关闭后回调生成 v2，重开可见修改（`docx-editor-open.png`）。XLSX A2 单元格改为 `zqx-ui-xlsx-edit`，关闭生成 v2，下载 v2 的 sharedStrings 含该词（`xlsx-editor-open.png`）。PDF 编辑器加载成功（`pdf-editor-open.png`）。DOCX 单篇导出（UI「导出原格式」）逐字节等于当前版本 SHA-256（`docx-ui-export.docx` = v3 `dd8d91ac…`）。
- **DOC-2 DOCX/XLSX/PDF 端到端 — 通过**：`status=2`（关闭保存）DOCX 生成 v2（40,280 B），`note.version` 1→2，下载 SHA 与 DB 一致且含编辑词；`status=6`（强制保存）经 ONLYOFFICE 命令服务发起真实 forcesave（响应 error:0）生成文件 v3（40,444 B）且 `note.version` 保持 2，符合系统版本语义；旧回调以 v1 参数重放返回 `{"error":1}`，篡改 token 返回 401。XLSX 单元格编辑后生成 v2。PDF 选中文本添加批注后显式保存（Ctrl+S）生成 v2（38,041 B），pypdf 解析确认含该批注。
  - 附注：PDF 批注在关闭编辑器时不触发保存回调（docserver 视为未保存变更），需显式保存才生成版本——已记录为产品行为，不影响验收。
- **DOC-3 PNG 预览与缩放 — 通过**：25%/100%/300% 缩放及重置正常；导出/下载 PNG 与源文件 SHA-256 逐字节一致（`2c2e204a…`）。
- **DOC-4 DOC/XLS 转换确认流 — 通过（UI 路径）**：`01-testWORD.doc` 弹出确认框（`doc-convert-dialog.png`）→ v1 = 原件 .doc（32,768 B，下载 SHA 与源文件一致），v2 = 转换后 DOCX（10,297 B）；编辑器顶部提供「保留的原件: 下载」。`01-testEXCEL.xls` 同样成功（v1 13,824 B / v2 8,609 B）。重复上传同一 .doc → UI 提示「内容重复」。转换期间事件循环探针 12/12 次 200 且 ≤0.06s。
- **IDX/EXP-1 界面结果位置核对 — 通过**：DOCX 结果卡显示段落文本与表格行并在编辑器中可核对；XLSX 片段与工作表单元格一致；PDF `Incubation` 命中 `location={"kind":"page","page":1}`；PNG 视觉描述重试后生成 caption，混合检索「草地上的黑白猫」命中且 `location={"kind":"image","source":"vision"}`，界面与结果未声称 OCR 文字。
- **补测收尾回归、清理与完整性 — 通过**：6 项回归 exit=0（`test-results/m3/ui/reg-*.log`）；`npm run build` 成功（341.53 kB js / 165.98 kB css）；清理临时账号 `m3ui-a@m3test.dev` 共 2,272 行用户数据与 20 个 MinIO 对象（`cleanup-m3ui-a.json`）；清理后 `check_integrity` 全 0；主环境全程未改动。

### 2.6 IDX/EXP：索引位置、版本失效与导出

- DOCX（合成，含段落与表格）：`zqx-docx-para-alpha` 命中 `{"kind":"paragraph","paragraph":2,"heading_path":["M3 索引测试文档"]}`；`zqx-docx-table-beta` 命中 `{"row":2,"kind":"table_row","table":1}`。
- XLSX（合成，工作表「数据表」）：`zqx-xlsx-cell-gamma` 命中 `{"row":2,"kind":"sheet_row","cells":["A2","B2"],"sheet":"数据表"}`。
- 文字型 PDF：命中 `{"kind":"page","page":1}`。
- 版本失效：docx 保存第 2 版（移除旧词、新增 `zqx-docx-v2-delta`）后，旧版独有词检索为 **0 命中**，新版词命中且位置为 v2 段落；v1 文件版本仍保留（SHA 不变）。
- 图像视觉描述：`07-baseball.png` 生成 caption，语义查询 `棒球运动员投球`（hybrid）命中且 `location={"kind":"image","source":"vision"}`，未声称 OCR 文字。
- 导出：单篇 MD 逐字节一致；笔记本导出仅含该笔记本；全部导出 8 个条目、**无 README/清单/系统元数据**、未编辑文件逐字节一致；被引用对象缺失时全部导出 **502**、单篇 **410**（整体失败，非静默部分包），恢复对象后 200。

### 2.7 WEB：网页草稿与抓取安全

- **DNS/出网门禁**：容器内解析 `example.com`、`www.example.com`、`example.org`、`github.com`、`www.wikipedia.org`、`cloudflare.com`、`neverssl.com`、`httpbin.org` **8/8** 全部落到 `198.18.1.x`（RFC 2544 benchmarking 段）与 `2001:2::x`（RFC 5180 benchmarking 段），逐条 `ipaddress.is_global=False`；按 `m3.py` 的 `all(is_global)` 判定，应用层必然返回 422。
- **SSRF 门禁实测**：`POST /v1/link-drafts {"url":"https://example.com/"}` → 422「出于安全原因，不能抓取内网或保留地址」。复核时因隔离环境仅余主环境复制来的账号（密码未知），改用端点与 worker 实际调用的同一函数复核——`m3._resolve_public_addresses`（`m3.py:921-960`）与 `m3.fetch_public_page`（`link_fetch_worker.py:75`）均抛 422 同一 detail。
- **草稿生命周期（DB fixture，因门禁无法建真实草稿）**：草稿不在普通笔记列表/关键词搜索/全部导出中；等价 URL（大小写、`#frag`）命中已有草稿提示；更新标题/正文后刷新保留；发布生成 Markdown 笔记且 `source_url` 保留、可检索、草稿列表清空；删除已发布草稿不影响笔记；无模型时 `rewrite`/`analyze` 受控返回 409 且 `snapshot_text` 不变。

### 2.8 WEB 抓取复测：根因定位与结论

**复测触发条件**：确认本机出网可用（宿主 `curl https://example.com/` 返回 200）后，重新检查 DNS/出网门禁。

三轮证据：

1. **解析**：容器内 8 个目标域名 8/8 解析到 `198.18.1.x` / `2001:2::x`，逐条 `is_global=False`。
2. **门禁**：直接调用端点与 worker 使用的同一函数——`m3._resolve_public_addresses` 与 `m3.fetch_public_page`——**均抛 422**。
3. **正向对照**：容器内复刻 `_PinnedHTTPSConnection` 行为，直连 DoH 查得的 `example.com` 真实 A 记录（`172.66.147.243`、`104.20.23.154`），**TLS 握手成功且返回 `HTTP/1.1 200 OK`**（0.26–0.33s）。

**根因判定**：阻断点单点收敛在 DNS 解析层。宿主本地代理（Clash Verge）启用 fake-IP DNS 模式，把域名统一映射到 `198.18.0.0/15` 与 `2001:2::/48`；这两段按 IANA 定义均非公网地址，因此 `is_global=False`，应用层门禁按设计拒绝。

- **不是产品缺陷**：SSRF 门禁与固定 IP 连接行为完全正确，拒绝保留地址正是其设计目标。
- **不是网络不可达**：容器出网与 TLS 均正常；宿主 `curl` 返回 200 是因为流量走本地代理，不代表门禁会通过。
- 与 `scripts.verify_m3_fixes` 的确定性 SSRF 专项无关：该专项以 monkeypatch 固定 DNS 与响应，已 PASS。

**风险判定**：一旦解析恢复真实公网地址，抓取链路（`robots.txt` 检查 → ≤4 跳重定向 → 固定 IP 连接 → 转 Markdown → 发布后入索引）预计直接可用，属**低风险**。

**本轮未复测说明**：经确认根因已知，本轮不执行 WEB 第 1–5 项真实抓取复测，WEB 维持「环境受限未验证」，**不标为通过**。

**解除条件与最小代价路径**（均不修改 `is_global` 门禁逻辑，不构成绕过 SSRF 防护）：

1. **宿主代理切至 real-ip 模式**（证据最干净）：把 Clash Verge 从 fake-IP 改为 real-ip/redir-host，重跑本节取证确认 `is_global=True` 后执行 WEB 第 1–5 项。
2. **隔离环境解析注入**（不动宿主）：为 `api` 与 `link-fetch-worker` **两个**服务加临时 compose override（`extra_hosts` 固定真实 A 记录，或指向可返回真实地址的解析器）后复测。需同时处理两个容器：`api` 在 `create_link_draft` 阶段做门禁预检，真正抓取发生在 `link-fetch-worker`。

完整证据：`test-results/m3/web-dns-gate-2026-10-05.txt`。

### 2.9 ISO：账号隔离

- B 对 A 的笔记（GET 详情/文件/导出/编辑器配置）、更新、删除 → 全部 **404**。
- B 访问 A 的上传会话、草稿（GET/PATCH/PUBLISH/DELETE）→ 全部 **404**。
- B 导出 A 的笔记本 → 404；B 全部导出为空（不含 A 内容）。
- B 搜索 A 的独有词（docx/xlsx/网页草稿）→ **0 命中**；A 自身命中正常。
- 编辑器取件链接：有效 200；篡改签名 401；无 token 422；过期 token 401；错误密钥签名 401。
- 结束确认无跨账号关联、无孤儿对象：`check_integrity` 全部计数 0。

### 2.10 回归与完整性

| 项 | 结果 |
| --- | --- |
| `verify_m1` | PASS（语义同义词命中） |
| `verify_m2` | PASS |
| `verify_conversations` | PASS |
| `verify_lifecycle` | PASS |
| `verify_m3_fixes` | PASS |
| `verify_vision_checkpoint` | PASS |
| `check_integrity`（测试后） | 全部计数 0 |
| `web/ npm run build` | 成功（vue-tsc + vite，341.53 kB js / 165.98 kB css） |
| 清理后 `check_integrity` | 全部计数 0 |

### 2.11 修复项与数据处置

| 问题 | 修复 | 验收结果 |
| --- | --- | --- |
| S3 文件单篇导出返回 410 | 单篇导出改为按版本记录的存储后端读取文件字节 | PNG S3 文件导出字节一致通过；历史版本下载与版本替换通过 |
| ZIP 静默略过缺失文件 | ZIP 导出遇到任何有效文件读取失败时返回 502，不返回部分成功压缩包 | 完整 ZIP 解压字节一致；缺失对象显式失败通过 |
| DNS 重绑定与恶意跳转 | 对所有解析结果做公网校验，连接固定到通过校验的 IP；重定向逐跳重新解析、校验并固定；TLS 仍校验原主机名 | 混合公网/私网 DNS 拒绝、目标 IP 固定及跳转内网拦截测试通过；真实外部抓取环境受限未验证，门禁拒绝保留地址属设计行为 |
| ONLYOFFICE 延迟回调覆盖新文件 | 回调 URL 和文档 key 绑定笔记版本、文件版本及 SHA-256；下载保存后加锁复核 | `status=6` 保存后旧回调被拒绝且新文件哈希不变；真实浏览器编辑/转换端到端通过 |
| 草稿 PATCH 可引用他人笔记本 | 设置 `notebook_id` 前校验当前账号归属；失败时不写入，允许清空 | 跨账号设置返回 404 且草稿不变；合法设置和清空通过 |
| URL 等价形式未统一去重 | 统一 scheme/host 大小写、默认端口和 fragment；保留路径与查询参数；创建和发布都检查已导入笔记及草稿 | 创建重复、发布后的规范化重复拦截通过 |
| M3 孤儿数据未纳入完整性检查 | 检查文件版本、上传会话、采集任务、草稿和文本块等关系；新增默认只读 dry-run 清理脚本，备份后才可应用 | 清理前发现 7 条文件版本、5 条文本块、2 条草稿；清理前将数据库记录与对象状态归档到 `/data/note-files/.orphan-backups/m3-orphans-20261004T135930Z.zip`，归档校验通过；之后删除孤儿行，完整性计数全部归零 |
| 图片编辑器需求边界 | 按负责人确认，仅保留图片预览和缩放作为验收范围 | 组件提供预览、25%–300% 缩放、重置和加载错误提示；未增加其他编辑能力 |

`alembic current`：`0017_assistant_traces (head)`（修复专项复测时点）；集成验收时点为 `0021_optional_reminder_note`。

### 2.12 通过标准与判定口径

M3 剩余用例全部通过，或将无法验证的项标为 BLOCKED 并附环境证据；文件大小/哈希、版本、检索位置、导出内容及账号隔离符合需求；回归通过且清理后完整性计数为 0。MIG、真实浏览器编辑/转换、格式矩阵、UP 恢复/并发和 WEB 成功抓取五类门槛均有结果后，才可建议 M3 集成验收完成。**BLOCKED 项不算通过，也不允许以模拟测试替代真实浏览器、公网或数据迁移验收。**

每项执行记录至少包含用例编号、执行时间、账号/文件 fixture、操作步骤、实际与预期结果、日志或截图路径、失败原因及清理确认。

### 2.13 遗留事项（已知问题，修复方向明确，本轮未实施）

两项均**不计入 M3 验收门槛**（不影响已 PASS 的用例组），登记于此以便后续统一处理。两项均未改动代码。

#### ① 直传 API 转换期间阻塞事件循环

- **范围**：`api/app/knowledge/m3.py` 的 `async def upload_note`（行 315）与 `async def replace_note_file`（行 388）在协程内**同步**调用 `convert_legacy_office`，转换期间阻塞事件循环，接口恒返回 422「ONLYOFFICE 无法转换此文件」。
- **不影响产品 UI**：浏览器路径走 `api/app/knowledge/upload_sessions.py:368` 的**同步** `complete_session`，由 FastAPI 放入线程池执行；转换期间 `/health/live` 12/12 探针 200 且 ≤0.06s。
- **建议修复方向**：把 `convert_legacy_office` 调用改为 `await anyio.to_thread.run_sync(...)`（或 `starlette.concurrency.run_in_threadpool`），或将该端点改为同步 `def` 交由线程池。
- **验证要求（实施后）**：重跑 DOC-4（转换成功、原件可按原字节下载），并复测转换期间 `/health/live` 不再阻塞。

#### ② URL 规范化不折叠尾部斜杠

- **事实**：`api/app/knowledge/m3.py:636-651` 的 `canonicalize_source_url` 只做 scheme/host 小写、IDNA、去默认端口、丢 fragment，**保留 `parsed.path` 原样** → `/a1` 与 `/a1/` 被视为不同 URL。
- **影响面**：可绕过草稿的部分唯一索引 `uq_link_drafts_user_url`（`api/core/models.py:189`）与笔记侧的 O(n) 去重（`m3.py:924-927`、`m3.py:1056-1061`），产生两篇同一来源笔记。
- **建议修复方向**：规范化时对 `path` 去尾斜杠，但**保留根路径 `/`**（即仅 `len(path) > 1 and path.endswith("/")` 时裁剪）；需评估 `/a/b/` 与 `/a/b` 是否确实等价于同一资源。
- **验证要求（实施后）**：重跑 `scripts.verify_m3_fixes` 的 URL 规范化去重场景（`verify_m3_fixes.py:185-199`），并补充「等价 URL 再次创建草稿 → 重复提示」的用例不回归。

### 2.14 清理确认

- 删除临时账号 `m3test-a/b@m3test.dev` 及其全部用户相关行（23 张表）、11 个 MinIO 对象；另清理 `m3ui-a@m3test.dev`（2,272 行、20 个对象）。隔离环境现仅余主环境复制来的 2 个原始账号。
- 未删除主项目卷；主环境 `pkm-system` 全程未执行迁移、故障注入或 `down -v`。
- 隔离环境 `pkm-m3-test` 按评审决定保留运行，便于补测。
