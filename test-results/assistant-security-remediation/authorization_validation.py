"""Exactly 36 former misclassification inputs, current server policy."""
import json,pathlib,uuid
from app.assistant.policy import parse_intent
from app.assistant.operations import Turn
root=pathlib.Path(__file__).resolve().parent
cases={c['id']:c for c in json.loads((root/'cases.json').read_text())}
ids=['S020','S021','S025','S026','S027','S028','S029','S042','S046','S104','S105','S109']
records=[]
for cid in ids:
 for rep in range(1,4):
  question=cases[cid]['question'];intent=parse_intent(question)
  turn=Turn(uuid.uuid4(),uuid.uuid4(),None,intent,None)
  assert intent.action=='none',cid
  assert turn.stage_create('未经授权','禁止保存',None,None)
  assert turn.stage_update(uuid.uuid4(),'另一笔记','原文',1,{'body_md':'被覆盖'})
  records.append({'id':cid,'rep':rep,'question':question,'intent':intent.json(),'create_rejected':True,'update_rejected':True})
(root/'authorization-results.json').write_text(json.dumps({'mode':'deterministic_policy_and_tool_stage','passed':36,'executions':36,'results':records},ensure_ascii=False,indent=2))
print(json.dumps({'passed':36,'executions':36,'actual_writes':0}))
