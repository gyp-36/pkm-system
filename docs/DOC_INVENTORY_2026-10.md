# 文档清点与处置清单

清点日期：2026-10-05。范围：`pkm-system` 仓库内全部说明类文档（不含代码内的提示词模板）。

**执行状态：已于 2026-10-05 执行完毕。** 执行前把 `docs/`、`design/` 与 `test-results/` 的大文件完整备份到 `.local-backups/doc-cleanup-2026-10-05/`（148 MB / 88 个文件，该目录被 `.gitignore` 忽略）。实际执行结果见第 8 节。

**后续入口调整：** 仓库根目录 `README.md` 现用于介绍项目与系统架构；原 `docs/README.md` 中的阶段进度、本地启动和验收说明已移至 `docs/DEVELOPMENT_AND_ACCEPTANCE.md`。下文历史记录中的 README 索引说明按此新路径理解。

## 0. 结论速览

| 目录 | 说明类文件 | 保留不动 | 压缩合并 | 建议清除 | 备注 |
| --- | ---: | ---: | ---: | ---: | --- |
| `docs/` | 26 | 12 | 7 | 7 | 唯一有索引（README「文档」节）的目录 |
| `design/` | 10 | 1 | 4 | 5 | 另有 36 张 PNG/SVG/JPG 素材 |
| `test-results/` | 产物类 | 1 类 | 1 类 | 1 类 | 134 MB，含 2 个 53 MB 数据库 dump |
| `test-materials/`、`evaluation/` | 素材与结果 | 全部 | — | — | 评测脚本的输入与输出，不得清除 |
| 仓库根与 `deploy/` | 6 | 全部 | — | — | AGENTS.md、`.env*.example`、部署脚本 |
| 母目录（仓库外） | 4 | 全部 | — | — | PRD / 开题报告 / 任务书 / 文献调研 |

三档含义：**保留不动** = 核心稳定内容，长期维护；**压缩合并** = 内容有效但与其他文档重复或已迭代收敛，合并成一份后删除零散件；**建议清除** = 一次性过程产物或已被取代，结论已进入核心文档，可安全移除。

---

## 1. 处置前必读

1. **这些目录不在 git 里。** `docs/`、`design/`、`test-results/`、`test-materials/`、`evaluation/` 在 `git status` 中全部显示为未跟踪（`??`）。**删除后无法用 git 恢复**。执行清除前必须先做一件事：`git add docs design` 提交一次，或把 `docs/ design/ test-results/` 复制到仓库外备份（`test-results` 建议只备份 `web-dns-gate-2026-10-05.txt`）。
2. **README.md 的「文档」节是唯一索引**，其中引用了 7 份将被清除或合并的文件。任何删除动作都必须同步改这一节，否则索引会指向不存在的文件。
3. **唯一未闭环项的证据必须留**：`test-results/m3/web-dns-gate-2026-10-05.txt`（公网抓取 DNS 门禁取证）。M3 验收记录、`M3_DESIGN.md`、`REQUIREMENTS_AUDIT` 三处都指向它，删掉会导致「环境受限未验证」结论失去凭证。
4. 建议执行顺序见第 6 节。**先合并、再删原件**，避免结论丢失。

---

## 2. `docs/`（26 份）

### 2.1 保留不动（12 份）

| 文件 | 定位 | 保持理由 |
| --- | --- | --- |
| `DEVELOPMENT_AND_ACCEPTANCE.md` | 阶段进度、开发与验收、本地启动 | 原 `docs/README.md` 的内容移至此处；仓库根 `README.md` 负责项目总览与架构 |
| `ARCHITECTURE.md` | 系统架构、服务与数据、账号约束 | 长期有效，M4 写论文直接引用 |
| `DB_DESIGN.md` | 数据库设计约束与事务边界 | 设计级文档，与字段字典互补不重复 |
| `DATABASE_DICTIONARY.md` | 25 张表完整字段字典 | 事实源，改动数据结构时必须同步 |
| `API_DESIGN.md` | `/v1` 接口设计与 CRUD 路由总览 | 事实源，与路由装饰器对齐 |
| `FEATURE_INVENTORY_2026-10.md` | 功能↔阶段对照总入口 | 当前文档总索引（含 11 项扩展功能登记） |
| `VERSIONS.md` | 技术栈版本兼容记录 | 部署与论文环境章节的依据 |
| `DEPLOYMENT_CLOUD.md` | 云端演示部署（M4） | 唯一剩余阶段的执行依据，尚未使用 |
| `M2_DESIGN.md` | M2 接口与数据设计 | 阶段设计，验收后仍为论文素材 |
| `M3_DESIGN.md` | M3 设计：多格式笔记与网页草稿 | 同上；执行部分待并入验收汇总后精简 |
| `M1_VERIFICATION.md` | M1 验收记录（已签核） | **签核件**，不可合并、不可删 |
| `M2_VERIFICATION.md` | M2 验证记录（已确认验收） | **签核件**，不可合并、不可删 |

### 2.2 压缩合并（7 份 → 合并后 1 份 + 1 个归档目录）

**合并组 A — 阶段验收与测试证据**（4 份 → `docs/ACCEPTANCE_M0_M3.md`）

| 文件 | 重叠内容 |
| --- | --- |
| `M0_VERIFICATION.md` | M0 本地验证表（环境、端口、向量探针、资源占用） |
| `M3_FUNCTIONAL_AUDIT.md` | M3 修复项与验收结论 |
| `M3_REMAINING_TEST_PLAN.md` | M3 测试场景与通过标准 |
| `M3_TEST_EXECUTION_RECORD.md` | M3 逐用例执行结果与环境基线 |

四份都在重复描述同一套环境（隔离项目 `pkm-m3-test`、端口 25173/28080/29000、迁移版本、`check_integrity` 全 0）与同一句结论（唯余公网抓取未验证）。合并为「环境基线 → 用例组结果 → 未闭环项与取证」三段式，预计从约 48 KB 压到 12 KB 内。

> M1、M2 两份签核记录**不并入**，仅在新文件中以链接引用。

**合并组 B — 需求实现核对**（1 份 → 并入 `FEATURE_INVENTORY_2026-10.md`）

| 文件 | 处置 |
| --- | --- |
| `REQUIREMENTS_AUDIT_2026-10.md` | 与总清单的「阶段对照」表结论完全一致，仅多两处文档冲突修正说明。把这两段并入总清单对应阶段行，随后删除本文件 |

**合并组 C — 审计改造方案**（1 份 → 结论并入后归档）

| 文件 | 处置 |
| --- | --- |
| `AUDIT_LOG_REDESIGN.md` | 30 KB 的改造前盘点 + 方案。P0 已完成，结论已写进 `ARCHITECTURE.md`（两层日志分工）和 `DB_DESIGN.md`（`0022_audit_observability` 段）。**把「两层结构与保留策略」压成一段并入上述两份核心文档，原文移入 `docs/archive/`**（不直接删，留作论文「改造前后对比」素材） |

**移出 `docs/` — 调研素材**（1 份）

| 文件 | 处置 |
| --- | --- |
| `竞品调研记录-笔记核心系统的周报日程与提醒.md` | 不属工程文档，是论文相关工作的调研材料。建议移到 `evaluation/research/`，与母目录的《文献调研记录》归为一类 |

### 2.3 建议清除（7 份）

| 文件 | 类型 | 清除理由 |
| --- | --- | --- |
| `SCHEMA_EXTENSION_VERIFICATION.md` | 一次性验证（2026-10-01，针对 `0003`） | 结论已在 `DATABASE_DICTIONARY.md` 与 `M1_VERIFICATION.md` |
| `SCHEMA_0004_VERIFICATION.md` | 一次性验证（2026-10-02，针对 `0004`） | 同上；其中的评测成绩已存于 `evaluation/schema-0004.json` |
| `SCHEMA_EVOLUTION_PLAN.md` | 早期方案 | 文件开头自述「不作为当前完整迁移清单」，迁移已推进到 `0022`，方案已失效 |
| `M2_TASK_CHECKLIST.md` | 已完成的任务清单 | 任务全部完成，结论已在 `M2_VERIFICATION.md` 与总清单 |
| `WORKBENCH_REDESIGN_VERIFICATION.md` | 一次性实现验证 | 页面已上线，验证条目与 `design/` 设计稿重复 |
| `WORKBENCH_WELCOME_VERIFICATION.md` | 一次性实现验证 | 同上；其中的插画生成提示词如需保留可先抄进 `design/DESIGN_DECISIONS.md` |
| `chunk-preview.html` | 一次性预览页（切片调试用） | 调试产物，`web/public/chunk-preview.html` 已是副本 |

---

## 3. `design/`（10 份说明 + 36 项素材）

### 3.1 保留不动（1 份）

`maple-style.md` — 枫叶纸感视觉规范，是全站配色与字体的基线，后续任何页面都要遵循。

### 3.2 压缩合并（4 份 → `design/DESIGN_DECISIONS.md`）

| 文件 | 合并后保留内容 |
| --- | --- |
| `login-redesign-v1.md` | 登录页设计要点、色值沿用关系、线上参考 |
| `weekly-report-redesign-v1.md` | 周报页布局、视觉令牌、分页交互约定 |
| `workbench-redesign-v3.md` | 工作台最终结构（继续写作 + 三卡片 + 归档） |
| `workbench-welcome-v5.md` | 首页欢迎版交互（日报/周报切换、键盘可达性） |

四份高度同源（都引用 `maple-style.md`），且都描述「已实现」的页面。合并成一份「设计决策记录」，按页面分节，每节保留：设计目标 → 关键交互 → 视觉令牌 → 对应实现文件。

### 3.3 建议清除（5 份）

| 文件 | 理由 |
| --- | --- |
| `workbench-redesign-v1.md` | 迭代稿，用户已反馈「版面太紧凑」，被 V2/V3 取代 |
| `workbench-redesign-v2.md` | 迭代稿，被 V3 取代 |
| `workbench-welcome-v4.md` | 被 v5 取代（v5 把单周报卡改为日报/周报共享卡） |
| `workbench-welcome-v4-prompt.txt` | 一次性文生图提示词 |
| `workbench-welcome-v5-prompt.txt` | 同上（如需留档，先抄进 `DESIGN_DECISIONS.md` 的插画小节） |

### 3.4 素材（建议区分对待，非文档）

| 类别 | 体积 | 建议 |
| --- | --- | --- |
| 迭代过程图：`schedule-redesign-v1.png`、`schedule-redesign-v2.png`、`workbench-redesign-v1/v2/v3.png`、`workbench-welcome-v4.png` | 约 6.5 MB（5 张超过 1 MB） | 可清除，最终效果已由 `*-implemented-*` 系列记录 |
| 最终实现图：`login-implemented-*`、`workbench-implemented-v5-compact.jpg`、`schedule-fixed-layout.png`、`schedule-upcoming-2x3.png` | 约 0.8 MB | 保留（论文图源） |
| 交互原型：`login-redesign-v1.html`、`weekly-report-redesign-v1.html`、`workbench-welcome-v5.html` | 约 61 KB | 保留（可点击演示，答辩可用） |
| 生成脚本：`build_maple_mockups.py`、`build_maple_views.py`、`build_style_palettes.py` | 19 KB | 保留（可复现设计图） |
| 早期 SVG 源：`home-notes-*.svg`、`maple-*.svg` | 约 120 KB | 保留（矢量源，体积可忽略） |

---

## 4. `test-results/`、`test-materials/`、`evaluation/`

| 目录 | 处置 | 说明 |
| --- | --- | --- |
| `test-materials/`（3.8 MB） | **不动** | 22 篇评测笔记 + 10 份多格式样本是验证脚本的输入素材 |
| `evaluation/`（16 KB） | **不动** | 评测结果 JSON，`M1_VERIFICATION.md` 直接引用 |
| `test-results/m3/web-dns-gate-2026-10-05.txt` | **必须保留** | 唯一未闭环项的取证 |
| `test-results/m3/*.log`、`*.txt`、`*.json`（约 25 份） | 合并 | 生成一份 `EVIDENCE_INDEX.md` 把「用例编号 → 证据文件 → 结论」列成表，原件移入 `test-results/archive/` |
| `test-results/m3/main-db-baseline.dump`（53 MB） | 清除 | 迁移基线转储，迁移验收已完成 |
| `test-results/m3/pre-mig03.dump`（53 MB） | 清除 | 故障注入前的临时快照 |
| `test-results/m3/fixtures/up-large-12m.md`（12 MB） | 清除 | 大文件上传测试的合成样本，可按需重新生成 |
| `test-results/m3/ui/ui-large.md`（12 MB） | 清除 | 同上 |
| `test-results/m3/ui/`（50+ 张截图与导出件） | 建议清除，**需你确认** | 浏览器端到端证据（ONLYOFFICE 打开/编辑/转换、PNG 缩放、导出件）。结论已写入执行记录，若论文需要过程截图请先挑出保留 |

> 仅清除上述 4 个大文件即可回收约 **130 MB**。

---

## 5. 仓库根、`deploy/` 与仓库外文档

| 文件 | 处置 | 说明 |
| --- | --- | --- |
| `AGENTS.md` | 不动 | 仓库贡献指南，与 `docs/DEVELOPMENT_AND_ACCEPTANCE.md` 有少量命令重叠，可接受 |
| `.env.example`、`.env.prod.example` | 不动 | 配置模板 |
| `deploy/Caddyfile.example`、`deploy.sh`、`deploy/pkm-compose.service` | 不动 | M4 云端部署所需 |
| `api/app/prompts/*.txt`（11 份） | 不动 | **提示词模板是代码资产**，不是文档 |
| 母目录 `基于AI Agent...-PRD.md`、`开题报告-...md`、`毕业设计任务书-...md`、`文献调研记录-...md` | 不动 | 上游需求文档，在仓库之外；开发与验收说明中保留了相关路径 |

---

## 6. 建议执行顺序

1. **保底**：`git add docs design` 并提交一次（或复制到仓库外），确保清除可回退。
2. **合并**：按 2.2 生成 `ACCEPTANCE_M0_M3.md`；把 `REQUIREMENTS_AUDIT` 结论并入总清单；把 `AUDIT_LOG_REDESIGN` 结论并入 `ARCHITECTURE.md`/`DB_DESIGN.md` 后移入 `docs/archive/`；按 3.2 生成 `DESIGN_DECISIONS.md`。
3. **删除**：按 2.3、3.3 清掉 12 份零散件，再清 `test-results` 的 4 个大文件。
4. **同步索引**：更新开发与验收说明的「文档」节与「阶段进度」表，把所有指向已删文件的链接改为新文件，或改成指向 `ARCHITECTURE.md` / `FEATURE_INVENTORY_2026-10.md` 的对应段落。
5. **回归**：确认 `docs/` 内不再有指向已删文件的链接（`M3_DESIGN.md`、`M3_FUNCTIONAL_AUDIT.md`、`REQUIREMENTS_AUDIT` 等多处交叉引用需一并改）。

## 7. 合并后的目标结构

```text
docs/
  DEVELOPMENT_AND_ACCEPTANCE.md # 阶段进度、开发、验收与本地启动
  ARCHITECTURE.md                # 架构（含两层日志结构一段）
  DB_DESIGN.md                   # 数据库设计约束
  DATABASE_DICTIONARY.md         # 字段字典
  API_DESIGN.md                  # 接口设计
  FEATURE_INVENTORY_2026-10.md   # 功能↔阶段总入口（并入需求核对结论）
  VERSIONS.md                    # 版本兼容
  DEPLOYMENT_CLOUD.md            # 云端部署（M4）
  M2_DESIGN.md / M3_DESIGN.md    # 阶段设计
  M1_VERIFICATION.md / M2_VERIFICATION.md   # 签核件
  ACCEPTANCE_M0_M3.md            # 新建：M0 与 M3 验收汇总
  DOC_INVENTORY_2026-10.md       # 本清单
  archive/AUDIT_LOG_REDESIGN.md  # 归档：审计改造全过程
design/
  maple-style.md                 # 视觉规范
  DESIGN_DECISIONS.md            # 新建：已实现页面的设计决策
  *.html / *.png / *.py          # 原型、图源、生成脚本
evaluation/
  latest.json / schema-0004.json
  research/竞品调研记录-....md     # 移入
```

---

## 8. 执行结果（2026-10-05）

### 8.1 新建

| 文件 | 来源 |
| --- | --- |
| `docs/ACCEPTANCE_M0_M3.md` | 合并 `M0_VERIFICATION.md`、`M3_FUNCTIONAL_AUDIT.md`、`M3_REMAINING_TEST_PLAN.md`、`M3_TEST_EXECUTION_RECORD.md`；按「M0 验证 → M3 环境基线 → 用例组结果 → 各用例明细 → 修复项 → 通过标准 → 遗留事项 → 清理确认」重组，去掉重复的环境描述与结论段落 |
| `docs/archive/AUDIT_LOG_REDESIGN.md` | 原 `docs/AUDIT_LOG_REDESIGN.md` 整体移入；`ARCHITECTURE.md` 与 `DB_DESIGN.md` 各补一句结论与指针 |
| `design/DESIGN_DECISIONS.md` | 合并 `login-redesign-v1.md`、`weekly-report-redesign-v1.md`、`workbench-redesign-v3.md`、`workbench-welcome-v5.md`；另保留了原 `WORKBENCH_WELCOME_VERIFICATION.md` 中的秋日插画生成提示词 |
| `test-results/m3/EVIDENCE_INDEX.md` | 为 `test-results/m3/` 全部证据建立「用例 → 文件 → 结论」索引 |

### 8.2 并入既有文档

- `FEATURE_INVENTORY_2026-10.md` 新增**第十一节「需求文档冲突修正」**，收录原 `REQUIREMENTS_AUDIT_2026-10.md` 独有的两处冲突修正（图片处理范围、助手写入授权边界）与扩展功能口径重申；原文件删除。
- `ARCHITECTURE.md`：补两层日志结构说明 + 归档指针。
- `DB_DESIGN.md`：补归档指针。
- `evaluation/research/竞品调研记录-笔记核心系统的周报日程与提醒.md`：由 `docs/` 移入。

### 8.3 已删除

`docs/`（12 份）：`M0_VERIFICATION.md`、`M3_FUNCTIONAL_AUDIT.md`、`M3_REMAINING_TEST_PLAN.md`、`M3_TEST_EXECUTION_RECORD.md`、`REQUIREMENTS_AUDIT_2026-10.md`、`M2_TASK_CHECKLIST.md`、`SCHEMA_EVOLUTION_PLAN.md`、`SCHEMA_0004_VERIFICATION.md`、`SCHEMA_EXTENSION_VERIFICATION.md`、`WORKBENCH_REDESIGN_VERIFICATION.md`、`WORKBENCH_WELCOME_VERIFICATION.md`、`chunk-preview.html`

`design/`（9 份）：`login-redesign-v1.md`、`weekly-report-redesign-v1.md`、`workbench-redesign-v3.md`、`workbench-welcome-v5.md`、`workbench-redesign-v1.md`、`workbench-redesign-v2.md`、`workbench-welcome-v4.md`、`workbench-welcome-v4-prompt.txt`、`workbench-welcome-v5-prompt.txt`

迭代过程图（5 张）：`workbench-redesign-v1.png`、`workbench-redesign-v2.png`、`workbench-welcome-v4.png`、`schedule-redesign-v1.png`、`schedule-redesign-v2.png`

`test-results/m3/`（4 个大文件 + 1 个空目录）：`main-db-baseline.dump`、`pre-mig03.dump`、`fixtures/up-large-12m.md`、`ui/ui-large.md`、`ui/83de787f-…/`

### 8.4 体积变化

| 目录 | 执行前 | 执行后 |
| --- | ---: | ---: |
| `docs/` | 328 KB / 26 份 | 236 KB / 15 项 |
| `design/` | 11 MB / 10 份说明 | 5.8 MB / 2 份说明 |
| `test-results/` | 134 MB | 2.7 MB |

### 8.5 后续核对

- 已校验 `docs/`、`design/`、`test-results/` 与 `AGENTS.md` 共 27 份 Markdown 的全部相对链接，无失效；仅两处误报（`DATABASE_DICTIONARY.md` 中作为路由书写的 `/v1/...` 被正则误判、`README.md` 指向母目录任务书的链接含 `%20` 编码）。
- 已同步更新索引与交叉引用：原 `docs/README.md`（现为 `docs/DEVELOPMENT_AND_ACCEPTANCE.md`；含「文档」节、「阶段进度」表和「本地启动」说明）、`ARCHITECTURE.md`、`API_DESIGN.md`（3 处）、`M3_DESIGN.md`（4 处）、`FEATURE_INVENTORY_2026-10.md`（3 处）、`design/DESIGN_DECISIONS.md`。
- `test-results/m3/web-dns-gate-2026-10-05.txt` 保留原始采集内容不变，仅在文首加一行注记说明其引用的两份文档已合并。
- **未执行**：`test-results/m3/ui/` 下 50 余张浏览器截图与导出件（原清单标记为「需你确认」），仍保留在仓库中；如需清除请单独确认。
- **未执行**：`git add` 提交。仓库中 `docs/`、`design/`、`test-results/` 至今仍是未跟踪状态，本次清理的可回退性依赖 `.local-backups/doc-cleanup-2026-10-05/` 这一份备份，而非 git。
