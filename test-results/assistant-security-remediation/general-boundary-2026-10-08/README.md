# 通用边界测试复跑

本目录保留本轮结果，不覆盖此前报告。源文件和规则指纹见freeze-manifest.json；当前完整结论见REPORT.md。

所有有副作用脚本必须在专用`assistant_security`数据库执行，均有DSN后缀断言。使用现有API容器依赖及已有提供商配置，原配置只读。不要把个人DSN传给属性、路由、HTTP或向量脚本。

1. 将当前API源码复制到容器`/tmp/assistant-remediation/api`；本目录复制到`/tmp/assistant-remediation/tests`。复制目录内容时使用`目录/.`，防止形成嵌套目录。
2. 子进程设置PYTHONPATH指向复制源码、DATABASE_URL指向专用库；保持个人服务环境不变。专用库应具有当前兼容迁移。
3. `run_deterministic.py`执行六项模块，`boundary_properties.py`执行38项通用属性，`response_contract_validation.py`执行两项真实HTTP响应契约属性，`deep_contract_validation.py`执行三项模型深层契约属性。合计43项、每项三次。
4. `ui_server.py`使用专用库及合成UI账号在8001启动；http_validation.py运行两账号真实TCP检查。测试前核验启动指纹与冻结清单。
5. `route_boundary_validation.py`在实际路由及PostgreSQL中替代代理和核验器，验证同步首发；增加`--stream-first`验证SSE首发。没有真实模型调用，不能将其算作模型回复成功。
6. `vector_validation.py`只允许隔离Ollama端点`http://pkm-assistant-security-vector:11434`及专用库，缓存模型只读；不修改个人模型或端点。
7. `render_fixtures.py`生成七个合成输出。用真实浏览器在15174专用页面登录合成账号，检查DOM和合法文字；browser-results.json及browser-legacy-results.json为实际CUA执行结果，不由脚本模拟生成。未获取网络或逐帧轨迹时继续标为未验证。
8. 模型条件恢复后执行`launch_model.py --output 新模型记录.jsonl`。默认200场景280次；已有失败不能删除或当作通过。旧文件的id/rep会被视为已记录，补测建议使用新文件并在报告合并时保留失败。每6.2秒启动，最多两个并发；认证、余额、权限或限流错误停止新场景。
9. `personal_snapshot.py`及check_personal_data.py在原环境只读执行，只导出摘要。verify_redaction.py检查本目录是否出现真实配置秘密；不导出秘密值。
10. `summarize_run.py`重建本轮覆盖和统计，严格区分实际执行、未验证占位、上游故障及受控结果；新增模型文件需显式纳入下一轮统计，不能直接以旧summary作为补测结果。

本轮提供商独立诊断为HTTP402余额不足，因此没有完成真实模型验收。脚本正常退出表示记录流程完成，不能替代逐例判定。
