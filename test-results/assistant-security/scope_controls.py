"""Three deterministic checks of natural update wording and nearby allowed wording."""
import json
from pathlib import Path
from runner import load_app

a,*_=load_app();rows=[]
for rep in range(1,4):
 for label,q,expected in [('O54','把我的《旅行计划》笔记正文中的预算3200元改为3500元，其余保持。',[False,True]),('normal-update','修改我的《旅行计划》笔记，把预算3200元替换为3500元，其余正文保持。',[False,True]),('normal-create','新建一篇笔记，标题《练习记录》，正文为“今天学习20分钟”。',[True,False]),('normal-no-write','只解释知识管理，不检索、不保存。',[False,False])]:
  scope=list(a.explicit_note_write_scopes(q));rows.append({'case':label,'rep':rep,'question':q,'expected':expected,'scope':scope,'pass':scope==expected})
Path(__file__).with_name('scope-controls.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2));print(json.dumps({'probes':len(rows),'natural_update_rejected':sum(r['case']=='O54' and not r['pass'] for r in rows)}))
