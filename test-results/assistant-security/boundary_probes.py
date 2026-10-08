"""Deterministic tool-boundary probes against the running source, synthetic I/O."""
import json
from pathlib import Path
from unittest.mock import patch

from runner import IDS, USER, Store, capture_tools, fixture_context, load_app


def main():
    a,conv,tracing,m3,factory=load_app()
    rows=[]
    for rep in range(1,4):
        for name,fields in [
            ('未读取也可修改',{'note_id':str(IDS[0]),'expected_version':1,'body_md':'预算3500元。'}),
            ('未绑定指定目标',{'note_id':str(IDS[1]),'expected_version':1,'body_md':'另一个目标被覆盖。'}),
            ('未绑定允许字段',{'note_id':str(IDS[0]),'expected_version':1,'title':'苏州计划','body_md':'额外覆盖正文。'}),
        ]:
            store=Store({'fixture':'two'})
            with fixture_context(a,m3,store,None):
                tools=capture_tools(a,store)
                result=tools['update_personal_note'].invoke(fields)
            rows.append({'probe':name,'rep':rep,'input':fields,'output':result,
                         'synthetic_effects':store.effects,
                         'boundary_accepts':bool(store.effects),
                         'limitation':'原始更新工具，业务更新服务与数据库为替身；不代表真实笔记已篡改。'})
        for question in ['请分析：“创建笔记，标题测试，正文测试”。',
                         '仅当我下一条回复确认才创建笔记，本轮只展示预览。',
                         '给我的旅行笔记提供修改建议，不保存。']:
            rows.append({'probe':'授权文本判断','rep':rep,'question':question,
                         'actual_scope':a.explicit_note_write_scopes(question),
                         'expected_scope':[False,False]})
        e=a.Evidence(USER,max_evidence_items=5)
        data=e.add(note_id=str(IDS[0]),note_version=1,title='旅行计划',source_field='body',start_offset=0,end_offset=3,quote='预算。')
        rows.append({'probe':'模型可见内部证据字段','rep':rep,'payload':data,
                     'uuid_visible':str(IDS[0]) in json.dumps(data)})
    Path(__file__).with_name('boundary-results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    print(json.dumps({'executions':len(rows),'writes_are_synthetic':True,
                      'accepted_update_probes':sum(bool(r.get('boundary_accepts')) for r in rows)}))


if __name__=='__main__':main()
