"""Exercise original citation verification; all notes and IDs are synthetic."""
import json
from pathlib import Path
from runner import IDS,USER,Store,load_app,fixture_context,capture_tools

def main():
 a,conv,tracing,m3,factory=load_app();rows=[]
 for rep in range(1,4):
  for label,marker,version,quote,answer,expected in [
   ('正常支持','S1',1,'预算3200元。','预算3200元。[S1]',1),
   ('不存在编号','S99',1,'预算3200元。','预算3200元。[S99]',0),
   ('历史编号无本轮证据',None,1,'预算3200元。','预算9999元。[S1]',0),
   ('过期版本','S1',0,'预算3200元。','预算3200元。[S1]',0),
   ('引用片段篡改','S1',1,'预算9999元。','预算9999元。[S1]',0),
   ('来源不支持结论','S1',1,'预算3200元。','酒店已付款。[S1]',0),
  ]:
   store=Store({'fixture':'trip'});ev=a.Evidence(USER,max_evidence_items=5)
   with fixture_context(a,m3,store,None):
    if marker:ev.add(note_id=str(IDS[0]),note_version=version,title='旅行计划',source_field='body',start_offset=0,end_offset=len(quote),quote=quote)
    cites=ev.verified(answer)
   rows.append({'scenario':label,'rep':rep,'input':answer,'evidence_quote':quote if marker else None,'note_version':version,'expected_citations':expected,'actual_citations':len(cites),'pass':len(cites)==expected,'limitation':'原始引用核验，合成存储；验证位置/版本真实性，不保证语义支持结论。'})
  store=Store({'fixture':'trip'})
  with fixture_context(a,m3,store,None):
   tools=capture_tools(a,store);tools['read_personal_note'].invoke({'note_id':str(IDS[0])})
   result=tools['update_personal_note'].invoke({'note_id':str(IDS[0]),'expected_version':1,'title':'苏州计划'})
  rows.append({'scenario':'正常标题修改对照','rep':rep,'input':'读取后仅修改标题','output':result,'synthetic_effects':store.effects,'pass':store.effects[-1]['before']['body_md']==store.effects[-1]['after']['body_md']})
 Path(__file__).with_name('citation-results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
 print(json.dumps({'executions':len(rows),'unsupported_accepted':sum(r.get('scenario')=='来源不支持结论' and r['actual_citations']>0 for r in rows)}))
if __name__=='__main__':main()
