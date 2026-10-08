"""Meaningful guard checks for the test harness itself, not app behavior tests."""
import json
from unittest.mock import patch
from runner import IDS, USER, Store, capture_tools, fixture_context, load_app

a,conv,tracing,m3,factory=load_app()
cases=json.loads(__import__('pathlib').Path(__file__).with_name('cases.json').read_text())
assert len(cases)==200
assert sum(c['repeats'] for c in cases)==280
assert sum(c['id'].startswith('O') for c in cases)==60
store=Store({'fixture':'two'})
with fixture_context(a,m3,store,None):
    tools=capture_tools(a,store)
    assert {'create_personal_note','update_personal_note','fetch_external_link'}<=tools.keys()
    # All three paths must stay in memory even while using original tools.
    created=json.loads(tools['create_personal_note'].invoke({'title':'安全测试','body_md':'合成资料'}))
    assert created['status']=='created' and len(store.effects)==1
    updated=json.loads(tools['update_personal_note'].invoke({'note_id':str(IDS[0]),'expected_version':1,'body_md':'合成修改'}))
    assert updated['status']=='updated' and store.effects[-1]['action']=='update'
    fetched=json.loads(tools['fetch_external_link'].invoke({'url':'https://fixture.example/article'}))
    assert fetched['status']=='ok'
    assert store.events[-1]['kind']=='network_attempt_intercepted'
    repeated=json.loads(tools['fetch_external_link'].invoke({'url':'https://fixture.example/article'}))
    assert repeated['error_code']=='already_attempted'
assert store.session().__class__.__name__=='MemorySession'
assert len(Store({'fixture':'empty'}).selected())==0
with patch.object(a,'create_agent',lambda **kw:{t.name for t in kw['tools']}):
    names=a.build_agent(None,a.Evidence(USER),'test',can_search=True)
    assert 'create_personal_note' not in names and 'update_personal_note' not in names
print(json.dumps({'catalog_checks':'passed','synthetic_create_update_fetch':'passed','default_tools_read_only':'passed'}))
