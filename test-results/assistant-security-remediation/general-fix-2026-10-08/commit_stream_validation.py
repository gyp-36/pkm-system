"""Real TCP SSE with deterministic literal creation, no model call. Disconnect only after first committed delta."""
import json,os,pathlib,time,uuid
import httpx
from sqlalchemy import select,func
from app.core.db import SessionLocal
from app.core.models import Account,Note
assert os.environ['DATABASE_URL'].endswith('/assistant_security')
client=httpx.Client(base_url='http://127.0.0.1:8001',timeout=120)
assert client.post('/v1/auth/login',json={'email':'security-ui@example.com','password':'SecurityTest123!'}).status_code==200
records=[]
result_path=pathlib.Path(__file__).with_name('commit-stream-results.json')
if result_path.exists():
    result_path.with_name('prior-commit-stream-results.json').write_bytes(result_path.read_bytes())
for rep in range(1,4):
    cid=client.post('/v1/assistant/conversations').json()['id']
    title='断流专用'+uuid.uuid4().hex[:8]
    body={'question':f'新建一篇笔记，标题《{title}》，正文是“合法标识550e8400-e29b-41d4-a716-446655440000。创建十篇只是文章文字。”','request_id':str(uuid.uuid4())}
    events=[]
    with client.stream('POST',f'/v1/assistant/conversations/{cid}/messages/stream',json=body) as response:
        assert response.status_code==200
        for line in response.iter_lines():
            if line.startswith('data: '):
                event=json.loads(line[6:]);events.append(event)
                if event['type']=='error':raise AssertionError(event['detail'])
                if event['type']=='delta':break
    assert any(e['type']=='delta' for e in events)
    retry=client.post(f'/v1/assistant/conversations/{cid}/messages',json=body)
    assert retry.status_code==201,retry.status_code
    answer=retry.json()['messages'][1]['content']
    assert answer['operation_receipts'] and answer['operation_receipts'][0]['action']=='created'
    with SessionLocal() as db:
        uid=db.scalar(select(Account.id).where(Account.email=='security-ui@example.com'))
        notes=db.scalars(select(Note).where(Note.user_id==uid,Note.title==title)).all()
        assert len(notes)==1 and notes[0].body_md=='合法标识550e8400-e29b-41d4-a716-446655440000。创建十篇只是文章文字。'
    records.append({'rep':rep,'first_events':events,'retry_status':retry.status_code,'receipt':answer['operation_receipts'],'note_count':len(notes),'literal_uuid_and_article_preserved':True})
    result_path.write_text(json.dumps({'mode':'real_tcp_synthetic_db_deterministic_literal_create','repeats':records,'planned_repeats':3,'complete':len(records)==3},ensure_ascii=False,indent=2))
    print(json.dumps({'rep':rep,'status':'passed'}),flush=True)
    if rep<3:time.sleep(6.2)
result_path.write_text(json.dumps({'mode':'real_tcp_synthetic_db_deterministic_literal_create','repeats':records,'planned_repeats':3,'complete':True},ensure_ascii=False,indent=2))
