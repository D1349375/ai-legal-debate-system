"""重跑控制器的隔離、可重現輸入與修正回合契約；不呼叫模型。"""
import json
from pathlib import Path
import shutil

import pytest


def module():
    import scripts.rerun_role_separation as rerun
    return rerun


def fake_repo(tmp_path):
    root = tmp_path / 'repo'
    templates = root / '.claude/skills/legal-debate/templates'
    templates.mkdir(parents=True)
    (templates.parent / 'SKILL.md').write_text('固定流程', encoding='utf-8')
    (templates / 'stage1_prompt.txt').write_text('案件 {CASE_ID}：讀 {CASE_FACTS_PATH}', encoding='utf-8')
    cases = root / 'data/cases'
    cases.mkdir(parents=True)
    (cases / 'real-2026-10-31-002.json').write_text(json.dumps({
        'case_id': 'real-2026-10-31-002', 'case_type': '侵權行為',
        'facts_summary': '第一則原文\n第二則原文', 'claims': '原告原起訴聲明：15顆比特幣',
        'source_note': '絕不可給角色看的來源與答案字號',
    }, ensure_ascii=False), encoding='utf-8')
    (root / 'corpus').mkdir()
    (root / 'corpus' / 'law.txt').write_text('公開法規', encoding='utf-8')
    return root


def test_conversion_preserves_raw_facts_but_removes_source_note():
    raw = {'case_id': 'real-2026-10-31-002', 'case_type': '侵權行為',
           'facts_summary': '原始\n資料，卷內未載', 'claims': '原告原起訴聲明', 'source_note': '秘密'}
    converted, log = module().convert_case(raw)
    assert converted['plaintiff_facts'] == raw['facts_summary']
    assert converted['represented_side'] == 'plaintiff'
    assert converted['claims'] == '原告起訴聲明'
    assert converted['claim_amount'] is None
    assert 'source_note' not in converted
    assert raw['source_note'] == '秘密'
    assert log['facts_changed'] is False


def test_001_amount_has_explicit_input_source():
    converted, log = module().convert_case({'case_id': 'real-2026-10-31-001', 'case_type': '契約',
                                           'facts_summary': '原文', 'claims': '請求新臺幣974,000元'})
    assert converted['claim_amount'] == 974000
    assert 'claims' in log['claim_amount_source']


def test_new_run_refuses_overwrite_and_freezes_hashes(tmp_path):
    repo = fake_repo(tmp_path)
    controller = module().RerunController(repo, 'real-2026-10-31-002', 'fixed-run')
    controller.prepare()
    manifest = json.loads((controller.out / 'run_manifest.json').read_text(encoding='utf-8'))
    assert manifest['model'] == 'gpt-6-astra'
    assert manifest['reasoning_effort'] == 'ultra'
    assert manifest['frozen_sha256']['templates/stage1_prompt.txt']
    assert manifest['db_url'].startswith('sqlite:///')
    assert str(controller.out).replace('\\', '/') in manifest['db_url']
    with pytest.raises(FileExistsError):
        module().RerunController(repo, 'real-2026-10-31-002', 'fixed-run').prepare()


def test_role_call_exposes_only_materials_and_corpus(tmp_path):
    controller = module().RerunController(fake_repo(tmp_path), 'real-2026-10-31-002', 'isolated')
    controller.prepare()
    material = controller.out / 'materials/role.json'
    material.write_text('{"role":"plaintiff","facts":[]}', encoding='utf-8')
    call = controller.prepare_call('p_s1-attempt-1', 'stage1_prompt.txt',
        {'CASE_ID': controller.case_id, 'CASE_FACTS_PATH': 'role.json'}, {'role.json': material})
    permissions = json.loads((call / 'permission_config.json').read_text(encoding='utf-8'))
    assert permissions['network_enabled'] is False
    assert permissions['filesystem'][':root'] == 'deny'
    assert permissions['filesystem'].get(controller.repo.as_posix()) != 'read'
    assert not (call / 'workspace/database').exists()
    assert not (call / 'workspace/controller').exists()
    assert 'source_note' not in (call / 'workspace/role.json').read_text(encoding='utf-8')
    argv = controller.model_command(call)
    assert 'agents.enabled=false' in argv
    assert 'features.multi_agent=false' in argv
    assert 'model_reasoning_effort="ultra"' in argv
    assert 'gpt-6-astra' in argv


def test_controller_metadata_cannot_be_passed_as_role_input(tmp_path):
    controller = module().RerunController(fake_repo(tmp_path), 'real-2026-10-31-002', 'no-secret')
    controller.prepare()
    with pytest.raises(ValueError, match='materials'):
        controller.prepare_call('bad', 'stage1_prompt.txt', {'CASE_ID': controller.case_id, 'CASE_FACTS_PATH': 'case.json'},
                                {'case.json': controller.out / 'controller/original_case.json'})


def test_run_ids_cannot_escape_output_directory(tmp_path):
    with pytest.raises(ValueError):
        module().RerunController(fake_repo(tmp_path), 'real-2026-10-31-002', '../outside')


def test_invalid_output_is_returned_verbatim_to_same_role_and_bounded(tmp_path):
    controller = module().RerunController(fake_repo(tmp_path), 'real-2026-10-31-002', 'retry')
    controller.prepare()
    original = '{"argument":"法律內容不得由controller改寫"}'
    seen = []
    def runner(call):
        seen.append(call)
        (call / 'last_message.txt').write_text(original, encoding='utf-8')
        return 0
    controller.run_model = runner
    def reject(payload, attempt):
        raise ValueError('精確錯誤：缺少items，必須修正')
    with pytest.raises(RuntimeError, match='3'):
        controller.execute_node('plaintiff_s1', 'stage1_prompt.txt',
                                {'CASE_ID': controller.case_id, 'CASE_FACTS_PATH': 'none'}, {}, reject)
    assert len(seen) == 3
    assert (seen[1] / 'workspace/previous_output.txt').read_text(encoding='utf-8') == original
    assert '精確錯誤：缺少items' in (seen[1] / 'workspace/validation_error.txt').read_text(encoding='utf-8')
    manifest = json.loads((controller.out / 'run_manifest.json').read_text(encoding='utf-8'))
    assert manifest['nodes']['plaintiff_s1']['status'] == 'failed'


def test_resume_reuses_committed_node_without_another_model_call(tmp_path):
    controller = module().RerunController(fake_repo(tmp_path), 'real-2026-10-31-002', 'resume')
    controller.prepare()
    def runner(call):
        (call / 'last_message.txt').write_text('{"argument":"原始內容"}', encoding='utf-8')
        return 0
    controller.run_model = runner
    result = controller.execute_node('plaintiff_s1', 'stage1_prompt.txt',
                                    {'CASE_ID': controller.case_id, 'CASE_FACTS_PATH': 'none'}, {}, lambda payload, attempt: None)
    resumed = module().RerunController(controller.repo, controller.case_id, 'resume', resume=True)
    resumed.prepare()
    resumed.run_model = lambda call: pytest.fail('已落地node不能重跑')
    assert resumed.execute_node('plaintiff_s1', 'stage1_prompt.txt', {}, {}, lambda *a: None) == result


def test_independent_review_cannot_publish_historical_current_text():
    mechanical = [{'citation_text': '108年民法第205條', 'status': 'version_unverified'}]
    check = {'citation_text': '108年民法第205條', 'status': 'published', 'reason': '現在網站有205',
             'existence': True, 'document_identity': True, 'supports_proposition': True}
    with pytest.raises(ValueError, match='version_unverified'):
        module().validate_independent_checks(mechanical, {'checks': [check]}, [check['citation_text']])


def test_independent_review_rejects_duplicates_and_missing_support():
    citation = '最高法院114年度台上字第1945號'
    mechanical = [{'citation_text': citation, 'status': 'published'}]
    check = {'citation_text': citation, 'status': 'published', 'reason': '只有字號存在',
             'existence': True, 'document_identity': True, 'supports_proposition': None}
    with pytest.raises(ValueError, match='支持'):
        module().validate_independent_checks(mechanical, {'checks': [check]}, [citation])
    check['supports_proposition'] = True
    with pytest.raises(ValueError, match='重複'):
        module().validate_independent_checks(mechanical, {'checks': [check, check]}, [citation])


def test_item_old_version_hint_reaches_matching_short_form():
    payload = {'items': [{'label': '利率上限應用108年舊法', 'citations': ['民法第205條']}],
               'cited_statutes': ['民法第205條']}
    hints = module().version_hints_for([payload], ['民法第205條第1項'])
    assert hints['民法第205條第1項'] == payload['items'][0]


def test_full_controller_lands_isolated_fixture_without_a_model(tmp_path):
    """實際CLI/DB串接；角色輸出為明示測試fixture，不當作真實重跑。"""
    rerun = module()
    repo = fake_repo(tmp_path)
    production = Path(__file__).resolve().parents[1]
    shutil.copyfile(production / 'main.py', repo / 'main.py')
    for folder in ('database', 'engine', '.claude/skills/legal-debate/templates'):
        shutil.copytree(production / folder, repo / folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.db'))
    controller = rerun.RerunController(repo, 'real-2026-10-31-002', 'fixture-only')
    controller.out = repo / 'run'
    controller.db_url = 'sqlite:///' + (controller.out / 'controller/run.db').as_posix()
    controller.prepare()
    controller.preflight = lambda: {'passed': True, 'model_called': False}
    seen = []
    def runner(call):
        meta = rerun.load_json(call / 'call_manifest.json')
        seen.append(meta['name'])
        runtime = call / 'workspace'
        all_input = '\n'.join(path.read_text(encoding='utf-8') for path in runtime.glob('*.json'))
        assert '絕不可給角色看的來源與答案字號' not in all_input
        if meta['template'].startswith('stage'):
            role = rerun.load_json(runtime / 'role.json')
            side = role['role']
            own = side == 'plaintiff'
            assert ('PRIVATE-DEFENDANT' if own else 'PRIVATE-PLAINTIFF') not in all_input
            item_id = 'P1' if own else 'D1'
            payload = {'side': side, 'position': '依現有資料主張' if own else '若資訊確認則評估抗辯',
                'argument': '測試公開論證；資料不足仍待確認', 'position_basis': [item_id] if own else [],
                'items': [{'id': item_id, 'label': '測試請求' if own else '若有對方事實的假設抗辯',
                    'kind': 'legal' if own else 'factual_hypothesis', 'status': 'asserted' if own else 'to_confirm',
                    'elements': [{'element': '測試要件', 'state': 'met' if own else 'unknown', 'source': 'F1', 'reason': '測試用'}],
                    'needs_from_client': [], 'citations': []}],
                'internal_notes': {'strategy': ['PRIVATE-PLAINTIFF' if own else 'PRIVATE-DEFENDANT'], 'prep_responses': []},
                'defeat_conditions': [], 'falsifier': '', 'cited_statutes': [], 'cited_precedents': [],
                'precedent_notes': [], 'claim_statement': '僅測試己方請求', 'rebuttal': '測試反駁不可進起訴素材'}
        elif meta['template'] == 'judge_question_prompt.txt':
            assert 'PRIVATE-' not in all_input
            payload = {'questions': [], 'prep_items': [], 'issues': [{'issue_id': 'I1', 'label': '測試爭點',
                        'items': ['plaintiff:P1', 'defendant:D1']}], 'uncontested_points': []}
        elif meta['template'] == 'verdict_prompt.txt':
            assert 'PRIVATE-' not in all_input
            role = rerun.load_json(runtime / 'judge_role.json')
            anchors = rerun.load_json(runtime / 'anchors.json')
            refs = [p['id'] for group in anchors['pending'].values() for p in group] + [c['id'] for c in anchors['defeat_conditions']]
            payload = {'issues': [{'issue_id': 'I1', 'label': '測試爭點', 'own_items': ['plaintiff:P1@S3'],
                'opponent_items': ['defendant:D1@S3'], 'reference_grade': role['issues'][0]['reference_grade'],
                'grade': role['issues'][0]['reference_grade'], 'basis': ['F1'], 'to_prepare': []}],
                'summary': '依測試資料準備；待確認defendant:D1@S3',
                'anchor_responses': [{'ref': ref, 'comment': '待確認；若取得資訊再評估'} for ref in refs], 'citations_used': []}
        elif meta['template'] == 'verify_prompt.txt':
            assert 'PRIVATE-' not in all_input
            payload = {'checks': [], 'lawyer_review': []}
        else:
            assert '測試反駁不可進起訴素材' not in all_input
            assert 'PRIVATE-' not in all_input
            payload = {'draft_text': '民事起訴狀\n依既有事實請求給付。', 'citations_used': [], 'claim_breakdown': []}
        (call / 'last_message.txt').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return 0
    controller.run_model = runner
    controller.run()
    assert len(seen) == 11
    assert controller.manifest()['status'] == 'completed'
    assert (controller.out / 'controller/run.db').exists()
    assert (controller.out / 'metrics.json').exists()
    report = rerun.load_json(controller.out / 'materials/report.json')
    assert report['pleadings']
    assert all(item['status'] == 'to_confirm' for item in report['opponent_preview']['items'])


def stage_fixture(side):
    own = side == 'plaintiff'
    return {'side': side, 'position': '測試立場' if own else '待確認抗辯', 'position_basis': ['P1'] if own else [],
        'argument': '公開測試內容', 'items': [{'id': 'P1' if own else 'D1', 'label': '請求或假設',
        'kind': 'legal' if own else 'factual_hypothesis', 'status': 'asserted' if own else 'to_confirm',
        'elements': [{'element': '要件', 'state': 'met' if own else 'unknown', 'source': 'F1'}],
        'citations': [], 'needs_from_client': []}], 'internal_notes': {}, 'falsifier': '', 'cited_statutes': [], 'cited_precedents': []}


def stage_controller(tmp_path):
    from database.db import get_session, record_case, record_argument
    from engine.role_protocol import role_view
    controller = module().RerunController(fake_repo(tmp_path), 'real-2026-10-31-002', 'paired')
    controller.out = controller.repo / 'run'
    controller.db_url = 'sqlite:///' + (controller.out / 'controller/run.db').as_posix()
    controller.prepare()
    with get_session(controller.db_url) as session:
        record_case(session, **module().load_json(controller.out / 'controller/converted_case.json'))
    controller._material('procedural', {})
    def project(label, args):
        with get_session(controller.db_url) as session:
            result = role_view(session, controller.case_id, args[-1])
        return controller._material(label, result)
    controller.project = project
    def cli(label, args):
        payload = module().load_json(args[-1])
        with get_session(controller.db_url) as session:
            record_argument(session, case_id=payload['case_id'], side=payload['side'], stage=payload['stage'],
                position=payload['position'], reasoning=payload['argument'], cited_statutes=[], cited_precedents=[],
                structured_json=payload)
        return '已落地'
    controller.cli = cli
    return controller


def test_second_side_invalid_leaves_both_stage_rows_unwritten(tmp_path):
    from database.db import get_session
    from database.schema import DebateArgument
    controller = stage_controller(tmp_path)
    def runner(call):
        side = 'plaintiff' if call.name.startswith('plaintiff') else 'defendant'
        payload = stage_fixture(side)
        if side == 'defendant':
            payload['items'] = []
        (call / 'last_message.txt').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return 0
    controller.run_model = runner
    with pytest.raises(RuntimeError):
        controller._stage(1)
    with get_session(controller.db_url) as session:
        assert session.query(DebateArgument).count() == 0


def test_selected_pair_can_resume_landing_without_model_reexecution(tmp_path):
    from database.db import get_session
    from database.schema import DebateArgument
    controller = stage_controller(tmp_path)
    def runner(call):
        side = 'plaintiff' if call.name.startswith('plaintiff') else 'defendant'
        (call / 'last_message.txt').write_text(json.dumps(stage_fixture(side), ensure_ascii=False), encoding='utf-8')
        return 0
    controller.run_model = runner
    real_cli = controller.cli
    controller.cli = lambda *args: (_ for _ in ()).throw(RuntimeError('模擬已選JSON、尚未落地時中斷'))
    with pytest.raises(RuntimeError):
        controller._stage(1)
    assert all(controller.manifest()['nodes'][side + '_s1']['status'] == 'succeeded' for side in ('plaintiff', 'defendant'))
    controller.run_model = lambda call: pytest.fail('續跑不可重新呼叫已選定角色')
    controller.cli = real_cli
    controller._stage(1)
    controller._stage(1)
    with get_session(controller.db_url) as session:
        assert session.query(DebateArgument).count() == 2


def test_metrics_do_not_borrow_sibling_reference_or_match_fifteen_years(tmp_path):
    controller = module().RerunController(fake_repo(tmp_path), 'real-2026-10-31-002', 'metrics')
    controller.prepare()
    payloads = {'plaintiff_s3': {'items': [{'id': 'P1'}]},
                'defendant_s3': {'items': [{'id': 'D1', 'label': '十五年時效', 'status': 'to_confirm'}]},
                'verdict': {'summary': '被告自承收款。', 'issues': [{'own_items': ['plaintiff:P1@S3']}]}}
    for name, payload in payloads.items():
        path = controller.out / 'artifacts' / (name + '.json')
        module().save_json(path, payload)
        controller.update(lambda state, name=name: state['nodes'].__setitem__(name, {'status': 'succeeded', 'selected_output': f'artifacts/{name}.json'}))
    metrics = controller.metrics({})
    assert metrics['M4_traceability']['total'] == 1
    assert metrics['M4_traceability']['with_valid_reference'] == 0
    assert metrics['M1_final_defenses']['五年時效'] == []
