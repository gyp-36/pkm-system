"""Sequential continuation of the frozen run; no concurrent provider batches."""
import json, os, pathlib, subprocess, sys, time
ROOT = pathlib.Path(__file__).resolve().parent
while pathlib.Path('/proc/53290').exists():
    time.sleep(1)
manifest = json.loads((ROOT/'freeze-manifest.json').read_text())['source_sha256']
frozen = [json.loads(x) for x in (ROOT/'frozen-results.jsonl').read_text().splitlines() if x]
needs = {row['id'] for row in frozen if any(manifest.get('api/'+path) != digest for path, digest in row.get('source_fingerprints', {}).items())}
commands = [
    ['--ids', ','.join(sorted(needs)), '--output', 'frozen-version-rechecks.jsonl'],
    ['--ids', (ROOT/'final-supplement-ids.txt').read_text().strip(), '--repeat-count', '2', '--output', 'frozen-supplement-results.jsonl'],
    ['--cases-file', 'extra-cases.json', '--output', 'frozen-extra-results.jsonl'],
]
logs = []
for args in commands:
    status = subprocess.call([sys.executable, str(ROOT/'launch_model.py'), *args])
    logs.append({'arguments': args, 'exit_code': status})
    (ROOT/'post-validation-status.json').write_text(json.dumps(logs, ensure_ascii=False, indent=2))
    if status:
        print(json.dumps({'stopped': True, 'exit_code': status}), flush=True)
        sys.exit(status)
frozen = [json.loads(x) for x in (ROOT/'frozen-results.jsonl').read_text().splitlines() if x]
first = [json.loads(x) for x in (ROOT/'frozen-version-rechecks.jsonl').read_text().splitlines() if x]
ids = {x['id'] for x in first}
(ROOT/'pre-final-correction-results.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False)+'\n' for x in frozen if x['id'] in ids))
(ROOT/'frozen-results.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False)+'\n' for x in [x for x in frozen if x['id'] not in ids]+first))
print(json.dumps({'post_validation_complete':True,'frozen_rows':len(frozen),'version_rechecks':len(first)}),flush=True)
