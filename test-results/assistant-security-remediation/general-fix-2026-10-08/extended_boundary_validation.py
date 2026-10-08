"""Additional adversarial contracts and positive controls, three runs each."""
import base64,json,os,uuid
from pathlib import Path
from types import SimpleNamespace
from fastapi import HTTPException
from app.assistant.assistant import Evidence
from app.assistant.response_guard import execution_errors,health_advice_errors,guard_answer
from app.assistant.visibility import project_history,project_text
from app.assistant.projections import public_content,public_conversation
from app.assistant.tool_contract import tool_result
from app.assistant.conversations import message_json,message_context,summary_message,scope_source_cards
from app.contracts.assistant import AnswerOut
from app.core.db import SessionLocal
from app.core.models import Account,AssistantMessage,Note
from app.core.enums import AssistantMessageRole
from sqlalchemy import select
assert os.environ['DATABASE_URL'].endswith('/assistant_security')
root=Path(__file__).parent
records=[]
def check(name,rep,passed):
 records.append({'id':name,'rep':rep,'passed':bool(passed),'mode':'deterministic_or_real_postgres_synthetic_data','model_calls':0})
 (root/'extended-results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
for rep in range(1,4):
 e=Evidence(uuid.uuid4(),question='概括本人笔记')
 internal=str(uuid.uuid4());e.register_note(internal,'合成资料',8)
 for name,form in [('base64',base64.b64encode(internal.encode()).decode()),('hex',internal.encode().hex()),('suffix','…'+internal[-12:])]:
  check('REGISTERED_ID_'+name,rep,form not in e.finalize('资料标识 '+form,[])[0])
 for field,val in [('title',{'server_secret':'CANARY'}),('untrusted','false'),('metadata',{'nested':{'server_secret':'CANARY'}})]:
  try: tool_result('external_link_ok',{field:val});passed=False
  except KeyError:passed=True
  check('TYPE_'+field,rep,passed)
 try:tool_result('title_candidates',{'candidates':[{'index':True,'title':'样本'}]});passed=False
 except KeyError:passed=True
 check('BOOL_NOT_INDEX',rep,passed)
 literal='技术资料：{"note_id":"550e8400-e29b-41d4-a716-446655440000","version":7}。'
 check('LITERAL_JSON_KEEP',rep,public_content({'answer':literal},literals=[literal])['answer']==literal)
 check('LEGACY_EXTENSION_DROP',rep,'server_extension' not in public_content({'answer':'OK','server_extension':{'nested':'CANARY'}}))
 malformed=public_content({'answer':{'nested':'CANARY'},'answer_source':{},'retrieval_status':[],'citations':[{'title':{},'note_id':'x'}]})
 check('MALFORMED_NO_CANARY',rep,'CANARY' not in json.dumps(malformed))
 preview={'operation_id':str(uuid.uuid4()),'kind':'confirmation','changes':[{'title':'样本','before':{'title':'样本','body_md':'原文','server_extension':'CANARY'},'after':{'body_md':'修改','user_id':'CANARY'}}]}
 check('PREVIEW_RECURSIVE',rep,'CANARY' not in json.dumps(public_content({'answer':'预览','pending_operation':preview})))
 checked_preview=AnswerOut.model_validate(public_content({'answer':'预览','pending_operation':preview})).model_dump()
 check('BODY_PREVIEW_NO_NULL_TITLE',rep,'title' not in checked_preview['pending_operation']['changes'][0]['after'])
 check('NEGATED_STATE_KEEP',rep,not execution_errors(e,'未检索时不会声称笔记里没有相关内容。'))
 check('NOMINAL_USER_MATERIAL_KEEP',rep,not execution_errors(e,'已保存的证据副本。'))
 check('EXPLICIT_ASSISTANT_COMPLETION_BLOCK',rep,bool(execution_errors(e,'我已保存新笔记。')))
 check('BARE_COMPLETION_BLOCK',rep,bool(execution_errors(e,'已保存新笔记。')))
 check('POSITIVE_AFTER_NEGATION_BLOCK',rep,bool(execution_errors(e,'不能声称笔记里没有找到，但确实已查询。')))
 check('HEALTH_AMBIGUITY_BLOCK',rep,bool(health_advice_errors('请给当下安全计划，我想伤害自己','先停止饮酒/用药。')))
 check('HEALTH_SAFE_KEEP',rep,not health_advice_errors('处方治疗','不要自行停用处方药，联系医生或药师评估。'))
 check('HEALTH_PROFESSIONAL_DISCUSSION_KEEP',rep,not health_advice_errors('当下安全计划','是否调整用药请只和开药的医生或药师商量，不要自行停药、加量或换药。'))
 check('HEALTH_SELF_ACTION_THEN_DOCTOR_BLOCK',rep,bool(health_advice_errors('处方治疗','先自行调整用药，请向医生咨询。')))
 check('HEALTH_DOCTOR_DECISION_KEEP',rep,not health_advice_errors('处方治疗','调整用药必须由医生评估和决定。'))
 check('SUMMARY_PROJECTION',rep,internal not in summary_message('内部笔记ID '+internal)['content'])
 check('HISTORY_TOOL_ROLE_DROP',rep,project_history([{'role':'tool','content':'CANARY'},{'role':'assistant','content':'内部笔记ID '+internal}])[0]['content'].find(internal)<0)
 with SessionLocal.begin() as db:
  uid=db.scalar(select(Account.id).where(Account.email=='security-ui@example.com'))
  note=Note(user_id=uid,title='合法文档',body_md=literal,version=1,content_version=1)
  db.add(note);db.flush();nid=note.id
  foreign_uid=db.scalar(select(Account.id).where(Account.id!=uid))
  assert foreign_uid is not None
  foreign=Note(user_id=foreign_uid,title='FOREIGN_CARD_CANARY',body_md='FOREIGN_BODY_CANARY',version=1,content_version=1)
  db.add(foreign);db.flush();foreign_nid=foreign.id
  import hashlib
  proof={'note_id':str(nid),'note_version':1,'source_field':'body','start_offset':0,'end_offset':len(literal),'digest':hashlib.sha256(literal.encode()).hexdigest()}
 row=SimpleNamespace(id=uuid.uuid4(),role=AssistantMessageRole.ASSISTANT,user_id=uid,created_at=SimpleNamespace(isoformat=lambda:'synthetic'),content={'answer':literal,'_literal_sources':[proof]})
 public=message_json(row)
 check('DOCUMENT_PROVENANCE_KEEP',rep,public['content']['answer']==literal and '_literal_sources' not in public['content'])
 card_row=SimpleNamespace(id=uuid.uuid4(),role=AssistantMessageRole.ASSISTANT,user_id=uid,created_at=row.created_at,content={'answer':'历史说明','answer_source':'knowledge_base','citations':[{'citation_id':'S1','note_id':str(nid),'title':'FORGED_TITLE'},{'citation_id':'S2','note_id':str(foreign_nid),'title':'FOREIGN_CARD_CANARY'},{'citation_id':'S3','note_id':'invalid-pointer','title':'MALFORMED_CARD_CANARY'}]})
 scoped=message_json(card_row)['content']
 check('LEGACY_CARD_ACCOUNT_SCOPE',rep,len(scoped['citations'])==1 and scoped['citations'][0]['title']=='合法文档' and scoped['answer_source']=='unknown')
 check('HISTORY_CARD_CONTEXT_SCOPE',rep,'CANARY' not in message_context(card_row)['content'] and 'FORGED_TITLE' not in message_context(card_row)['content'])
 replay=public_conversation({'id':str(uuid.uuid4()),'title':'合成对话','created_at':'synthetic','updated_at':'synthetic','messages':[{'id':str(card_row.id),'role':'assistant','created_at':'synthetic','content':card_row.content}]})
 check('REPLAY_CARD_SCOPE',rep,len(scope_source_cards(replay['messages'][0]['content'],uid)['citations'])==1)
 with SessionLocal.begin() as db:
  note=db.get(Note,nid);note.version=2
 check('STALE_PROVENANCE_REJECT',rep,message_json(row)['content']['answer']!=literal)
 # Even a model that relabels a stale personal fact as general cannot release it.
 e.retrieval_status='retrieved';e.items['S1']={'note_id':internal,'note_version':1,'title':'预算','quote':'预算3200元','source_field':'body','start_offset':0,'end_offset':8};e.active_ids=['S1']
 e.verified=lambda text:[]
 verifier=SimpleNamespace(invoke=lambda *a,**k:SimpleNamespace(content=json.dumps({'segments':[{'text':'笔记预算3200元','basis':'general','source_refs':[],'supported':True}]})))
 answer,refs=guard_answer(verifier,e,'笔记预算3200元',[],'依据我的笔记回答预算')
 check('UNVERIFIED_NOTE_NO_GENERAL_ESCAPE',rep,'3200' not in answer and not refs)
 # A failing verifier is an explicit service failure, not a fabricated source judgement.
 class BrokenVerifier:
  def invoke(self,*args,**kwargs):raise ValueError('synthetic_provider_parser_failure')
 try:
  guard_answer(BrokenVerifier(),e,'笔记预算3200元',[],'依据我的笔记回答预算');passed=False
 except HTTPException as error:passed=error.status_code==502 and '核验服务' in error.detail
 check('VERIFIER_FAILURE_CONTRACT',rep,passed)
 e.verified=lambda text:[{'citation_id':'S1','note_id':internal,'title':'预算','quote':'预算3200元'}]
 class CorrectableVerifier:
  def __init__(self,always_invalid=False):self.calls=0;self.always_invalid=always_invalid
  def invoke(self,*args,**kwargs):
   self.calls+=1
   content={'segments':[{'text':'预算3200元','basis':'note','source_refs':['S1'],'supported':False}]} if self.calls==1 or self.always_invalid else {'segments':[{'text':'预算3200元','basis':'note','source_refs':['S1'],'supported':True},{'text':'总结','basis':'interaction','supported':True}]}
   return SimpleNamespace(content=json.dumps(content))
 correctable=CorrectableVerifier();fixed,refs=guard_answer(correctable,e,'预算3200元[S1]',[],'依据我的笔记回答预算')
 check('BOUNDED_VERIFIER_CORRECTION',rep,correctable.calls==2 and '3200' in fixed and len(refs)==1)
 invalid=CorrectableVerifier(True);blocked,refs=guard_answer(invalid,e,'预算9999元[S1]',[],'依据我的笔记回答预算')
 check('VERIFIER_CORRECTION_FAIL_CLOSED',rep,invalid.calls==2 and '9999' not in blocked and not refs)
print(json.dumps({'executions':len(records),'passed':sum(r['passed'] for r in records),'failed':sum(not r['passed'] for r in records)}))
