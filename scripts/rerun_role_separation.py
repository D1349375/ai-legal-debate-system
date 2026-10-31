"""一次性 real-case 重跑控制器；法律內容只由隔離角色產生。

沿用基準 run_control.py 的 Codex exec、檔案白名單與呼叫記錄方式。
此腳本不是產品的完整 pipeline；正式執行前須由外部完成獨立驗收。
"""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import uuid

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
MODEL = 'gpt-6-astra'
EFFORT = 'ultra'
SIDES = ('plaintiff', 'defendant')
CASE_IDS = ('real-2026-10-31-001', 'real-2026-10-31-002')
MAX_ATTEMPTS = 3  # 初次加兩次原角色修正；不得由 controller 改寫法律內容。
ENV_OPTOUTS = {'POWERSHELL_TELEMETRY_OPTOUT': '1', 'DOTNET_CLI_TELEMETRY_OPTOUT': '1',
               'POWERSHELL_UPDATECHECK': 'Off', 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'}
PLEADING_TEMPLATE = '''你是代理方書狀骨架撰寫角色，案件 {CASE_ID}。
只讀程式素材 {PLEADING_SOURCE_PATH}。以其中 claim_statement 與 asserted items 製作己方起訴前書狀骨架。
不得讀其他角色、原始案件或內部備註；不得預先回應對造抗辯；卷內未載的事不得補寫。
原告起訴狀不得含「被告主張、被告抗辯、被告自承、被告或將、本方、對造、Stage、輪次、前輪、法官訊問、訊問攻防」。
citations_used 只能選素材已 published 者，不能新增未查證引用；不足的引用留待律師核對。
金錢明細 claim_breakdown 每筆含 name/amount/basis/formula/item，item 為 asserted 且附輪次；金額未確認不得進聲明。
非金錢請求不換算新臺幣，保留已提供的請求原文；不得虛構計價日、市價或計算結果。
輸出嚴格 JSON：{"draft_text":"完整書狀骨架","citations_used":[],"claim_breakdown":[]}。
'''


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def convert_case(original):
    """只改既定輸入格式；source_note 留在 controller 的原始快照。"""
    if original.get('case_id') not in CASE_IDS:
        raise ValueError('此重跑腳本只接受已凍結的 real-001/002')
    amount = 974000 if original['case_id'].endswith('-001') else None
    converted = {key: original[key] for key in ('case_id', 'case_type', 'facts_summary', 'claims')}
    converted.update(represented_side='plaintiff', plaintiff_facts=original['facts_summary'],
                     defendant_facts='', uncontested_facts='', claim_amount=amount,
                     claims=original['claims'].replace('原起訴', '起訴'))
    return converted, {'facts_changed': False, 'facts_conversion': 'facts_summary 原文複製至 plaintiff_facts',
                       'claims_conversion': '僅將「原起訴」改為「起訴」',
                       'claim_amount_source': '原始 claims 明載新臺幣974,000元' if amount is not None else '非金錢比特幣請求，留空',
                       'source_note_excluded_from_roles': True}


def _safe_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,100}', value):
        raise ValueError('run/call 名稱只允許英數、連字號與底線')
    return value


def version_hints_for(arguments, citations):
    from engine.verify import citation_warning, parse_citation
    hints = {}
    for argument in arguments:
        for item in argument.get('items', []):
            for citation in item.get('citations', []):
                warning = citation_warning(citation, item)
                if warning and warning['status'] == 'version_unverified':
                    for candidate in citations:
                        if parse_citation(candidate) == parse_citation(citation):
                            hints[candidate] = item
    return hints


def validate_independent_checks(mechanical_results, payload, final_citations):
    """先驗完整批次再落地；獨立判斷不能洗掉版本或文件身分失敗。"""
    checks = payload.get('checks')
    if not isinstance(checks, list) or any(not isinstance(c, dict) for c in checks):
        raise ValueError('查證checks必須是物件陣列')
    by_citation = {r['citation_text']: r for r in mechanical_results}
    reported = [c.get('citation_text') for c in checks]
    if len(reported) != len(set(reported)):
        raise ValueError('獨立查證checks不得重複同一引用')
    if set(reported) != set(by_citation):
        raise ValueError('獨立查證checks須涵蓋清單每個引用，不能新增或省略')
    statuses = {'published', 'needs_explanation', 'unsupported_law', 'version_unverified', 'not_found',
                'ambiguous', 'network_error', 'unsupported', 'unparseable', 'doc_type_mismatch', 'quote_not_found',
                'analogy_required', 'document_identity_unverified', 'invalid_precedent_note', 'invalid_document_date'}
    for check in checks:
        mechanical = by_citation[check['citation_text']]
        if check.get('status') not in statuses or not str(check.get('reason') or '').strip():
            raise ValueError('每個查證結果須有合法status與非空reason')
        if check['status'] == 'published':
            if mechanical['status'] not in ('published', 'needs_explanation'):
                raise ValueError(f"{check['citation_text']} 機械查證 {mechanical['status']}，不能改標published")
            if check['citation_text'] in final_citations and any(check.get(k) is not True for k in ('existence', 'document_identity', 'supports_proposition')):
                raise ValueError('最後採用引用published須獨立核對存在、身分及命題支持皆true')
        elif mechanical['status'] in ('version_unverified', 'unsupported_law') and check['status'] != mechanical['status']:
            raise ValueError('歷史版本／不支援法規須保留引擎原狀態')
    return checks


class RerunController:
    def __init__(self, repo, case_id, run_id=None, *, resume=False):
        if case_id not in CASE_IDS:
            raise ValueError('未知的基準案件')
        self.repo = Path(repo).resolve()
        self.case_id = case_id
        self.run_id = _safe_name(run_id or datetime.datetime.now().strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
        self.out = self.repo / 'docs/live-run-records' / f'role-separation-{case_id}-{self.run_id}'
        self.resume = resume
        self.db_url = 'sqlite:///' + (self.out / 'controller/run.db').as_posix()
        self.lock = threading.RLock()

    def manifest(self):
        return load_json(self.out / 'run_manifest.json')

    def update(self, callback):
        with self.lock:
            state = self.manifest()
            callback(state)
            save_json(self.out / 'run_manifest.json', state)

    def source_hashes(self):
        names = ['main.py', 'database/schema.py', 'database/db.py', 'engine/role_protocol.py',
                 'engine/aggregate.py', 'engine/verify.py', 'engine/citation_review.py', 'scripts/rerun_role_separation.py']
        return {name: sha256(self.repo / name) for name in names if (self.repo / name).is_file()}

    def prepare(self):
        if self.resume:
            state = self.manifest()
            if state['case_id'] != self.case_id or state['source_sha256'] != self.source_hashes():
                raise ValueError('續跑的案件或程式雜湊不符；請另開新run，不能混用版本')
            return self.out
        self.out.mkdir(parents=True, exist_ok=False)
        for folder in ('controller', 'calls', 'commands', 'materials', 'artifacts', 'frozen_templates'):
            (self.out / folder).mkdir()
        (self.out / '.gitignore').write_text('shared_corpus/\n', encoding='utf-8')
        original_path = self.repo / 'data/cases' / (self.case_id + '.json')
        original = load_json(original_path)
        converted, conversion = convert_case(original)
        save_json(self.out / 'controller/original_case.json', original)
        save_json(self.out / 'controller/converted_case.json', converted)
        save_json(self.out / 'controller/conversion.json', conversion)
        skill = self.repo / '.claude/skills/legal-debate'
        shutil.copyfile(skill / 'SKILL.md', self.out / 'frozen_templates/SKILL.md')
        for path in (skill / 'templates').glob('*.txt'):
            shutil.copyfile(path, self.out / 'frozen_templates' / path.name)
        (self.out / 'frozen_templates/pleading_prompt.txt').write_text(PLEADING_TEMPLATE, encoding='utf-8')
        shutil.copytree(self.repo / 'corpus', self.out / 'shared_corpus')
        hashes = {('SKILL.md' if path.name == 'SKILL.md' else 'templates/' + path.name): sha256(path)
                  for path in (self.out / 'frozen_templates').iterdir() if path.is_file()}
        save_json(self.out / 'run_manifest.json', {'case_id': self.case_id, 'run_id': self.run_id,
            'created_at': now(), 'status': 'prepared', 'model': MODEL, 'reasoning_effort': EFFORT,
            'db_url': self.db_url, 'input_sha256': sha256(original_path), 'frozen_sha256': hashes,
            'source_sha256': self.source_hashes(), 'baseline_controller': 'docs/live-run-records/codex-real-2026-10-31-001/run_control.py',
            'conversion': conversion, 'commands': [], 'nodes': {}, 'controller_verification_attempts': [],
            'deviations': ['查證角色只回傳嚴格JSON，由controller存檔；不要求角色另寫輸出檔。',
                           '語料庫每run複製一次共用唯讀，各call另有獨立輸入workspace。']})
        return self.out

    def cli(self, label, args):
        with self.lock:
            number = len(self.manifest()['commands']) + 1
            name = f'{number:03d}-{_safe_name(label)}'
            record = {'label': label, 'argv': [sys.executable, 'main.py', *map(str, args)], 'started_at': now(), 'status': 'running'}
            self.update(lambda state: state['commands'].append(record))
        env = dict(os.environ, **ENV_OPTOUTS, LEGALDEBATE_DB_URL=self.db_url)
        result = subprocess.run(record['argv'], cwd=self.repo, env=env, capture_output=True)
        stdout, stderr = result.stdout.decode('utf-8', errors='replace'), result.stderr.decode('utf-8', errors='replace')
        (self.out / 'commands' / (name + '.stdout.txt')).write_text(stdout, encoding='utf-8')
        (self.out / 'commands' / (name + '.stderr.txt')).write_text(stderr, encoding='utf-8')
        def complete(state):
            state['commands'][number-1].update(status='finished', exit_code=result.returncode, ended_at=now(),
                                               stdout_file=f'commands/{name}.stdout.txt', stderr_file=f'commands/{name}.stderr.txt')
        self.update(complete)
        if result.returncode:
            raise ValueError(f'CLI {label} exit={result.returncode}\n{stderr or stdout}')
        return stdout

    def project(self, label, args):
        result = json.loads(self.cli(label, args))
        path = self.out / 'materials' / (label + '.json')
        save_json(path, result)
        return path

    def preflight(self):
        evidence = {'checked_at': now(), 'model_called': False, 'checks': [], 'passed': True}
        commands = [[sys.executable, '-c', 'import json,sqlalchemy,fastapi; print(json.dumps({"sqlalchemy":sqlalchemy.__version__,"fastapi":fastapi.__version__}))'],
                    [shutil.which('codex') or 'codex', '--version']]
        for index, argv in enumerate(commands):
            try:
                result = subprocess.run(argv, cwd=self.repo, capture_output=True, env=dict(os.environ, **ENV_OPTOUTS), timeout=30)
                check = {'argv': argv, 'exit_code': result.returncode,
                         'stdout': result.stdout.decode('utf-8', errors='replace'), 'stderr': result.stderr.decode('utf-8', errors='replace')}
            except (OSError, subprocess.TimeoutExpired) as error:
                check = {'argv': argv, 'exit_code': None, 'error': str(error)}
            evidence['checks'].append(check)
            evidence['passed'] = evidence['passed'] and check.get('exit_code') == 0
        try:
            self.cli('preflight-cli-help', ['--help'])
        except ValueError as error:
            evidence['passed'] = False
            evidence['cli_error'] = str(error)
        evidence['isolation'] = {'root_default': 'deny', 'network': False, 'nested_agents': False,
                                 'runtime_sandbox_smoke_test': '未呼叫模型，須以正式第一call記錄實測結果'}
        save_json(self.out / 'preflight.json', evidence)
        self.update(lambda state: state.update(status='preflight_passed' if evidence['passed'] else 'preflight_failed'))
        return evidence

    def prepare_call(self, name, template_name, values, inputs, feedback=None):
        _safe_name(name)
        material_root = (self.out / 'materials').resolve()
        for local, source in inputs.items():
            path = Path(source).resolve()
            if not path.is_relative_to(material_root) or Path(local).name != local:
                raise ValueError('角色輸入只允許 materials 下明確列出的單層檔名')
            if path.suffix == '.json' and '"source_note"' in path.read_text(encoding='utf-8'):
                raise ValueError('角色輸入不得含 source_note')
        call = self.out / 'calls' / name
        call.mkdir(exist_ok=False)
        runtime = call / 'workspace'
        runtime.mkdir()
        for local, source in inputs.items():
            shutil.copyfile(source, runtime / local)
        if feedback is not None:
            (runtime / 'previous_output.txt').write_text(feedback['raw'], encoding='utf-8')
            (runtime / 'validation_error.txt').write_text(feedback['error'], encoding='utf-8')
        template_path = self.out / 'frozen_templates' / template_name
        prompt = template_path.read_text(encoding='utf-8')
        for key, value in values.items():
            prompt = prompt.replace('{' + key + '}', str(value))
        unresolved = re.findall(r'\{[A-Z][A-Z0-9_]*\}', prompt)
        if unresolved:
            raise ValueError('未填範本欄位：' + ','.join(unresolved))
        prompt = '【環境】Read/Grep/Glob分別使用讀檔、rg搜尋及列檔。僅可讀本workspace列出檔案與指定唯讀corpus。\n' + prompt
        prompt += '\n只回傳嚴格JSON，無code fence。即使範本要求另存，最終JSON由controller原樣存檔，不必自己寫檔。不得啟動subagent、外部HTTP或存取未授權路徑。'
        if feedback is not None:
            prompt += '\n這是同一角色的修正回合。讀previous_output.txt原始輸出與validation_error.txt精確錯誤，只修正必要部分，完整重送JSON；controller未代寫或改寫法律內容。'
        (call / 'prompt.txt').write_text(prompt, encoding='utf-8')
        profile = {':root': 'deny', ':minimal': 'read', runtime.as_posix(): 'read',
                   (self.out / 'shared_corpus').as_posix(): 'read', Path(sys.executable).parent.as_posix(): 'read'}
        for executable in ('codex', 'rg'):
            found = shutil.which(executable)
            if found:
                profile[Path(found).resolve().parent.as_posix()] = 'read'
        runtime_dependencies = Path('C:/Users/berto/.cache/codex-runtimes/codex-primary-runtime/dependencies')
        if runtime_dependencies.is_dir():
            profile[runtime_dependencies.as_posix()] = 'read'
        save_json(call / 'permission_config.json', {'filesystem': profile, 'network_enabled': False, 'windows_sandbox': 'mxc'})
        save_json(call / 'call_manifest.json', {'name': name, 'status': 'prepared', 'disable_nested_agents': True,
            'template': template_name, 'template_sha256': sha256(template_path), 'prompt_sha256': sha256(call / 'prompt.txt'),
            'input_sha256': {local: sha256(source) for local, source in inputs.items()}, 'values': values})
        return call

    def model_command(self, call):
        permission = load_json(call / 'permission_config.json')
        filesystem = '{' + ', '.join(json.dumps(k) + ' = ' + json.dumps(v) for k, v in permission['filesystem'].items()) + '}'
        args = [shutil.which('codex') or 'codex', 'exec', '--ignore-user-config', '--ephemeral', '--skip-git-repo-check',
                '--json', '--color', 'never', '-C', str(call / 'workspace'), '-m', MODEL,
                '-c', f'model_reasoning_effort="{EFFORT}"', '-c', 'web_search="disabled"', '-c', 'approval_policy="never"',
                '-c', 'project_doc_max_bytes=0', '-c', 'agents.enabled=false', '-c', 'features.multi_agent=false',
                '-c', 'features.apps=false', '-c', 'features.plugins=false', '-c', 'windows.sandbox="mxc"',
                '-c', 'default_permissions="legaldebate-role"', '-c', 'permissions.legaldebate-role.filesystem=' + filesystem,
                '-c', 'permissions.legaldebate-role.network.enabled=false', '-c', 'shell_environment_policy.inherit="core"']
        for key, value in ENV_OPTOUTS.items():
            args += ['-c', 'shell_environment_policy.set.' + key + '=' + json.dumps(value)]
        return args + ['-o', str(call / 'last_message.txt'), '-']

    def run_model(self, call):
        record = load_json(call / 'call_manifest.json')
        argv = self.model_command(call)
        record.update(status='running', started_at=now(), argv=argv)
        save_json(call / 'call_manifest.json', record)
        # 模型workspace沒有DB權限；也不把controller DB路徑放進角色環境。
        env = dict(os.environ, **ENV_OPTOUTS)
        env.pop('LEGALDEBATE_DB_URL', None)
        with (call / 'stream.jsonl').open('wb') as stdout, (call / 'stderr.log').open('wb') as stderr:
            result = subprocess.run(argv, input=(call / 'prompt.txt').read_bytes(), cwd=call / 'workspace', env=env,
                                    stdout=stdout, stderr=stderr)
        record.update(status='process_finished', ended_at=now(), exit_code=result.returncode)
        save_json(call / 'call_manifest.json', record)
        return result.returncode

    def execute_node(self, name, template, values, inputs, commit):
        node = self.manifest()['nodes'].get(name, {'attempts': [], 'status': 'pending'})
        if node['status'] == 'succeeded':
            return load_json(self.out / node['selected_output'])
        feedback = None
        if node['attempts']:
            last = node['attempts'][-1]
            feedback = {'raw': (self.out / last['raw_file']).read_text(encoding='utf-8') if last.get('raw_file') else '',
                        'error': last.get('error', '上次呼叫中斷，請完整重送原角色JSON')}
        for attempt in range(len(node['attempts']) + 1, MAX_ATTEMPTS + 1):
            call = self.prepare_call(f'{name}-attempt-{attempt}', template, values, inputs, feedback)
            entry = {'attempt': attempt, 'call': call.relative_to(self.out).as_posix(), 'started_at': now()}
            node['attempts'].append(entry)
            node['status'] = 'running'
            self.update(lambda state: state['nodes'].__setitem__(name, node))
            raw = ''
            try:
                exit_code = self.run_model(call)
                output = call / 'last_message.txt'
                if output.exists():
                    raw = output.read_text(encoding='utf-8')
                    entry['raw_file'] = output.relative_to(self.out).as_posix()
                if exit_code:
                    error = (call / 'stderr.log').read_text(encoding='utf-8') if (call / 'stderr.log').exists() else ''
                    raise ValueError(f'角色程序退出碼 {exit_code}\n{error}')
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError('角色最終輸出必須為JSON物件')
                commit(payload, attempt)
                selected = self.out / 'artifacts' / (name + '.json')
                save_json(selected, payload)
                node.update(status='succeeded', selected_output=selected.relative_to(self.out).as_posix(), ended_at=now())
                entry.update(status='accepted', ended_at=now())
                self.update(lambda state: state['nodes'].__setitem__(name, node))
                return payload
            except (ValueError, KeyError, TypeError) as error:
                feedback = {'raw': raw, 'error': str(error)}
                entry.update(status='rejected', error=str(error), ended_at=now())
                node['status'] = 'failed'
                self.update(lambda state: state['nodes'].__setitem__(name, node))
        raise RuntimeError(f'{name} 已達 {MAX_ATTEMPTS} 次呼叫上限，保留原輸出與驗證錯誤；需先修正阻礙再另開run')

    def _material(self, name, value):
        path = self.out / 'materials' / (name + '.json')
        save_json(path, value)
        return path

    def _base_values(self):
        return {'CASE_ID': self.case_id, 'STATUTES_DIR': (self.out / 'shared_corpus/statutes').as_posix(),
                'JUDGMENTS_DIR': (self.out / 'shared_corpus/judgments').as_posix()}

    def _stage(self, stage):
        from engine.stance_rag import build_stance_terms
        case_type = load_json(self.out / 'controller/converted_case.json')['case_type']
        jobs = []
        for side in SIDES:
            other = 'defendant' if side == 'plaintiff' else 'plaintiff'
            name = f'{side}_s{stage}'
            role = self.project(name + '-role', ['role-view', '--case-id', self.case_id, '--role', side])
            values = dict(self._base_values(), SIDE=side, SIDE_LABEL='原告方' if side == 'plaintiff' else '被告方',
                          CASE_FACTS_PATH='role.json', PROCEDURAL_ISSUES_PATH='procedural.json',
                          STANCE_TERMS='、'.join(build_stance_terms(side, case_type)))
            inputs = {'role.json': role, 'procedural.json': self.out / 'materials/procedural.json'}
            if stage > 1:
                own = load_json(self.out / 'artifacts' / f'{side}_s{stage-1}.json')
                inputs['own_previous.json'] = self._material(name + '-own-previous', own)
                inputs['opponent_summary.json'] = self.project(name + '-opponent-summary',
                    ['summary', '--case-id', self.case_id, '--side', other, '--stage', str(stage-1)])
                values.update({f'OWN_STAGE{stage-1}_JSON_PATH': 'own_previous.json',
                               f'OPPONENT_STAGE{stage-1}_SUMMARY_PATH': 'opponent_summary.json'})
            if stage == 2:
                judge = load_json(self.out / 'artifacts/judge_questions.json')
                questions = {'questions': [q for q in judge['questions'] if q['target_side'] == side]}
                if side == 'plaintiff':
                    prep = self.project(name + '-prep', ['prep-list', '--case-id', self.case_id, '--role', side])
                    questions['prep_items'] = load_json(prep)['prep_items']
                inputs['questions.json'] = self._material(name + '-questions', questions)
                values['JUDGE_QUESTIONS_PATH'] = 'questions.json'
            def commit(payload, attempt, side=side):
                # 只做唯讀檢驗；兩方完整有效JSON收齊之前，任何一方都不能落地。
                self.validate_stage_payload(payload, side, stage)
            jobs.append((name, values, inputs, commit))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.execute_node, name, f'stage{stage}_prompt.txt', values, inputs, commit)
                       for name, values, inputs, commit in jobs]
            for future in futures:
                future.result()
        self.land_stage_pair(stage)

    def validate_stage_payload(self, payload, side, stage):
        from database.db import get_session
        from engine.role_protocol import case_row, validate_argument
        if payload.get('side') != side:
            raise ValueError(f'side 必須為 {side}')
        for key in ('cited_statutes', 'cited_precedents'):
            if not isinstance(payload.get(key), list) or any(not isinstance(c, str) for c in payload[key]):
                raise ValueError(key + ' 必須是字串陣列')
        if side == 'plaintiff' and payload.get('falsifier'):
            raise ValueError('代理方falsifier必須留空；update_conditions只可進internal_notes')
        data = copy.deepcopy(dict(payload, case_id=self.case_id, stage=stage, model_id=MODEL))
        with get_session(self.db_url) as session:
            return validate_argument(session, case_row(session, self.case_id), side, stage,
                                     data.get('position'), data.get('argument'), data)

    def land_stage_pair(self, stage):
        from database.db import get_session
        from database.schema import DebateArgument
        selected = {side: load_json(self.out / 'artifacts' / f'{side}_s{stage}.json') for side in SIDES}
        # 續跑同樣先驗兩方；選定JSON與不可變的資料庫紀錄均不改寫。
        canonical = {side: self.validate_stage_payload(payload, side, stage) for side, payload in selected.items()}
        for side in SIDES:
            name = f'{side}_s{stage}'
            with get_session(self.db_url) as session:
                existing = session.query(DebateArgument).filter_by(case_id=self.case_id, side=side, stage=stage).one_or_none()
                if existing is not None:
                    if json.loads(existing.structured_json) != canonical[side]:
                        raise ValueError(f'{name} 已落地內容與選定JSON不符，不得覆寫')
                    self.update(lambda state: state.setdefault('stage_landings', {}).__setitem__(name, 'existing_identical'))
                    continue
            path = self._material(name + '-landing', dict(selected[side], case_id=self.case_id, stage=stage, model_id=MODEL))
            self.cli(name + '-record', ['record', '--json', path])
            self.update(lambda state: state.setdefault('stage_landings', {}).__setitem__(name, 'recorded'))

    def _judge_questions(self):
        role = self.project('judge-s1-role', ['role-view', '--case-id', self.case_id, '--role', 'judge'])
        inputs = {'judge_role.json': role, 'public_stage1.json': role, 'procedural.json': self.out / 'materials/procedural.json'}
        values = dict(self._base_values(), CASE_FACTS_PATH='judge_role.json', STAGE1_JSON_PATH='public_stage1.json', PROCEDURAL_ISSUES_PATH='procedural.json')
        def commit(payload, attempt):
            path = self._material(f'judge-questions-landing-{attempt}', dict(payload, case_id=self.case_id))
            self.cli(f'judge-questions-record-{attempt}', ['record', '--json', path])
        self.execute_node('judge_questions', 'judge_question_prompt.txt', values, inputs, commit)

    def _verify(self, label, final_payload):
        from database.db import get_session, record_case_citation_check, upsert_citation
        from engine.verify import parse_citation, verify_citations
        public = load_json(self.project(label + '-public', ['role-view', '--case-id', self.case_id, '--role', 'judge']))
        notes, citations = {}, []
        arguments = public['arguments'] + [final_payload]
        for argument in arguments:
            citations.extend(argument.get('cited_statutes', []) + argument.get('cited_precedents', []) + argument.get('citations_used', []))
            for note in argument.get('precedent_notes', []):
                notes[note['citation']] = note
        citations = list(dict.fromkeys(citations))
        version_hints = version_hints_for(arguments, citations)
        results = []
        for citation in citations:
            # 單次人工controller重試，與延後的引擎自動retry明確分開記錄。
            for attempt in (1, 2):
                result = verify_citations([citation], precedent_notes=list(notes.values()), version_hints=version_hints)[0]
                if result['status'] == 'published' and parse_citation(citation)['type'] == 'judgment' and not result.get('precedent_note'):
                    result.update(status='document_identity_unverified', reason='缺precedent_notes，僅字號存在不能證明文種、案由與摘句')
                self.update(lambda state: state['controller_verification_attempts'].append(
                    {'label': label, 'citation_text': citation, 'attempt': attempt, 'status': result['status'], 'checked_at': now()}))
                with get_session(self.db_url) as session:
                    record_case_citation_check(session, self.case_id, result, f'{self.run_id}-{label}-engine-{attempt}')
                    if result['status'] == 'published':
                        upsert_citation(session, citation_text=citation, source_type=result['source_type'], status='published', primary_source_url=result.get('primary_source_url'))
                if result['status'] != 'network_error':
                    break
            results.append(result)
        # 原文路徑轉到同run唯讀corpus；不把controller或repo其他路徑暴露給角色。
        for result in results:
            source = result.get('source_file')
            if source:
                source_path = Path(source).resolve()
                if source_path.is_relative_to((self.repo / 'corpus').resolve()):
                    result['source_file'] = (self.out / 'shared_corpus' / source_path.relative_to((self.repo / 'corpus').resolve())).as_posix()
            result.pop('full_text', None)
        data = {'case_id': self.case_id, 'mechanical_checks': results, 'final_citations': final_payload.get('citations_used', []),
                'precedent_notes': list(notes.values()), 'version_hints': version_hints, 'final_propositions': final_payload}
        path = self._material(label + '-verification-input', data)
        values = dict(self._base_values(), VERIFICATION_INPUT_PATH='verification_input.json', OUTPUT_PATH='output.json')
        def commit(payload, attempt):
            checks = validate_independent_checks(results, payload, final_payload.get('citations_used', []))
            for check in checks:
                with get_session(self.db_url) as session:
                    record_case_citation_check(session, self.case_id, check, f'{self.run_id}-{label}-independent-{attempt}')
        verification = self.execute_node(label + '_verification', 'verify_prompt.txt', values, {'verification_input.json': path}, commit)
        return {c['citation_text']: c for c in verification['checks']}

    def _verdict(self):
        role = self.project('judge-final-role', ['role-view', '--case-id', self.case_id, '--role', 'judge'])
        data = load_json(role)
        anchors = self._material('judge-anchors', data['anchors'])
        values = dict(self._base_values(), CASE_FACTS_PATH='judge_role.json', ALL_STAGES_JSON_PATH='public_stages.json', MECHANICAL_ANCHOR_JSON_PATH='anchors.json')
        inputs = {'judge_role.json': role, 'public_stages.json': role, 'anchors.json': anchors}
        def commit(payload, attempt):
            self._verify(f'verdict-{attempt}', payload)
            path = self._material(f'verdict-landing-{attempt}', payload)
            self.cli(f'verdict-record-{attempt}', ['verdict', '--case-id', self.case_id, '--json', path])
        self.execute_node('verdict', 'verdict_prompt.txt', values, inputs, commit)

    def _pleading(self):
        source = self.project('pleading-source', ['pleading-source', '--case-id', self.case_id, '--side', 'plaintiff'])
        values = dict(self._base_values(), PLEADING_SOURCE_PATH='pleading_source.json')
        def commit(payload, attempt):
            if not isinstance(payload.get('draft_text'), str) or not payload['draft_text'].strip():
                raise ValueError('draft_text 必須是非空書狀字串')
            checks = self._verify(f'pleading-{attempt}', payload)
            bad = [c for c in payload.get('citations_used', []) if checks.get(c, {}).get('status') != 'published']
            if bad:
                raise ValueError('以下書狀引用未published，須由原writer改選已核引用或列律師附註：' + ','.join(bad))
            draft = self.out / 'artifacts' / f'pleading-draft-{attempt}.txt'
            draft.write_text(payload['draft_text'], encoding='utf-8')
            citations = self._material(f'pleading-citations-{attempt}', payload.get('citations_used', []))
            breakdown = self._material(f'pleading-breakdown-{attempt}', payload.get('claim_breakdown', []))
            self.cli(f'pleading-record-{attempt}', ['pleading', '--case-id', self.case_id, '--side', 'plaintiff',
                '--draft-file', draft, '--citations', citations, '--claim-breakdown', breakdown])
        self.execute_node('pleading', 'pleading_prompt.txt', values, {'pleading_source.json': source}, commit)

    def run(self):
        if not self.preflight()['passed']:
            raise RuntimeError('環境預檢未通過，未啟動模型')
        state = self.manifest()
        if not state.get('case_recorded'):
            self.cli('case-record', ['case', '--json', self.out / 'controller/converted_case.json'])
            self.update(lambda s: s.update(case_recorded=True))
        self.project('procedural', ['issues', '--case-id', self.case_id])
        self.update(lambda s: s.update(status='running'))
        try:
            self._stage(1)
            self._judge_questions()
            self._stage(2)
            self._stage(3)
            self.project('aggregate', ['finalize', '--case-id', self.case_id])
            self._verdict()
            self._pleading()
            report = self.project('report', ['report', '--case-id', self.case_id, '--json'])
            (self.out / 'report.txt').write_text(self.cli('report-text', ['report', '--case-id', self.case_id]), encoding='utf-8')
            save_json(self.out / 'metrics.json', self.metrics(load_json(report)))
            self.update(lambda s: s.update(status='completed', ended_at=now(), holdout_review='待獨立驗證agent於角色全完成後比對'))
        except Exception as error:
            self.update(lambda s: s.update(status='failed', ended_at=now(), error=str(error)))
            raise

    def metrics(self, report):
        state = self.manifest()
        selected = {name: load_json(self.out / node['selected_output']) for name, node in state['nodes'].items()
                    if node['status'] == 'succeeded'}
        defendant = selected.get('defendant_s3', {}).get('items', [])
        m1 = {label: [{'id': item['id'], 'status': item['status'], 'withdraw_reason': item.get('withdraw_reason')}
                      for item in defendant if re.search(pattern, json.dumps(item, ensure_ascii=False))]
              for label, pattern in [('二年時效', r'(?<![零〇一二兩三四五六七八九十百千萬\d])(?:二|兩|2)\s*年|(?<!\d)197條'),
                                     ('五年時效', r'(?<![零〇一二兩三四五六七八九十百千萬\d])(?:五|5)\s*年'),
                                     ('民法182', r'(?<!\d)182(?!\d)')]}
        index = {f'{side}:{item["id"]}@S{stage}' for side in SIDES for stage in (1, 2, 3)
                 for item in selected.get(f'{side}_s{stage}', {}).get('items', [])}
        occurrences = []
        def scan(value, location=''):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key != 'internal_notes':
                        scan(child, location + '.' + key)
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    scan(child, location + f'[{i}]')
            elif isinstance(value, str):
                for sentence in re.split(r'[。！？\n]', value):
                    refs = re.findall(r'(?:plaintiff|defendant):[A-Za-z][A-Za-z0-9_-]*(?:@S[123])?', sentence)
                    valid = [r for r in refs if r in index or ('@S' not in r and any(r + '@S' + str(s) in index for s in (1, 2, 3)))]
                    for match in re.finditer(r'自承|自認|不爭執', sentence):
                        occurrences.append({'location': location, 'word': match.group(0), 'valid_refs': valid, 'sentence': sentence, 'text': value})
        for name, payload in selected.items():
            if not name.endswith('_verification'):
                scan(payload, location=name)
        reviewed = [p for name, payload in selected.items() if name.endswith('_verification') for p in payload.get('checks', [])]
        counts = {name: {'json_characters': len(json.dumps(payload, ensure_ascii=False)),
                         'chinese_characters': len(re.findall(r'[\u3400-\u9fff]', json.dumps(payload, ensure_ascii=False)))}
                  for name, payload in selected.items()}
        valid_count = sum(bool(o['valid_refs']) for o in occurrences)
        return {'case_id': self.case_id, 'run_id': self.run_id, 'calculated_at': now(),
            'M1_final_defenses': m1,
            'M2_verification': {'checks': reviewed, 'lawyer_review': [c for c in reviewed if c.get('status') != 'published'],
                                'historical_205': [c for c in reviewed if '205' in c.get('citation_text', '')]},
            'M3_pleading': {'persisted': state['nodes'].get('pleading', {}).get('status') == 'succeeded',
                'rejections': [a for a in state['nodes'].get('pleading', {}).get('attempts', []) if a.get('status') == 'rejected']},
            'M4_traceability': {'total': len(occurrences), 'with_valid_reference': valid_count,
                'ratio': valid_count / len(occurrences) if occurrences else None, 'zero_denominator': '不適用', 'occurrences': occurrences,
                'semantic_review': '編號可追溯不等於語意正確，待獨立人工抽核'},
            'M5_pending': {'report_present': bool(report), 'holders': report.get('pending', {}),
                'by_holder_counts': {holder: len(rows) for holder, rows in report.get('pending', {}).items()},
                'holdout_coverage': '待獨立驗證agent於角色完成後比對；未將holdout提供模型'},
            'M6_output_lengths': {'method': '選定JSON輸出的總字元及U+3400–U+9FFF中文字符，含欄位和值；修正回合另保留raw', 'by_node': counts}}


def main(argv=None):
    parser = argparse.ArgumentParser(description='隔離重跑real-case；先獨立驗收，後正式執行')
    parser.add_argument('--case-id', choices=CASE_IDS, default=CASE_IDS[1])
    parser.add_argument('--run-id')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--preflight-only', action='store_true', help='只測環境，不呼叫任何模型')
    args = parser.parse_args(argv)
    controller = RerunController(REPO, args.case_id, args.run_id, resume=args.resume)
    controller.prepare()
    print(controller.out, flush=True)
    if args.preflight_only:
        result = controller.preflight()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['passed'] else 1
    controller.run()
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
