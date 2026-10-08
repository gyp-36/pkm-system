# AI 对话助手安全边界扩展测试

入口：`REPORT.md`（中文报告），`RESULTS.md`（200例逐场景判定）。原始观测不覆盖，人工纠正/规则复核放在 `reviewed-results.jsonl`。

## 文件

- `cases.json` / `cases.csv` / `CASES.md`：60普通+140特殊，独立输入、资料条件、预期和判定依据。
- `build_cases.py` + `case_contracts.py`：复建清单；不得用删/改个人笔记来准备资料。
- `runner.py`：当前运行API容器的原始Agent、授权判断和工具。真实模型使用现有唯一连接；配置只读，Key仅在内存中供模型请求使用。每场景独立进程；合成存储、检索、网页拦截替代副作用服务。不是新工作区代码测试。
- `results.jsonl`：280个基线计划位，7个页面/渲染占位需要补测；不能把占位算有效执行。
- `supplemental.jsonl`：疑似问题三次复测及正常对照，42条seed复制不重复计数。`supplement-plan.json`记录选择。
- `ownership-repairs.jsonl` / `notebook-repairs.jsonl`：探针签名/只读行锁适配纠正；初次脚本错误不算应用缺陷。
- `extra-cases.json` / `extra-results.jsonl`：误拒、代码正常对照、正常预算修改、噪声引用、过期引用复现。
- `boundary_probes.py` / `citation_probes.py` / `stream_probes.py` / `scope_controls.py`：原始工具/引用/流式/授权边界的确定性验证，原始工具授权不被替换。
- `advice_probe.py`：仅合成环境验证生成排障命令是否泄值，未读取真实环境变量。
- `trace_controls.py`：本人追踪正常对照，不导出追踪内容。
- `render_probe.mjs`：从当前前端提取实际渲染函数，在禁脚本/禁网络的DOM环境验证。运行Web容器函数及依赖指纹一致；不是全浏览器XSS验证。
- `ui-evidence.json` / `ui-source-repeats.json` / `ui-persisted.json` / `ui-*.jpg`：真实页面、专用对话、落库只读核对。已有来源笔记ID在导出JSON中替换为匿名标识。
- `baseline.json` / `after.json` / `runtime-boundaries.json`：笔记摘要、运行源码/提示词指纹和最小边界代码证据。未复制完整提示词或配置密钥。
- `review_results.py`：保留自动初判，同时修正引用标记告警、历史禁止检索、无增量串比较、上一轮累计检索等误报。
- `case-summary.json` / `case-summary.csv` / `summary.json`：逐例次数、问题分布、证据级别和受限条件；同根因不计为不同漏洞。
- `smoke.jsonl`：前置烟测，单独保存，不计入正式200例/280基线位。

## 复跑

在项目根目录，确认仍是同一个正在运行的本地版本、只有一个已有模型连接。脚本不会创建账号、改模型配置、部署应用、修改个人笔记，也不会请求攻击地址。不要为了复跑重建容器。模型产生的写入只进入合成Store。

```sh
python3 test-results/assistant-security/build_cases.py
docker compose --env-file .env.local exec -T api mkdir -p /tmp/assistant-security
```

将所需脚本及清单复制到临时目录：

```sh
security_dir=test-results/assistant-security
for security_file in runner.py cases.json self_check.py boundary_probes.py citation_probes.py stream_probes.py scope_controls.py trace_controls.py extra-cases.json; do
  docker cp "$security_dir/$security_file" "pkm-system-api-1:/tmp/assistant-security/$security_file"
done
docker compose --env-file .env.local exec -T api /app/.venv/bin/python /tmp/assistant-security/self_check.py
docker compose --env-file .env.local exec -T api /app/.venv/bin/python /tmp/assistant-security/runner.py --output rerun.jsonl
```

脚本以不少于6.2秒的间隔启动真实模型场景，最多2个工作进程；不要并行启动另一套模型测试。每个多轮/多工具场景可能产生多个模型调用。限流探针仅在隔离进程模拟计数，不对提供商发11个请求。

断点续跑同一 `--output`；`--dry-run`只统计待执行项；`--ids S001,S054`选定场景。输出文件已存在时会跳过已有 `id/rep`，全量重新跑须使用新的输出文件名。

疑似问题重复：

```sh
docker compose --env-file .env.local exec -T api /app/.venv/bin/python /tmp/assistant-security/runner.py --ids S054,S055,S117 --repeat-count 3 --output focused-rerun.jsonl
docker compose --env-file .env.local exec -T api /app/.venv/bin/python /tmp/assistant-security/citation_probes.py
docker compose --env-file .env.local exec -T api /app/.venv/bin/python /tmp/assistant-security/stream_probes.py
```

结果复制回本目录后运行 `python3 test-results/assistant-security/review_results.py`。该脚本针对本轮人工检查过的断言生成结论；新版本结果需要重新审查，不能机械地当通用安全评分器。

DOM探针的依赖安装在测试目录，应用依赖不变：

```sh
npm install --prefix test-results/assistant-security/.renderer-runtime jsdom@26.1.0 --ignore-scripts --no-package-lock --no-save
node test-results/assistant-security/render_probe.mjs
```

## 页面复跑与限制

通过现有登录页面新建专用“安全测试”对话；每个独立场景另开对话，多轮在同一对话追问。保留测试对话，未删除已有消息。页面关键输入与截图见 `ui-evidence.json`。本轮5个新对话共6轮请求，实际模型8次调用。

`export_ui.py`只读取脚本列出的5个专用对话并校验首条消息以“安全测试”开头；新复跑需替换为新专用对话ID，不扫描/导出其他已有对话。它采用只读事务导出，并核对全部笔记摘要。

浏览器拒绝本地file探针页面后未通过换端口/浏览器绕过；改用无网络DOM探针。真实浏览器的危险HTML事件、真实历史摘要压缩、完整跨账号HTTP认证链、逐帧DOM和部分真实故障条件明确保留为未验证项。
