"""Finish source consistency, then run real TCP integration serially."""
import json, os, pathlib, subprocess, sys, time
ROOT = pathlib.Path(__file__).resolve().parent
while pathlib.Path('/proc/54078').exists():
    time.sleep(1)
state = json.loads((ROOT/'post-validation-status.json').read_text())
if len(state) != 3 or any(row['exit_code'] for row in state):
    raise SystemExit('Prior model batch did not complete; no further provider calls started')
manifest = json.loads((ROOT/'freeze-manifest.json').read_text())['source_sha256']
frozen = [json.loads(x) for x in (ROOT/'frozen-results.jsonl').read_text().splitlines() if x]
needs = {row['id'] for row in frozen if any(manifest.get('api/'+path) != digest for path, digest in row.get('source_fingerprints', {}).items())}
if needs:
    status = subprocess.call([sys.executable,str(ROOT/'launch_model.py'),'--ids',','.join(sorted(needs)),'--output','frozen-final-gap-results.jsonl'])
    if status:
        raise SystemExit(status)
    repaired = [json.loads(x) for x in (ROOT/'frozen-final-gap-results.jsonl').read_text().splitlines() if x]
    ids = {row['id'] for row in repaired}
    (ROOT/'pre-final-gap-results.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in frozen if row['id'] in ids))
    (ROOT/'frozen-results.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in [row for row in frozen if row['id'] not in ids]+repaired))
env = os.environ.copy()
env['DATABASE_URL'] = 'postgresql+psycopg://security_test:SecurityTestOnly123@pkm-assistant-security-db:5432/assistant_security'
env['PYTHONPATH'] = '/tmp/assistant-remediation/api'
records = []
for script,out in [('http_validation.py','http-results.json'),('history_validation.py','history-results.json'),('commit_stream_validation.py','commit-stream-results.json')]:
    result = subprocess.run([sys.executable,str(ROOT/script)],env=env,cwd='/tmp/assistant-remediation/api',capture_output=True,text=True,timeout=480)
    record = {'script':script,'exit_code':result.returncode}
    if result.returncode:
        record['failure_type']='integration_script_failure'
        (ROOT/(script+'.failure.txt')).write_text(result.stderr[-4000:])
    else:
        # Script outputs contain only synthetic data and public model statuses.
        (ROOT/out).write_text(result.stdout.strip().splitlines()[-1]+'\n')
    records.append(record)
    print(json.dumps(record),flush=True)
    (ROOT/'final-integration-status.json').write_text(json.dumps(records,indent=2))
print(json.dumps({'final_validation_finished':True,'source_gap_cases':len(needs)}),flush=True)
