"""Immutable version, sequential batches, original evidence retained."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
root=Path(__file__).parent
api=Path('/tmp/assistant-remediation/api')
manifest=json.loads((root/'freeze-manifest.json').read_text())
for name,digest in manifest['source_sha256'].items():
 if name.startswith('api/'):
  assert hashlib.sha256((api/name.removeprefix('api/')).read_bytes()).hexdigest()==digest
phases=[
 ['--output','frozen-results.jsonl'],
 ['--ids',(root/'supplement-ids.txt').read_text().strip(),'--repeat-count','2','--output','acceptance-supplement-results.jsonl'],
 ['--cases-file','extra-cases.json','--repeat-count','3','--output','acceptance-extra-results.jsonl'],
 ['--ids','S020,S140','--repeat-count','3','--output','provider-recovery-results.jsonl'],
]
records=[]
for args in phases:
 code=subprocess.call([sys.executable,str(root/'launch_model.py'),*args])
 records.append({'arguments':args,'exit_code':code})
 (root/'acceptance-status.json').write_text(json.dumps(records,indent=2))
 if code:raise SystemExit(code)
env=os.environ.copy();env['PYTHONPATH']=str(api);env['DATABASE_URL']='postgresql+psycopg://security_test:SecurityTestOnly123@pkm-assistant-security-db:5432/assistant_security'
for script,output in [('history_validation.py','history-results.json')]:
 result=subprocess.run([sys.executable,str(root/script)],env=env,cwd=api,capture_output=True,text=True,timeout=480)
 records.append({'script':script,'exit_code':result.returncode})
 (root/'acceptance-status.json').write_text(json.dumps(records,indent=2))
 if result.returncode:
  (root/(script+'.failure.txt')).write_text(result.stderr[-4000:])
 else:
  (root/output).write_text(result.stdout.strip().splitlines()[-1]+'\n')
print(json.dumps({'phases_complete':True,'checks':records}),flush=True)
