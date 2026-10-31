import json

import pytest

from database.db import get_session, record_case, record_argument, record_question, record_judge_bundle, record_verdict, finalize_case, pleading_materials, record_pleading


@pytest.fixture
def session():
    s = get_session('sqlite:///:memory:')
    yield s
    s.close()


def new_case(session, side='plaintiff'):
    return record_case(session, case_id='v2', case_type='買賣', facts_summary='舊摘要', claims='給付',
                       represented_side=side, plaintiff_facts='〔書證：郵件〕已催告\n交付貨物',
                       defendant_facts='對方說短少', claim_amount=100000)


def item(id='P1', status='asserted', kind='legal', source='F1'):
    return dict(id=id, label='給付價金', kind=kind, status=status,
                elements=[dict(element='已交付', state='met', source=source)], needs_from_client=[], citations=[])


def argument(session, side='plaintiff', stage=1, items=None, **over):
    data = dict(items=items or [item('P1' if side == 'plaintiff' else 'D1')], position_basis=[],
                internal_notes={'secret': side + '-private'}, precedent_notes=[], defeat_conditions=[])
    data.update(over)
    if stage == 3:
        data.setdefault('claim_statement', '給付已交付貨物之價金')
        data.setdefault('rebuttal', '回應')
    return record_argument(session, case_id='v2', side=side, stage=stage, position='依法主張', reasoning='公開論證', structured_json=data)


def test_role_view_fact_ids_sources_and_private_boundaries(session):
    from engine.role_protocol import role_view, argument_summary
    new_case(session)
    argument(session)
    argument(session, side='defendant')
    own = role_view(session, 'v2', 'plaintiff')
    assert own['has_client'] is True
    assert own['facts'][0]['id'] == 'F1' and own['facts'][0]['source'] == '書證'
    assert own['facts'][0]['source_name'] == '郵件'
    assert '原告轉述' in own['facts'][-1]['attribution']
    assert 'plaintiff-private' in json.dumps(own)
    judge = json.dumps(role_view(session, 'v2', 'judge'), ensure_ascii=False)
    assert 'private' not in judge and 'source_note' not in judge
    assert 'internal_notes' not in argument_summary(session, 'v2', 'plaintiff', 1)


def test_unknown_position_and_missing_fact_ref_rejected(session):
    new_case(session)
    with pytest.raises(ValueError, match='事實編號'):
        argument(session, items=[item(source='F99')])
    with pytest.raises(ValueError, match='position_basis'):
        argument(session, items=[item(status='to_confirm')], position_basis=['P1'])


def test_opponent_hypothesis_and_withdrawal_missing_item_rejected(session):
    new_case(session)
    with pytest.raises(ValueError, match='to_confirm'):
        argument(session, side='defendant', items=[item('D1', kind='factual_hypothesis')])
    argument(session, side='defendant', items=[item('D1', status='to_confirm', kind='factual_hypothesis')])
    with pytest.raises(ValueError, match='withdraw_reason'):
        argument(session, side='defendant', stage=2, items=[item('D1', status='withdrawn', kind='factual_hypothesis')])
    withdrawn = item('D1', status='withdrawn', kind='factual_hypothesis')
    withdrawn['withdraw_reason'] = {'type': 'strategy', 'explanation': '無本人資料'}
    with pytest.raises(ValueError, match='策略|strategy'):
        argument(session, side='defendant', stage=2, items=[withdrawn])
    with pytest.raises(ValueError, match='消失'):
        argument(session, side='defendant', stage=2, items=[item('D2')])


def test_judge_cannot_ask_opponent_factual_or_invent_admission(session):
    new_case(session)
    argument(session)
    argument(session, side='defendant', items=[item('D1', status='to_confirm', kind='factual_hypothesis')])
    with pytest.raises(ValueError, match='事實題|factual'):
        record_question(session, case_id='v2', question_text='是否持有影片', target_side='defendant', based_on='defendant:D1', question_type='factual')
    with pytest.raises(ValueError, match='自承|事實陳述'):
        record_question(session, case_id='v2', question_text='被告自承不知日期', target_side='defendant', based_on='defendant:D1', question_type='legal')


def test_pleading_projection_and_banned_words(session):
    new_case(session)
    for stage in (1, 2, 3):
        argument(session, stage=stage)
        argument(session, side='defendant', stage=stage,
                 items=[item('D1', status='to_confirm', kind='factual_hypothesis')])
    source = pleading_materials(session, case_id='v2', side='plaintiff')
    dumped = json.dumps(source, ensure_ascii=False)
    assert 'rebuttal' not in dumped and 'private' not in dumped and 'to_confirm' not in dumped
    with pytest.raises(ValueError, match='對造'):
        record_pleading(session, case_id='v2', draft_text='對造要求先確定事實', citations_used=[])
    with pytest.raises(ValueError, match='代理方'):
        record_pleading(session, case_id='v2', side='defendant', draft_text='答辯狀', citations_used=[])


def test_aggregate_pending_report_privacy_and_grades(session):
    from engine.role_protocol import build_report, render_report, reference_grade
    new_case(session)
    for stage in (1, 2, 3):
        own = item()
        own['needs_from_client'] = [{'text': '催告何時到達', 'holder': 'own_client'}]
        argument(session, stage=stage, items=[own])
        hypothesis = item('D1', status='to_confirm', kind='factual_hypothesis')
        hypothesis['needs_from_client'] = [{'text': '若對方提出影片', 'holder': 'opponent'}]
        argument(session, side='defendant', stage=stage, items=[hypothesis])
    anchors = finalize_case(session, case_id='v2')
    assert 'weak_points' not in anchors and 'position_drift' not in anchors
    assert anchors['pending']['opponent'][0]['holder'] == 'opponent'
    assert 'private' not in json.dumps(anchors)
    report = build_report(session, 'v2')
    text = render_report(report)
    assert '待確認' in text and '預測' in text
    assert 'plaintiff-private' in text and 'defendant-private' not in text
    assert reference_grade([item()], []) == '高'
    assert reference_grade([item(status='to_confirm')], []) == '中'
    low = item(); low['elements'][0]['state'] = 'unmet'
    assert reference_grade([low], []) == '低'


def completed_case(session):
    new_case(session)
    for stage in (1, 2, 3):
        argument(session, stage=stage)
        argument(session, side='defendant', stage=stage)


def verdict(session, data):
    return record_verdict(session, case_id='v2', verdict_main_text=data.get('summary', ''),
                          verdict_reasoning='', risk_map={}, mechanical_anchor_json={},
                          protocol_version='v2', citations_used=[], structured_json=data)


def test_verdict_rejects_fictional_status_changes(session):
    completed_case(session)
    with pytest.raises(ValueError, match='status_changes'):
        verdict(session, {'issues': [], 'summary': 'plaintiff:P1@S1 → plaintiff:P1@S3，已改為不同立場。', 'anchor_responses': []})


def test_verdict_issues_grades_and_corroboration(session):
    new_case(session)
    argument(session)
    argument(session, side='defendant')
    record_judge_bundle(session, case_id='v2', payload={'questions': [], 'prep_items': [], 'issues': [
        {'issue_id': 'I1', 'label': '價金請求', 'items': ['plaintiff:P1', 'defendant:D1']}], 'uncontested_points': []})
    for stage in (2, 3):
        argument(session, stage=stage)
        argument(session, side='defendant', stage=stage)
    data = {'issues': [{'issue_id': 'I1', 'label': '價金請求', 'own_items': ['plaintiff:P1@S3'],
                       'opponent_items': ['defendant:D1@S3'], 'grade': '高', 'basis': ['F1']}],
            'summary': 'F1 足以佐證買賣。', 'anchor_responses': []}
    with pytest.raises(ValueError, match='grade_reason'):
        verdict(session, data)
    data['issues'][0]['grade_reason'] = '法律評估理由'
    with pytest.raises(ValueError, match='兩個不同'):
        verdict(session, data)
    data['summary'] = 'F1 與 F2 相互印證。'
    row = verdict(session, data)
    assert json.loads(row.structured_json)['issues'][0]['reference_grade'] == '中'


def test_claim_breakdown_pending_excluded_and_preserved_as_lawyer_note(session):
    new_case(session)
    for stage in (1, 2, 3):
        argument(session, stage=stage, items=[item(), item('P2', status='to_confirm')])
    row = record_pleading(session, case_id='v2', draft_text='起訴狀：請求已確定價金六萬元。', citations_used=[],
                          claim_breakdown=[{'name': '已確定價金', 'amount': 60000, 'basis': ['F1'], 'item': 'plaintiff:P1@S3'},
                                           {'name': '待確認損害', 'amount': 30000, 'basis': ['F2'], 'item': 'plaintiff:P2@S3'}])
    breakdown = json.loads(row.claim_breakdown_json)
    assert breakdown['total'] == 60000
    assert breakdown['pending'][0]['amount'] == 30000
    assert '律師附註' in row.draft_text and '不計入訴之聲明' in row.draft_text
    assert json.loads(row.warnings_json)


def test_own_stage2_requires_private_responses_to_all_preparations(session):
    new_case(session)
    argument(session)
    argument(session, side='defendant')
    record_judge_bundle(session, case_id='v2', payload={'questions': [], 'issues': [], 'uncontested_points': [],
        'prep_items': [{'id': 'J-PREP-1', 'hypothesis': '對方可能提出影片', 'affects': 'plaintiff:P1',
                        'prepare': '確認我方交貨時間', 'holder': 'opponent', 'is_hypothesis': True}]})
    with pytest.raises(ValueError, match='prep_responses'):
        argument(session, stage=2)
    argument(session, stage=2, internal_notes={'prep_responses': [{'id': 'J-PREP-1', 'response': 'PRIVATE_PREP_RESPONSE'}]})
    from engine.role_protocol import role_view
    assert 'PRIVATE_PREP_RESPONSE' in json.dumps(role_view(session, 'v2', 'plaintiff'))
    assert 'PRIVATE_PREP_RESPONSE' not in json.dumps(role_view(session, 'v2', 'judge'))


def test_verdict_issue_cannot_swap_own_and_opponent_refs(session):
    new_case(session)
    argument(session)
    argument(session, side='defendant')
    record_judge_bundle(session, case_id='v2', payload={'questions': [], 'prep_items': [], 'issues': [
        {'issue_id': 'I1', 'label': '價金請求', 'items': ['plaintiff:P1', 'defendant:D1']}], 'uncontested_points': []})
    for stage in (2, 3):
        argument(session, stage=stage)
        argument(session, side='defendant', stage=stage)
    with pytest.raises(ValueError, match='own_items'):
        verdict(session, {'issues': [{'issue_id': 'I1', 'own_items': ['defendant:D1@S3'],
                                    'opponent_items': ['plaintiff:P1@S3'], 'grade': '中', 'basis': ['F1']}],
                          'summary': '準備契約。', 'anchor_responses': []})


def test_historical_statute_cannot_borrow_current_global_publication(session):
    from database.db import upsert_citation, _assert_all_published
    upsert_citation(session, citation_text='民法第205條', source_type='statute', status='published')
    with pytest.raises(ValueError, match='version_unverified'):
        _assert_all_published(session, ['108年民法第205條'])


def test_v2_requires_own_latest_case_check_not_global_or_other_case(session):
    from database.db import upsert_citation, record_case_citation_check, _assert_all_published
    new_case(session)
    record_case(session, case_id='other', case_type='其他案', facts_summary='事實', claims='請求')
    upsert_citation(session, citation_text='民法第184條', source_type='statute', status='published')
    record_case_citation_check(session, 'other', {'citation_text': '民法第184條', 'status': 'published'})
    with pytest.raises(ValueError, match='本案'):
        _assert_all_published(session, ['民法第184條'], case_id='v2')
    record_case_citation_check(session, 'v2', {'citation_text': '民法第184條', 'status': 'published'})
    _assert_all_published(session, ['民法第184條'], case_id='v2')
    record_case_citation_check(session, 'v2', {'citation_text': '民法第184條', 'status': 'network_error'})
    with pytest.raises(ValueError, match='本案'):
        _assert_all_published(session, ['民法第184條'], case_id='v2')


def test_judgment_cannot_hide_in_item_citations_without_full_text_note(session):
    new_case(session)
    p = item()
    p['citations'] = ['最高法院114年度台上字第1945號']
    with pytest.raises(ValueError, match='precedent_notes'):
        argument(session, items=[p])


def test_verdict_must_cover_procedural_anchor_without_mistaking_it_for_item(session):
    from engine.role_protocol import case_row, validate_verdict
    completed_case(session)
    anchors = {'pending': {}, 'defeat_conditions': [], 'procedural_issues': {'issues': [{'id': 'defendant:no_rep'}]}}
    with pytest.raises(ValueError, match='覆蓋'):
        validate_verdict(session, case_row(session, 'v2'), {'issues': [], 'summary': '程序需補正。', 'anchor_responses': []}, anchors)
    validate_verdict(session, case_row(session, 'v2'), {'issues': [], 'summary': '程序需補正。',
                     'anchor_responses': [{'ref': 'defendant:no_rep', 'comment': '應先補正法定代理人。'}]}, anchors)


def test_public_projection_does_not_leak_private_fields_nested_in_items(session):
    from engine.role_protocol import role_view
    new_case(session)
    p = item()
    p['internal_notes'] = {'secret': 'NESTED_PRIVATE_SENTINEL'}
    argument(session, items=[p])
    assert 'NESTED_PRIVATE_SENTINEL' not in json.dumps(role_view(session, 'v2', 'judge'))


def test_verdict_judgments_require_this_round_precedent_notes(session):
    from engine.role_protocol import case_row, validate_verdict
    completed_case(session)
    with pytest.raises(ValueError, match='precedent_notes'):
        validate_verdict(session, case_row(session, 'v2'), {'issues': [], 'summary': '準備契約。', 'anchor_responses': [],
                         'citations_used': ['最高法院114年度台上字第1945號']}, finalize_case(session, case_id='v2'))
