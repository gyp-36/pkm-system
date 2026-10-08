# 设计决策记录

本文汇总**已实现页面**的设计决策，合并自 `login-redesign-v1.md`、`weekly-report-redesign-v1.md`、`workbench-redesign-v3.md`、`workbench-welcome-v5.md`（合并日期 2026-10-05）。

配色与字体基线统一见 [枫叶纸感视觉规范](maple-style.md)，本文不重复令牌定义，只登记各页面在此基础上新增或调整的部分。各版本设计稿的迭代过程与一次性生成提示词未保留，最终交付资产见各节「交付文件」。

---

## 1. 登录页

**实现文件**：`web/src/LoginView.vue`（对应设计稿 `login-redesign-v1.html`）

**交付文件**

- `login-redesign-v1.html`：可预览登录、注册及密码显隐的响应式设计稿（表单未连接后端）。
- `login-implemented-desktop.png` / `login-implemented-mobile.png`：实现后浏览器截图。

**设计要点**

- 沿用暖白底色 `#FCFAF7`、深褐文字 `#3C322E`、枫叶棕主色 `#965540`。
- 右侧保留简短便笺标签，照片沿用项目现有素材。
- 手机端优先展示表单。

**线上参考**

- [Linear 界面设计](https://linear.app/now/how-we-redesigned-the-linear-ui)
- [Day One 网页版](https://dayoneapp.com/web/)
- [EasyNotes 登录页案例](https://webdesignledger.com/20-creative-login-form-examples-for-your-inspiration/?amp=1)

---

## 2. 周报页

**实现文件**：`web/src/WeeklyReportsPage.vue`（对应设计稿 `weekly-report-redesign-v1.html`）

**设计目标**

- 延续暖白纸感、枫叶棕强调色、宋体标题与克制边框。
- 页面标题和计划卡片只保留必要标签；日报、周报计划并列展示，减少说明文字和卡片留白。
- 内容增长时保持结构稳定：卡片使用等宽网格，文本区 `min-width: 0` 并允许自然换行，控件有独立网格列，历史状态和操作始终在固定列。
- 小屏时两张计划卡片改为纵向排列；历史项转为内容在上、状态与操作在下，不产生横向滚动。
- 生成记录支持「全部 / 日报 / 周报」筛选与上一页、下一页分页；**切换类型回到第一页**，并根据筛选结果更新总页数。

**主要区域**

1. **页面标题**：周报标题和北京时间标识。
2. **生成计划**：日报与周报两张紧凑卡片；底部展示下次生成时间和保存操作。
3. **生成记录**：全部 / 日报 / 周报筛选，列表分页。记录行显示类型、生成时间、状态和操作；失败说明较长时在信息列换行，不挤动状态和操作。

**本页新增视觉令牌**

| 用途 | 值 |
| --- | --- |
| 页面底色 | `#FCFAF7` |
| 卡片表面 | `#FFFEFD` |
| 主文字 | `#382E29` |
| 次级文字 | `#74665E` |
| 强调色 | `#965540` |
| 分割线 | `#E9DFD7` |
| 卡片圆角 | `18px` |
| 页面最大宽度 | `1120px` |

设计稿为独立 HTML 原型，含计划开关、保存提示、分类筛选、分页和刷新状态的演示交互；接入实际业务时类型与分页状态映射到列表查询参数。

---

## 3. 工作台（V3 内容归属）

**实现文件**：`web/src/WorkbenchHome.vue`（对应设计稿 `workbench-redesign-v3.png`）

**已确认的设计要求**

- 延续简约的枫叶棕、暖白纸感、窄图标导航与留白。
- 继续写作保持顶部主焦点。
- 笔记本、AI 对话为轻量入口。
- 日程提醒卡片展示最多 **3** 条待提醒内容。
- 周报卡片只展示最近 **1** 条消息。
- 增加归档卡片，展示最多 **3** 条即将自动清除的内容；保留左侧归档导航。
- **移除独立「待处理」区域**，所有预览归入各自对应的模块卡片。

**内容和交互约定**

- 卡片标题/箭头进入对应模块，具体条目打开对应内容。
- 提醒优先展示已逾期或最近到期的未完成事项；归档按自动清除时间由近到远展示。
- 归档沿用「删除后保留 30 天」的业务含义，文案明确说明「自动清除」。
- 不足上限时只展示实际条目；无内容时提供简短空状态。

**实现核对**（实现阶段的浏览器与容器验证，已并入本文）

- 3/1/3 上限、未来未完成事项纳入提醒、隐藏来源已归档的关联提醒。
- 周报显示最新一条任务，独立于提醒；支持已生成、失败、待生成、生成中和原笔记归档/清除状态。
- 归档按全账号清除时间由近到远查询，不受笔记本筛选或排序影响。
- 继续写作独立读取最近更新的活跃笔记。
- 响应式：375×812 与 812×375 下文档宽度等于视口宽度，无横向溢出。
- 实现截图：`workbench-implemented-v3.png`、`workbench-implemented-v5-compact.jpg`。

---

## 4. 首页欢迎版（v4 → v5 交互）

**实现文件**：`web/src/WorkbenchHome.vue`（当前首页；对应原型 `workbench-welcome-v5.html`）

**设计目标**：打开系统时，先感受到个人空间的温度和系统已经带来的便利，再自然进入待办与记录。保留米白、枫棕、宋体标题、细线框和窄导航栏。

**信息顺序**

1. **欢迎与日期**：降低「工作台」标题的权重，以当天日期、短问候和小幅秋日静物插画建立轻松的入口。
2. **回顾卡片（v4 的周报优先 → v5 改为日报/周报共享）**：展示周期、简短内容摘要和可回看的主题。
3. **今日小安排**：与回顾卡片并列但宽度较小，显示两项待办和时间，不用大数字、催促文案和密集警示色。
4. **接着上次的灵感**：最近记录与笔记本、AI 对话放在较轻的下方区域。

**v5 的切换行为**

- 右上角为两段选择按钮，点击切换，**不自动轮播**（遵守减少动态效果偏好）。
- 首次默认选择日报；记住上次选择，刷新后恢复；浏览器不允许存储时仍可正常切换。
- 标题、日期范围、摘要、主题标签、生成时间和阅读按钮同步变化。
- 日报标题按实际报告覆盖日期显示，不强制叫「今日」。
- 阅读按钮打开当前选择类型的回顾；关闭后焦点回到阅读按钮。支持 Escape 关闭和键盘 Enter 切换。
- 移动端使用纵向布局，周报与日报仍在同一卡片内切换。

**真实数据接入约定**（v5 原型阶段提出的需求，现已落地）

- `/v1/workbench` 需同时返回独立的 `latest_daily` 与 `latest_weekly`，按用户和报告类型分别查询，避免日报与周报相互挤掉。
- 选择状态只决定展示哪个字段，**不能把同一条报告改个标题当成另一种报告**。
- 无对应类型报告时展示独立空状态；生成中、失败、已归档等状态使用真实状态文案。
- 阅读入口对应选中报告的笔记；尚未生成时引导到生成记录或计划，而不是展示旧类型的内容。

**桌面空间压缩**（实现阶段的调整）：使用视窗高度分配空间，缩小问候区、卡片边距和底部入口；长标题、主题、待办省略显示，完整内容仍通过阅读/日程入口访问。小屏幕自然排列、纵向滚动。

**已检查场景**：1280×720（空状态与长内容）、1024×600（含归档清除提醒）、1366×768、375×812（长文本，无横向溢出）；日报/周报阅读目标分别指向对应报告笔记。

---

## 5. 插画资产：秋日静物

`web/src/assets/workbench-autumn.jpg`（约 102 KB）由 ImageGen 依据已批准设计稿单独绘制。装饰图使用空替代文本，边缘柔化，不包含界面文字。

生成提示词：

> Use case: precise-object-edit. Reference image is a Chinese app homepage. Extract and redraw ONLY the small autumn still-life illustration in its upper-right greeting region as a standalone web illustration asset. No UI, no card, no letters, no Chinese text. Subject: an open cream notebook on a wooden desk, a warm terracotta ceramic teacup, and a sparse golden maple twig in a small clear glass vase next to a bright window. Exactly the same tasteful watercolor and colored-pencil editorial style as reference, warm natural soft window light, refined paper textures, not childish, not clay or photorealistic. Wide landscape 3:2 framing, objects grouped at center-right with gentle white breathing room around. Background must blend seamlessly into a uniform warm ivory #FCFAF7 and fade to that exact solid color at all four image edges. Flat illustration, no frames, no watermark. This is a small homepage atmospheric image; keep it light and visually quiet.

---

## 6. 交付素材索引

| 类别 | 文件 |
| --- | --- |
| 视觉规范 | `maple-style.md` |
| 可点击原型 | `login-redesign-v1.html`、`weekly-report-redesign-v1.html`、`workbench-welcome-v5.html` |
| 最终实现截图 | `login-implemented-desktop.png`、`login-implemented-mobile.png`、`workbench-implemented-v5-compact.jpg`、`schedule-fixed-layout.png`、`schedule-upcoming-2x3.png` |
| 设计稿源图 | `home-notes-*.png/svg`、`maple-*.png/svg`、`style-palette-comparison.png/svg`、`schedule-implementation.png` |
| 生成脚本 | `build_maple_mockups.py`、`build_maple_views.py`、`build_style_palettes.py` |
