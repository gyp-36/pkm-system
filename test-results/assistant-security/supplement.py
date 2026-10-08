"""Wait for baseline completion, then retest suspected issues with benign controls.
Only one parent schedules model starts; this avoids overlapping the two suites.
"""
import json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
while True:
 p=ROOT/'results.jsonl'
 rows=[json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
 if len(rows)>=280:break
 time.sleep(5)
cases=json.loads((ROOT/'cases.json').read_text())
by={c['id']:c for c in cases}
manual={'O08','O21','O26','O28','O30','O33','O35','O41','O45','O54','O55','O58','S031','S035','S038','S040'}
controls={'O19','O27','O53','O60','S034','S036','S140'}
selected=manual|controls|{r['id'] for r in rows if by[r['id']]['repeats']==1 and any(i['code']!='marker_quoted' for i in r.get('issues',[]))}
selected={i for i in selected if by[i]['mode']!='probe' or any(r['issues'] for r in rows if r['id']==i)}
p=ROOT/'supplemental.jsonl'
if not p.exists():
 with p.open('w') as f:
  for r in rows:
   if r['id'] in selected and r['id'] not in {'O35','S040'}:
    r['seed_from_baseline']=True
    f.write(json.dumps(r,ensure_ascii=False)+'\n')
(ROOT/'supplement-plan.json').write_text(json.dumps({'suspected':sorted(selected-controls),'normal_controls':sorted(controls),'invalid_first_fixture':['O35'],'rerun_fault_with_trace':['S040'],'selected':sorted(selected)},ensure_ascii=False,indent=2))
print(json.dumps({'supplemental_ids':sorted(selected),'baseline_completed':len(rows)}),flush=True)
subprocess.run([sys.executable,str(ROOT/'runner.py'),'--ids',','.join(sorted(selected)),'--repeat-count','3','--output','supplemental.jsonl'],check=True)

subprocess.run([sys.executable,str(ROOT/'runner.py'),'--cases-file','extra-cases.json','--output','extra-results.jsonl'],check=True)
