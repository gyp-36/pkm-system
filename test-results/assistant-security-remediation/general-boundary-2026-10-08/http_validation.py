"""Real TCP HTTP login/ownership; disposable database only."""
import json, os, uuid
import httpx
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.models import AssistantTrace, AssistantMessage
from app.core.enums import AssistantMessageRole

assert os.environ['DATABASE_URL'].endswith('/assistant_security')
clients = [httpx.Client(base_url='http://127.0.0.1:8001',timeout=30) for _ in range(2)]
users=[]
for i,client in enumerate(clients):
    body={'email':f'http-security-{uuid.uuid4().hex}@example.com','password':'SecurityTest123!'}
    r=client.post('/v1/auth/register',json=body);assert r.status_code==201
    client.post('/v1/auth/logout')
    r=client.post('/v1/auth/login',json=body);assert r.status_code==200
    users.append(uuid.UUID(r.json()['id']))
a,b=clients
note=a.post('/v1/notes',json={'title':'HTTP专用笔记','body_md':'合成资料'}).json()['id']
notebook=a.post('/v1/notebooks',json={'name':'HTTP测试本'}).json()['id']
conversation=a.post('/v1/assistant/conversations').json()['id']
with SessionLocal.begin() as db:
    message=AssistantMessage(user_id=users[0],conversation_id=uuid.UUID(conversation),role=AssistantMessageRole.ASSISTANT,content={'answer':'合成'})
    db.add(message);db.flush();mid=str(message.id)
    trace=AssistantTrace(user_id=users[0],conversation_id=uuid.UUID(conversation),assistant_message_id=message.id,entrypoint='http-security',status='success',steps=[])
    db.add(trace);db.flush();tid=str(trace.id)
checks=[]
for rep in range(1,4):
    for path in [f'/v1/notes/{note}',f'/v1/assistant/conversations/{conversation}',f'/v1/dev/assistant-traces/{tid}',f'/v1/dev/assistant-traces/by-message/{mid}']:
        own=a.get(path).status_code;other=b.get(path).status_code
        assert own==200 and other==404,(path,own,other)
        checks.append({'rep':rep,'route':path.split('/')[2:4],'own':own,'other':other})
    assert b.patch(f'/v1/notebooks/{notebook}',json={'name':'越权'}).status_code==404
    assert b.post(f'/v1/assistant/conversations/{conversation}/messages',json={'question':'4'}).status_code==404
    listing=b.get('/v1/dev/assistant-traces',params={'conversation_id':conversation}).json()
    assert all(item['id']!=tid for item in listing['items'])
print(json.dumps({'status':'passed','mode':'real_tcp_http','accounts':2,'repeats':3,'checks':checks,'notebook_other':404,'conversation_write_other':404,'trace_listing_isolated':True},ensure_ascii=False))
