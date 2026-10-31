"""Recording helpers for this frozen baseline; does not implement legal decisions."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

REPO = Path(__file__).resolve().parents[3]
HEADER = '【環境說明】本 prompt 提到的 Read、Grep、Glob 工具,在你的環境中分別對應讀取檔案、rg 搜尋、列出檔案;語意與規則不變。'

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def output(case_id):
    return REPO / 'docs/live-run-records' / ('codex-' + case_id)

def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def manifest(case_id):
    return json.loads((output(case_id) / 'run_manifest.json').read_text(encoding='utf-8'))

def cli(case_id, label, args):
    out = output(case_id)
    env = dict(os.environ, LEGALDEBATE_DB_URL='sqlite:///database/codex_runs.db', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    started = now()
    result = subprocess.run([sys.executable, 'main.py', *args], cwd=REPO, env=env, capture_output=True)
    (out/'commands'/f'{label}.stdout.txt').write_bytes(result.stdout)
    (out/'commands'/f'{label}.stderr.txt').write_bytes(result.stderr)
    record = {'label':label, 'argv':[sys.executable,'main.py',*args], 'env':{'LEGALDEBATE_DB_URL':env['LEGALDEBATE_DB_URL']}, 'started_at':started, 'ended_at':now(), 'exit_code':result.returncode}
    state = manifest(case_id)
    state['commands'].append(record)
    if result.returncode:
        state['status'] = 'stopped_command_error'
    save_json(out/'run_manifest.json',state)
    print(result.stdout.decode('utf-8', errors='replace'))
    if result.stderr:
        print(result.stderr.decode('utf-8', errors='replace'), file=sys.stderr)
    return result.returncode

def prepare(case_id, name, template_name, values, inputs):
    out = output(case_id)
    call = out/'calls'/name
    if (call/'call_manifest.json').exists():
        raise RuntimeError('Call already prepared')
    call.mkdir(exist_ok=True)
    runtime = call/'workspace'
    runtime.mkdir(exist_ok=True)
    for local_name, source in inputs.items():
        target = runtime/local_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source,target)
    # Materialize the unchanged corpus; no junction privileges are needed.
    corpus_copy = runtime/'corpus'
    if corpus_copy.exists() or corpus_copy.is_junction() or corpus_copy.is_symlink():
        raise RuntimeError('Existing corpus target; inspect before writing')
    shutil.copytree(REPO/'corpus',corpus_copy)
    template = (out/'frozen_templates'/template_name).read_bytes().decode('utf-8')
    prompt = template
    for key, value in values.items():
        prompt = prompt.replace('{'+key+'}',str(value))
    import re
    unresolved = re.findall(r'\{[A-Z][A-Z0-9_]*\}',prompt)
    if unresolved:
        raise ValueError(unresolved)
    prompt = HEADER+'\n'+prompt
    if 'legaldebate_holdout' in prompt:
        raise ValueError('Forbidden path token in prompt')
    (call/'prompt.txt').write_text(prompt,encoding='utf-8',newline='\n')
    # Only an allowlist is exposed; no withheld-data path is placed in model context.
    profile = {':root':'deny', ':minimal':'read', runtime.as_posix():'read', (REPO/'corpus').as_posix():'read', Path(sys.executable).parent.as_posix():'read', 'C:/Users/berto/AppData/Local/OpenAI/Codex/bin':'read', 'C:/Users/berto/.cache/codex-runtimes/codex-primary-runtime/dependencies':'read', 'C:/Users/berto/AppData/Local/Microsoft/WinGet/Links':'read'}
    rg_target=Path('C:/Users/berto/AppData/Local/Microsoft/WinGet/Links/rg.exe').resolve()
    profile[rg_target.parent.as_posix()]='read'
    save_json(call/'permission_config.json',{'filesystem':profile,'network_enabled':False,'windows_sandbox':'mxc'})
    record = {'name':name,'template':template_name,'values':values,'template_sha256':hashlib.sha256((out/'frozen_templates'/template_name).read_bytes()).hexdigest(),'prompt_sha256':hashlib.sha256(prompt.encode('utf-8')).hexdigest(),'input_sha256':{local:hashlib.sha256(Path(src).read_bytes()).hexdigest() for local,src in inputs.items()},'status':'prepared'}
    save_json(call/'call_manifest.json',record)
    return call

def permissions(call):
    data=json.loads((call/'permission_config.json').read_text(encoding='utf-8'))
    # TOML inline tables use '=' rather than JSON ':'.
    fs='{'+', '.join(json.dumps(k)+' = '+json.dumps(v) for k,v in data['filesystem'].items())+'}'
    backend=data.get('windows_sandbox','mxc')
    args=['-c','windows.sandbox='+json.dumps(backend),'-c','default_permissions="legaldebate-role"','-c','permissions.legaldebate-role.filesystem='+fs]
    if data.get('network_enabled',False):
        domains='{'+', '.join(json.dumps(k)+' = "allow"' for k in data['allowed_domains'])+'}'
        args.extend(['-c','features.network_proxy=true','-c','permissions.legaldebate-role.network.enabled=true','-c','permissions.legaldebate-role.network.allow_local_binding=true','-c','permissions.legaldebate-role.network.allow_upstream_proxy=false','-c','permissions.legaldebate-role.network.domains='+domains])
    else:
        args.extend(['-c','permissions.legaldebate-role.network.enabled=false'])
    return args

def run(case_id, name):
    call=output(case_id)/'calls'/name
    record=json.loads((call/'call_manifest.json').read_text(encoding='utf-8'))
    if record['status'] != 'prepared':
        raise RuntimeError('Call already attempted')
    if record.get('awaiting_user_network_clarification'):
        raise RuntimeError('Step8 network-scope clarification is still pending')
    cwd=Path(record.get('working_directory',str(call/'workspace')))
    env_flags=[]
    if record.get('disable_nested_agents'):
        env_flags.extend(['-c','agents.enabled=false'])
    if record.get('shell_environment_policy_set'):
        env_flags.extend(['-c','shell_environment_policy.inherit="core"'])
        for key,value in record['shell_environment_policy_set'].items():
            env_flags.extend(['-c','shell_environment_policy.set.'+key+'='+json.dumps(value)])
    args=['codex','exec','--ignore-user-config','--ephemeral','--skip-git-repo-check','--json','--color','never','-C',str(cwd),'-m','gpt-6-astra','-c','model_reasoning_effort="ultra"','-c','web_search="disabled"','-c','approval_policy="never"','-c','project_doc_max_bytes=0','-c','features.multi_agent=false','-c','features.apps=false','-c','features.plugins=false',*env_flags,*permissions(call),'-o',str(call/'last_message.txt'),'-']
    child_env=dict(os.environ,LEGALDEBATE_DB_URL='sqlite:///database/codex_runs.db',PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
    # Apply startup-sensitive opt-outs before Codex can launch a shell.
    child_env.update(record.get('shell_environment_policy_set',{}))
    record.update({'argv':args,'started_at':now(),'status':'running','explicit_host_environment':{k:child_env[k] for k in ['LEGALDEBATE_DB_URL','PYTHONIOENCODING','PYTHONDONTWRITEBYTECODE','POWERSHELL_TELEMETRY_OPTOUT'] if k in child_env}})
    save_json(call/'call_manifest.json',record)
    with (call/'stream.jsonl').open('wb') as stdout, (call/'stderr.log').open('wb') as stderr:
        result=subprocess.run(args,input=(call/'prompt.txt').read_bytes(),stdout=stdout,stderr=stderr,cwd=cwd,env=child_env)
    record.update({'ended_at':now(),'exit_code':result.returncode,'status':'process_finished'})
    save_json(call/'call_manifest.json',record)
    # Each call owns its manifest. The controller merges them after both sides finish.
    print(json.dumps({'case_id':case_id,'call':name,'exit_code':result.returncode,'last_message_exists':(call/'last_message.txt').exists()}))
    return result.returncode

def collect_stage(case_id, stage, calls):
    """Validate both raw final JSON messages before creating either DB payload."""
    out=output(case_id)
    values={}
    required=['side','position','argument','cited_statutes','cited_precedents']
    if stage in [2,3]:
        required.append('falsifier')
    for side,name in calls.items():
        call=out/'calls'/name
        meta=json.loads((call/'call_manifest.json').read_text(encoding='utf-8'))
        if meta.get('status') != 'process_finished' or meta.get('exit_code') != 0:
            raise ValueError(name+': process has not completed successfully')
        raw=(call/'last_message.txt').read_text(encoding='utf-8')
        data=json.loads(raw)
        if not isinstance(data,dict) or any(k not in data for k in required):
            raise ValueError(name+': incomplete final JSON fields')
        if data['side'] != side:
            raise ValueError(name+': wrong side')
        for key in ['position','argument']+(['falsifier'] if stage in [2,3] else []):
            if not isinstance(data[key],str) or not data[key].strip():
                raise ValueError(name+': invalid '+key)
        for key in ['cited_statutes','cited_precedents']:
            if not isinstance(data[key],list) or any(not isinstance(c,str) for c in data[key]):
                raise ValueError(name+': invalid '+key)
        values[side]=(name,data)
    for side,(name,data) in values.items():
        letter='p' if side=='plaintiff' else 'd'
        payload=dict(data,case_id=case_id,stage=stage,model_id='gpt-6-astra')
        path=out/f'{letter}_s{stage}.json'
        if path.exists():
            if json.loads(path.read_text(encoding='utf-8')) != payload:
                raise ValueError('Refusing to overwrite '+str(path))
        else:
            save_json(path,payload)
        call=out/'calls'/name
        meta=json.loads((call/'call_manifest.json').read_text(encoding='utf-8'))
        meta['classification']='complete_json_selected'
        meta['selected_output']=path.name
        save_json(call/'call_manifest.json',meta)
    return {side:data for side,(_,data) in values.items()}

if __name__ == '__main__':
    if sys.argv[1]=='cli':
        raise SystemExit(cli(sys.argv[2],sys.argv[3],sys.argv[4:]))
    if sys.argv[1]=='run':
        raise SystemExit(run(sys.argv[2],sys.argv[3]))
