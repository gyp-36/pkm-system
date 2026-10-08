"""Disposable DB regression runner; stores exit status, not environment secrets."""
import hashlib,json,os,pathlib,subprocess,sys,time
assert os.environ['DATABASE_URL'].endswith('/assistant_security')
root=pathlib.Path(__file__).resolve().parent
records=[]
for module in ['scripts.verify_assistant_security','scripts.verify_assistant_network','scripts.contract_check','scripts.verify_m2','scripts.verify_conversations','scripts.verify_assistant_tracing']:
    command=[sys.executable,'-m',module]
    if module=='scripts.contract_check':command+=['--static']
    started=time.monotonic()
    result=subprocess.run(command,capture_output=True,text=True,timeout=180)
    record={'module':module,'exit_code':result.returncode,'duration_seconds':round(time.monotonic()-started,3),'stdout':result.stdout[-5000:],'stderr':result.stderr[-5000:]}
    records.append(record)
    print(json.dumps({'module':module,'exit_code':result.returncode}),flush=True)
(root/'deterministic-results.json').write_text(json.dumps({'mode':'real_routes_synthetic_db_controlled_model','results':records},ensure_ascii=False,indent=2))
sys.exit(int(any(r['exit_code']!=0 for r in records)))
