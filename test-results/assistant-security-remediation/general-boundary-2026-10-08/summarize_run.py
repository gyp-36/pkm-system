# -*- coding: utf-8 -*-
"""Summarize recorded evidence without marking blocked slots as executed."""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).parent
read = lambda name: json.loads(root.joinpath(name).read_text(encoding='utf-8'))
cases = read('cases.json')
rows = [json.loads(line) for line in root.joinpath('general-results.jsonl').read_text(encoding='utf-8').splitlines() if line]
by_id = {}
for row in rows:
    by_id.setdefault(row['id'], []).append(row)
coverage = []
for case in cases:
    executions = by_id.get(case['id'], [])
    good = sum(row['status'] == '通过' for row in executions)
    unverified = sum(row['status'] == '未验证' for row in executions)
    faults = sum(row['status'] == '环境故障' for row in executions)
    status = '受限待验证' if case['mode'] != 'probe' else '未验证' if unverified else '目标断言通过' if good == case['repeats'] else '未完成'
    reason = '当前提供商独立诊断返回HTTP402余额不足；未取得真实模型回答，未启动其余模型场景。' if case['mode'] != 'probe' else ';'.join({row.get('limitation', '') for row in executions if row['status'] == '未验证'})
    coverage.append({'id': case['id'], 'group': case['group'], 'question': case['question'], 'expected': case['expected'],
                     'planned_executions': case['repeats'], 'recorded_plan_slots': len(executions),
                     'actual_attempts': sum(row['status'] != '未验证' for row in executions), 'passes': good,
                     'faults': faults, 'unverified_placeholders': unverified, 'status': status, 'reason': reason})
root.joinpath('coverage.json').write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding='utf-8')
with root.joinpath('coverage.csv').open('w', encoding='utf-8-sig', newline='') as file:
    writer = csv.DictWriter(file, fieldnames=list(coverage[0]))
    writer.writeheader()
    writer.writerows(coverage)

props = read('property-results.json') + read('response-contract-results.json') + read('deep-contract-results.json')
routes = read('route-boundary-results.json') + read('initial-stream-route-results.json')
browser, legacy = read('browser-results.json'), read('browser-legacy-results.json')
summary = {
    'generated_at': datetime.now(timezone.utc).isoformat(), 'overall': '未通过完整验收',
    'original_scenarios': len(cases), 'original_plan_executions': sum(case['repeats'] for case in cases),
    'base_recorded_slots': len(rows), 'base_actual_attempts': sum(row['status'] != '未验证' for row in rows),
    'real_model_scenario_attempts': sum(case['mode'] != 'probe' for case in cases for row in by_id.get(case['id'], [])),
    'real_model_complete_answers': 0,
    'base_executed_probes': sum(row.get('mode') == 'deterministic_probe' and row['status'] != '未验证' for row in rows),
    'base_probe_passes': sum(row['status'] == '通过' for row in rows),
    'base_unverified_placeholders': sum(row['status'] == '未验证' for row in rows),
    'original_model_scenarios_blocked': sum(case['mode'] != 'probe' for case in cases),
    'original_model_repeats_not_started': sum(case['repeats'] for case in cases if case['mode'] != 'probe') - sum(case['mode'] != 'probe' for case in cases for row in by_id.get(case['id'], [])),
    'properties': {'independent': len({row['id'] for row in props}), 'executions': len(props),
                   'passed': sum(row['status'] == '通过' for row in props), 'failed': sum(row['status'] == '发现问题' for row in props)},
    'controlled_routes': {'scenarios': len({row['id'] for row in routes}), 'executions': len(routes),
                          'passed': sum(row['status'] == '通过' for row in routes), 'failed': sum(row['status'] == '发现问题' for row in routes),
                          'real_model_calls': 0, 'execution_orders': ['sync_first', 'SSE_first']},
    'browser': {'controlled_render_executions': len(browser), 'passed': sum(row['passed'] for row in browser),
                'legacy_executions': len(legacy), 'legacy_failed': sum(not row['passed'] for row in legacy),
                'network_capture': '未验证', 'per_frame': '未验证'},
    'provider': read('provider-health.json'),
    'security_modules_passed': sum(row['exit_code'] == 0 for row in read('deterministic-results.json')['results']),
    'private_vector_checks': 6, 'personal_notes': read('personal-comparison.json'), 'personal_messages': read('personal-message-comparison.json'),
    'findings': ['自由文本出口不足以阻止模型/核验器输出内部身份变形和控制元数据',
                 '旧助手消息在历史输入、HTTP返回及页面/复制上缺少统一安全投影',
                 '消息content和模型信封的开放容器/字段类型缺少完整契约'],
}
root.joinpath('summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({key: summary[key] for key in ['original_scenarios', 'base_recorded_slots', 'base_actual_attempts',
                 'real_model_scenario_attempts', 'base_executed_probes', 'base_unverified_placeholders',
                 'original_model_repeats_not_started', 'properties', 'controlled_routes', 'browser']}, ensure_ascii=False, indent=2))
