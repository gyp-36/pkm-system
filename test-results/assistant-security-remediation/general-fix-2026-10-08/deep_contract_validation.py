"""Check unmodeled containers and scalar type substitution in model envelopes."""
import json
from pathlib import Path
from app.assistant.tool_contract import tool_result

root = Path(__file__).parent
records = []
for rep in range(1, 4):
    tests = [
        ('MODEL_UNMODELED_METADATA', {'metadata': {'user_id': 'SYNTHETIC_SERVER_ID', 'server_only_extension': 'SYNTHETIC_CONTROL'}}, False,
         '工具元数据容器中的未登记控制字段不能穿过模型信封'),
        ('MODEL_SCALAR_AS_CONTAINER', {'title': {'user_id': 'SYNTHETIC_SERVER_ID'}}, False,
         '标题标量不能变成携带未登记控制字段的嵌套对象'),
        ('MODEL_LITERAL_JSON_DOCUMENT', {'markdown': '{"user_id":"USER_DATA_EXAMPLE","version":7}', 'metadata': {}}, True,
         '文档字符串中的合法JSON字段保持作为资料'),
    ]
    for identifier, payload, allowed, expected in tests:
        try:
            result = tool_result('external_link_ok', payload)
            accepted = True
            canary = 'SYNTHETIC_SERVER_ID' in result
        except KeyError:
            accepted, canary = False, False
        records.append({'id': identifier, 'rep': rep, 'mode': 'deterministic_model_envelope_contract',
                        'expected': expected, 'observed': {'accepted': accepted, 'server_control_canary_in_payload': canary},
                        'status': '通过' if accepted == allowed else '发现问题',
                        'limitation': '直接调用实际信封构造器；当前抓取工具metadata固定为空，没有证明真实控制信息已被抓取工具泄漏。'})
root.joinpath('deep-contract-results.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
print(json.dumps({'executions': len(records), 'passed': sum(row['status'] == '通过' for row in records),
                  'failed': sum(row['status'] == '发现问题' for row in records)}))
