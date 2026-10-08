"""Controlled assistant outputs to inspect actual browser sanitizer; no model calls."""
import json,os,pathlib
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.enums import AssistantMessageRole
from app.core.models import Account,AssistantConversation,AssistantMessage
assert os.environ['DATABASE_URL'].endswith('/assistant_security')
payloads={
 'S111':'<script>alert("XSS_CANARY")</script><p>合法文本A</p>',
 'S112':'<div onclick="alert(\'XSS_CANARY\')">合法文本B</div><img src="https://fixture.example/pixel" onerror="alert(1)">',
 'S113':'<a href="javascript:alert(\'XSS_CANARY\')">危险协议示例</a>',
 'S114':'<iframe src="https://fixture.example/embed"></iframe><p>iframe示例</p>',
 'S115':'![图片](https://fixture.example/pixel)',
 'S116':'[安全登录](https://fixture.example/phishing)',
 'CODE':'```html\n<script>alert("XSS_CANARY")</script>\n<div onclick="alert(1)">代码保持</div>\n```',
}
records=[]
with SessionLocal.begin() as db:
 uid=db.scalar(select(Account.id).where(Account.email=='security-ui@example.com'))
 for cid,body in payloads.items():
  c=AssistantConversation(user_id=uid,title='呈现测试 '+cid);db.add(c);db.flush()
  db.add(AssistantMessage(user_id=uid,conversation_id=c.id,role=AssistantMessageRole.USER,content={'text':'安全测试：呈现合成输出 '+cid}))
  db.add(AssistantMessage(user_id=uid,conversation_id=c.id,role=AssistantMessageRole.ASSISTANT,content={'answer':body,'citations':[],'semantic_status':'not_requested','answer_source':'model_knowledge','retrieval_status':'not_requested'}))
  records.append({'id':cid,'url':'http://127.0.0.1:15174/#/assistant?conversation='+str(c.id),'input':body,'mode':'real_browser_controlled_assistant_output'})
pathlib.Path(__file__).with_name('render-fixtures.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
print(json.dumps(records,ensure_ascii=False))
