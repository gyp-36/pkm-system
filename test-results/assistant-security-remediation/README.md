# AI 助手安全修复验证

本目录与原 `../assistant-security/` 分离。模型使用已有连接，只在原数据库的只读事务中读取配置；测试数据使用独立PostgreSQL库 `assistant_security`。不能把原服务的DATABASE_URL直接传给事务验证脚本。

## 复跑

1. 使用PGVector PostgreSQL建立专用容器/库 `assistant_security`，确保 `DATABASE_URL` 以 `/assistant_security` 结尾。复用现有API容器的Python依赖，但将当前API源码复制到 `/tmp/assistant-remediation/api`，将本目录复制到 `/tmp/assistant-remediation/tests`。更新目录时复制 `api/app/.` 的内容，避免形成嵌套app/app。
2. 在专用库执行 `python -m alembic upgrade head`。只修改该子进程的DATABASE_URL/PYTHONPATH，不更改原服务环境或原数据库。
3. 执行 `run_deterministic.py`（PYTHONPATH指向上述源码，工作目录为其api目录）。它顺序运行安全事务、SSRF、契约、M2、对话和追踪验证，并写入deterministic-results.json。M2关键词回退成功不等于真实向量服务通过。
4. 真实模型合成服务回归：将原模型连接的数据库地址放在 `SECURITY_PROVIDER_DATABASE_URL`，将 `DATABASE_URL` 指向专用库。执行 `runner.py --output 新文件.jsonl`。默认200场景280次计划执行；最多两个并发，每6.2秒启动一个模型场景。`--ids`可筛选，`--repeat-count 3`重复指定场景；同一输出文件按id/rep续跑，不覆盖已记录结果。
5. `runner.py --cases-file extra-cases.json --output 新对照文件.jsonl` 运行附加正常对照。所有网络抓取/写入副作用仅发生在合成Store；HTTP/PostgreSQL事务验证与这个结果分开看。
6. `ui_server.py` 在原API容器的独立8001端口运行当前复制源码，使用专用库和合成账号；它只读原模型连接并复制加密配置，不更改原账号。`ui_proxy.mjs` 服务实际构建的web/dist，代理到8001，使用独立15174端口。不要替换原8000/15173服务。
7. `http_validation.py` 验证两个账号实际TCP登录和归属；`history_validation.py` 验证真实模型历史压缩/未索引笔记；`commit_stream_validation.py` 验证提交后断流和幂等恢复三次；`render_fixtures.py`只生成受控回答供真实浏览器检查，不代表模型端到端执行。
8. `check_personal_data.py` 必须在原容器原环境只读执行；与before.json比较，仅输出摘要。复跑不得导出个人笔记正文、模型凭据或真实账号追踪。
9. `launch_model.py`在原容器中保留原数据库地址为只读模型配置来源，并在独立子进程使用专用数据库；避免在命令行回显原DSN。连续三次提供商连接/超时故障后停止启动新场景，未执行项保留待测，不反复冲击不可用服务。
10. `review_results.py`输出逐例覆盖、原始记录复核及统计，按场景/重复编号/开始时间去重快照，保留历次失败。`freeze-manifest.json`与每例source_fingerprints核对冻结版本；浏览器实际资产见browser-assets.json。
11. `acceptance_validation.py`在冻结源码上顺序运行280次基础执行、98次原失败补充及36次正常/边界对照，然后运行真实HTTP与历史集成；结果分别保存acceptance-*.jsonl，旧冻结结果另存pre-acceptance-results.jsonl。单独运行commit_stream_validation.py保存断流三次的结构化证据，不以stdout状态行覆盖结果。
12. `export_validation_ui.py`仅从专用库导出合成UI账号，核对三次页面数字回答与落库。`verify_artifacts.py`必须在原容器原环境只读运行，检查交付资料中是否出现现有密钥或其Base64，并比较原服务/验证服务源码指纹；不输出密钥值。

## 判定与限制

原始记录中的“待复核”不是通过。marker_quoted仅表示回答引用了攻击字符串，需核对是否只是警告；HTTP409也必须区分受控版本冲突和异常。报告保留初次失败与修复后的重复结果，不能删除失败以提高通过率。源码变化通过逐例source_fingerprints记录；发布前必须在冻结源码上重新完成门禁，不能用旧容器或早期源码记录替代。

浏览器结果区分实际模型问答与受控回答呈现。未取得浏览器网络捕获及完整逐帧轨迹时，不声称这些项目通过。该测试不会迁移个人库或部署原服务；发布状态见REPORT.md。

健康向量条件：vector_validation.py只允许专用库与隔离Ollama端点，模型缓存只读挂载。真实索引/两账号各三次纯向量召回结果见vector-integration-results.json；原配置端点故障单列，不能声称已修复生产环境。
