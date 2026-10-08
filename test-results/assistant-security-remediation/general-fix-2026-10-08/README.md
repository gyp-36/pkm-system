# 通用安全边界修复验证

本目录保留本轮脚本、合成输入、逐例模型输出和修复前后的候选结果。最终结论见 `REPORT.md`，统计见 `summary.json`、`case-summary.csv`；`pre-*` 文件仅作为历史证据，不能代替当前版本验收。整批基线与最终健康规则增量使用不同指纹，分别保存，不将旧记录改标为最终字节版本结果。

## 环境与复跑

脚本使用已有 API 容器的 Python 环境，应用源码复制到 `/tmp/assistant-remediation/api`，测试脚本放在 `/tmp/assistant-remediation/fix-tests`。已有运行服务的 `/app` 不被覆盖。必须先准备独立测试 PostgreSQL，数据库名为 `assistant_security`；测试脚本会校验该数据库名。真实模型连接只从原配置只读取得，合成存储或独立数据库承接所有写入。结果中不保存真实凭据或个人笔记原文。

当前已准备的测试数据库地址为：

```text
postgresql+psycopg://security_test:SecurityTestOnly123@pkm-assistant-security-db:5432/assistant_security
```

该地址及测试账号密码只用于本地合成环境。复跑前保存旧结果，复制当前 `api/app`、`api/scripts` 及本目录脚本，再更新 `freeze-manifest.json` 中的完整源码 SHA256。`acceptance_validation.py` 会核验源码指纹；`runner.py` 拒绝复用不同版本的结果。不得直接删除旧失败记录。

以下命令在项目根目录执行，适用于已经准备好上述测试环境的工作区：

```sh
docker exec -w /tmp/assistant-remediation/api \
  -e PYTHONPATH=/tmp/assistant-remediation/api \
  -e DATABASE_URL=postgresql+psycopg://security_test:SecurityTestOnly123@pkm-assistant-security-db:5432/assistant_security \
  pkm-system-api-1 /app/.venv/bin/python \
  /tmp/assistant-remediation/fix-tests/run_deterministic.py
```

同样的隔离环境参数可运行 `boundary_properties.py`、`response_contract_validation.py`、`deep_contract_validation.py`、`extended_boundary_validation.py` 和 `route_boundary_validation.py`；后者再加 `--stream-first` 验证 SSE 首发。真实 TCP 脚本需要当前源码的隔离 `ui_server.py` 在 8001 端口运行，使用 `http_validation.py`、`commit_stream_validation.py` 和 `history_validation.py` 验证。

真实模型整批执行：

```sh
docker exec -w /tmp/assistant-remediation/api pkm-system-api-1 \
  /app/.venv/bin/python /tmp/assistant-remediation/fix-tests/acceptance_validation.py
```

它按顺序执行基础 280 个计划槽位、原问题补测、12 个附加场景各三次，以及曾发生环境故障的场景复测；基础中未实现的探针会明确写为未验证。并发最多两个场景，每 6.2 秒最多启动一个模型场景；认证、额度或限流错误及连续连接失败触发停止，不自动充值或绕过限流。多轮的实际模型调用单独统计。字面新建可能由服务器直接执行，`model_calls=0`，不能算作真实模型测试。

`review_results.py` 在宿主机运行，重新生成脱敏统计；它区分执行故障、发现问题和未验证，不将全部执行记录自动视为通过。`verify_redaction.py` 在原容器中只读检查当前凭据及其 Base64 形式是否进入交付文件，包括 JSONL。`personal_snapshot.py` 只读输出个人笔记和聊天配置的摘要，不输出原文或资源 ID。

## 证据分层

| 文件 | 证据性质 |
| --- | --- |
| `cases.json`、`extra-cases.json` | 200 个基础场景和附加场景的独立输入、预期与判据 |
| `frozen-results.jsonl` | 整批基线结果；含真实模型、确定性探针和未验证槽位 |
| `health-delta-results.jsonl`、`health-delta-scope.json` | 最终增量的实际执行与 AST 影响范围；没有替换基线记录 |
| `acceptance-supplement-results.jsonl`、`acceptance-extra-results.jsonl`、`provider-recovery-results.jsonl` | 同版本补测，不覆盖基础失败 |
| `deterministic-results.json` | 实际路由与 PostgreSQL 回归，模型或故障条件受控 |
| `property-results.json`、`extended-results.json` | 通用类型、授权、出口、历史与归属边界检查 |
| `route-boundary-results.json`、`initial-stream-route-results.json` | 不安全代理与核验器输出的受控首发及重放测试 |
| `http-results.json` | 两个账号实际 HTTP 登录和跨账号资源访问 |
| `commit-stream-results.json` | 真实 TCP 提交后断流与幂等恢复；字面新建没有模型调用 |
| `history-results.json` | 真实模型历史压缩与未索引合成笔记召回 |
| `vector-integration-results.json` | 原配置 Ollama 端点的实际索引和账号隔离召回 |
| `browser-history-results.json`、`browser-render-results.json` | 此前已采集的真实 Chrome 页面/DOM 证据；保留其适用范围 |
| `browser-unavailable.json` | 当前版本浏览器补测失败，页面网络及逐帧条件未验证 |
| `freeze-manifest.json`、`runtime-consistency.json` | 源码、提示词和运行版本对照 |
| `personal-comparison.json`、`redaction-verification.json` | 个人数据摘要比较与交付凭据扫描 |

浏览器 DOM 没有危险节点不等于已验证浏览器网络没有外发；后端 SSE 只发送提交结果不等于取得页面逐帧证据。语义核验也不是资源鉴权或对任意编码的形式化安全证明。
