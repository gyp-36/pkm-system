"""Synthetic legacy UI rows only; no model calls or production writes."""
import json,os,uuid
from pathlib import Path
import httpx
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.models import Account,AssistantMessage
from app.core.enums import AssistantMessageRole
assert os.environ['DATABASE_URL'].endswith('/assistant_security')
c=httpx.Client(base_url='http://127.0.0.1:8001',timeout=30)
assert c.post('/v1/auth/login',json={'email':'security-ui@example.com','password':'SecurityTest123!'}).status_code==200
items=[]
for i in range(1,4):
 cid=c.post('/v1/assistant/conversations').json()['id']; c.patch('/v1/assistant/conversations/'+cid,json={'title':'安全边界回归-历史'+str(i)})
 nid=c.post('/v1/notes',json={'title':'安全测试资料'+str(i),'body_md':'普通合成资料'}).json()['id']
 raw='已定位合成资料（内部笔记ID '+nid+'，内部版本1）。'
 with SessionLocal.begin() as db:
  uid=db.scalar(select(Account.id).where(Account.email=='security-ui@example.com'))
  db.add(AssistantMessage(user_id=uid,conversation_id=uuid.UUID(cid),role=AssistantMessageRole.USER,content={'text':'请概括合成资料。'}))
  db.add(AssistantMessage(user_id=uid,conversation_id=uuid.UUID(cid),role=AssistantMessageRole.ASSISTANT,content={'answer':raw,'citations':[],'server_extension':{'nested':'SYNTHETIC_CONTROL_CANARY'}}))
 response=c.get('/v1/assistant/conversations/'+cid).json()
 visible=next(x['content']['answer'] for x in response['messages'] if x['role']=='assistant')
 items.append({'id':cid,'title':'安全边界回归-历史'+str(i),'internal':nid,'http_projected_text':visible,'http_safe':nid not in json.dumps(response) and 'SYNTHETIC_CONTROL_CANARY' not in json.dumps(response)})
Path(__file__).with_name('browser-fixtures.json').write_text(json.dumps(items,ensure_ascii=False,indent=2))
print(json.dumps({'fixtures':len(items),'http_safe':all(x['http_safe'] for x in items)}))
