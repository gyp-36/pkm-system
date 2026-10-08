"""Real HTTP response contract extensibility, synthetic historical rows only."""
import json
import os
import uuid
from pathlib import Path
import httpx
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.enums import AssistantMessageRole
from app.core.models import Account, AssistantMessage

assert os.environ['DATABASE_URL'].endswith('/assistant_security')
root = Path(__file__).parent
client = httpx.Client(base_url='http://127.0.0.1:8001', timeout=30)
assert client.post('/v1/auth/login', json={'email': 'security-ui@example.com', 'password': 'SecurityTest123!'}).status_code == 200
records = []
for rep in range(1, 4):
    cid = uuid.UUID(client.post('/v1/assistant/conversations').json()['id'])
    unknown_key = 'server_extension_' + uuid.uuid4().hex[:8]
    data = {'answer': '普通回答', 'citations': [], unknown_key: {'control_token': 'SYNTHETIC_CONTROL_CANARY'}}
    literal = json.dumps({unknown_key: {'control_token': 'USER_DOCUMENT_EXAMPLE'}}, ensure_ascii=False)
    with SessionLocal.begin() as db:
        uid = db.scalar(select(Account.id).where(Account.email == 'security-ui@example.com'))
        db.add(AssistantMessage(user_id=uid, conversation_id=cid, role=AssistantMessageRole.USER, content={'text': literal}))
        db.add(AssistantMessage(user_id=uid, conversation_id=cid, role=AssistantMessageRole.ASSISTANT, content=data))
    response = client.get('/v1/assistant/conversations/' + str(cid))
    assert response.status_code == 200
    items = response.json()['messages']
    assistant = next(item for item in items if item['role'] == 'assistant')['content']
    user = next(item for item in items if item['role'] == 'user')['content']
    retained = unknown_key in assistant
    records.extend([
        {'id': 'API_UNREGISTERED_CONTENT_FIELD', 'rep': rep, 'mode': 'real_tcp_http_synthetic_legacy_row',
         'expected': '未登记服务器控制字段不得随历史消息响应返回',
         'observed': {'unregistered_field_retained': retained, 'control_canary_returned': 'SYNTHETIC_CONTROL_CANARY' in json.dumps(assistant)},
         'status': '发现问题' if retained else '通过'},
        {'id': 'API_LITERAL_JSON_PRESERVED', 'rep': rep, 'mode': 'real_tcp_http_synthetic_legacy_row',
         'expected': '用户正文中的同类JSON字段作为文字资料正常保留',
         'observed': {'literal_preserved': user.get('text') == literal}, 'status': '通过' if user.get('text') == literal else '发现问题'},
    ])
    root.joinpath('response-contract-results.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
print(json.dumps({'executions': len(records), 'passed': sum(item['status'] == '通过' for item in records),
                  'failed': sum(item['status'] == '发现问题' for item in records), 'real_model_calls': 0}))
