"""Independent review regressions: UI consumption of v2 case-specific checks."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from database.db import (get_session, record_case, record_case_citation_check,
                         record_pleading, upsert_citation)
from server.services import save_pleading_edit, find_pleading_version


@pytest.fixture
def review_session():
    session = get_session('sqlite:///:memory:')
    record_case(session, case_id='review', case_type='契約', claims='請求給付',
                represented_side='plaintiff', plaintiff_facts='契約約定。')
    yield session
    session.close()


def test_ui_edit_must_not_publish_precedent_rejected_for_this_case(review_session):
    session = review_session
    parent = record_pleading(session, case_id='review', draft_text='民事起訴狀', citations_used=[])
    citation = '最高法院115年度台上字第447號'
    record_case_citation_check(session, 'review', {
        'citation_text': citation, 'status': 'unsupported', 'supports_proposition': False,
        'reason': '獨立查證不支持本案命題'}, 'review-negative')
    version = save_pleading_edit(session, 'review', parent.id,
                                '民事起訴狀。依' + citation + '請求給付。', mode='offline')
    assert version['status'] == 'blocked'
    assert version['exportable'] is False


def test_ui_edit_must_preserve_historical_version_warning(review_session):
    session = review_session
    upsert_citation(session, citation_text='民法第205條', source_type='statute', status='published')
    record_case_citation_check(session, 'review', {
        'citation_text': '民法第205條', 'status': 'published'}, 'current')
    parent = record_pleading(session, case_id='review', draft_text='依民法第205條請求給付',
                             citations_used=['民法第205條'])
    record_case_citation_check(session, 'review', {
        'citation_text': '108年民法第205條', 'status': 'version_unverified'}, 'historical')
    version = save_pleading_edit(session, 'review', parent.id,
                                '依108年民法第205條請求給付', mode='offline')
    assert version['status'] == 'blocked'
    assert version['exportable'] is False


def test_ui_edit_keeps_historical_warning_when_current_article_occurs_first(review_session):
    session = review_session
    record_case_citation_check(session, 'review', {
        'citation_text': '民法第205條', 'status': 'published'}, 'current')
    parent = record_pleading(session, case_id='review', draft_text='依民法第205條請求給付',
                             citations_used=['民法第205條'])
    version = save_pleading_edit(session, 'review', parent.id,
                                '現行民法第205條另有規定。本件依108年民法第205條請求給付。', mode='offline')
    assert version['status'] == 'blocked'
    assert version['exportable'] is False


def test_ui_system_draft_must_honor_latest_case_failure(review_session):
    session = review_session
    upsert_citation(session, citation_text='民法第184條', source_type='statute', status='published')
    record_case_citation_check(session, 'review', {
        'citation_text': '民法第184條', 'status': 'published'}, 'before')
    parent = record_pleading(session, case_id='review', draft_text='依民法第184條請求給付',
                             citations_used=['民法第184條'])
    record_case_citation_check(session, 'review', {
        'citation_text': '民法第184條', 'status': 'network_error', 'reason': '本案最新查證未通過'}, 'after')
    version = find_pleading_version(session, 'review', parent.id)
    assert version['status'] == 'blocked'
    assert version['exportable'] is False


def _land_stage(session, stage):
    from database.db import record_argument
    for side, item_id in [('plaintiff', 'P1'), ('defendant', 'D1')]:
        record_argument(session, case_id='review', side=side, stage=stage,
                        position='依契約評估', reasoning='依書面契約內容評估。', structured_json={
                            'items': [{'id': item_id, 'label': '契約請求', 'kind': 'legal',
                                       'status': 'asserted' if side == 'plaintiff' else 'to_confirm',
                                       'elements': [{'element': '契約成立', 'state': 'met', 'source': 'F1'}],
                                       'citations': [], 'needs_from_client': []}],
                            'position_basis': ['P1'] if side == 'plaintiff' else [],
                            'internal_notes': {}, 'claim_statement': '請求給付', 'rebuttal': ''})


def test_ui_resume_recognizes_completed_judge_bundle_with_no_questions(review_session):
    from database.db import record_judge_bundle
    from server.live_run import resume_plan, pipeline_missing
    session = review_session
    _land_stage(session, 1)
    record_judge_bundle(session, case_id='review', payload={
        'questions': [], 'prep_items': [], 'issues': [], 'uncontested_points': []})
    _land_stage(session, 2)
    plan = resume_plan(session, 'review')
    assert plan['possible'] is True
    assert plan['from_key'] == 'stage3'
    assert '法官訊問' not in pipeline_missing(session, 'review', documents=['plaintiff'])


def test_grade_uses_final_items_for_stage_qualified_issue_references(review_session):
    from database.db import record_judge_bundle
    from engine.role_protocol import issues_with_grades
    session = review_session
    _land_stage(session, 1)
    record_judge_bundle(session, case_id='review', payload={
        'questions': [], 'prep_items': [], 'uncontested_points': [],
        'issues': [{'issue_id': 'I1', 'label': '契約請求',
                    'items': ['plaintiff:P1@S1', 'defendant:D1@S1']}]})
    _land_stage(session, 2)
    _land_stage(session, 3)
    assert issues_with_grades(session, 'review')[0]['reference_grade'] == '高'


@pytest.fixture
def review_cli_db(tmp_path):
    url = 'sqlite:///' + (tmp_path / 'review.db').as_posix()
    with get_session(url) as session:
        record_case(session, case_id='review', case_type='契約', claims='請求給付',
                    represented_side='plaintiff', plaintiff_facts='契約約定。')
    return url


def _review_cli(tmp_path, url, citations, *, notes=None, checks=None, candidate=None, prepare=False):
    command = [sys.executable, '-X', 'utf8', 'main.py', 'verify', *citations, '--case-id', 'review']
    if notes is not None:
        path = tmp_path / 'notes.json'
        path.write_text(json.dumps(notes, ensure_ascii=False), encoding='utf-8')
        command += ['--precedent-notes', str(path)]
    if checks is not None:
        path = tmp_path / 'review.json'
        path.write_text(json.dumps({'case_id': 'review', 'verifier_run_id': 'independent-review',
                                   'checks': checks}, ensure_ascii=False), encoding='utf-8')
        command += ['--review-json', str(path)]
    if candidate is not None:
        path = tmp_path / 'candidate.json'
        path.write_text(json.dumps(candidate, ensure_ascii=False), encoding='utf-8')
        command += ['--candidate-json', str(path)]
    if prepare:
        command += ['--prepare-only']
    return subprocess.run(command, cwd=Path(__file__).resolve().parents[1],
                          env={**os.environ, 'LEGALDEBATE_DB_URL': url}, capture_output=True,
                          text=True, encoding='utf-8', timeout=30)


def _checked_precedent():
    citation = '最高法院114年度台上字第1945號'
    note = {'citation': citation, 'doc_date': '20260513', 'doc_type': '判決',
            'case_cause': '請求確認本票債權不存在等', 'quote': '最高法院民事判決',
            'proposition': '裁判所論契約效力', 'analogy_reason': None}
    check = {'citation_text': citation, 'status': 'published', 'reason': '獨立核對本次採用命題',
             'existence': True, 'document_identity': True, 'supports_proposition': True}
    return citation, note, check


def test_live_cli_consumes_review_and_allows_verified_precedent_to_land(review_cli_db, tmp_path):
    from database.schema import CaseCitationCheck
    citation, note, check = _checked_precedent()
    result = _review_cli(tmp_path, review_cli_db, [citation], notes=[note], checks=[check])
    assert result.returncode == 0, result.stdout + result.stderr
    with get_session(review_cli_db) as session:
        saved = session.query(CaseCitationCheck).one()
        assert json.loads(saved.metadata_json)['supports_proposition'] is True
        draft = record_pleading(session, case_id='review', draft_text='依' + citation + '請求給付',
                                citations_used=[citation])
        assert draft.citation_verification_status == 'published'


def test_live_cli_rejects_existence_only_precedent_despite_review_true(review_cli_db, tmp_path):
    from database.schema import CaseCitationCheck, CitationVerification
    citation = '最高法院115年度台上字第447號'
    check = {'citation_text': citation, 'status': 'published', 'reason': '宣稱查證通過',
             'existence': True, 'document_identity': True, 'supports_proposition': True}
    result = _review_cli(tmp_path, review_cli_db, [citation], checks=[check])
    assert result.returncode == 1, result.stdout + result.stderr
    with get_session(review_cli_db) as session:
        assert session.query(CaseCitationCheck).count() == 0
        assert session.query(CitationVerification).count() == 0


def test_live_cli_rejects_whole_batch_if_review_upgrades_historical_failure(review_cli_db, tmp_path):
    from database.schema import CaseCitationCheck, CitationVerification
    citation, note, valid = _checked_precedent()
    invalid = {'citation_text': '108年民法第205條', 'status': 'published', 'reason': '宣稱歷史版本通過',
               'existence': True, 'document_identity': True, 'supports_proposition': True}
    result = _review_cli(tmp_path, review_cli_db, [citation, invalid['citation_text']],
                         notes=[note], checks=[valid, invalid])
    assert result.returncode == 1, result.stdout + result.stderr
    with get_session(review_cli_db) as session:
        assert session.query(CaseCitationCheck).count() == 0
        assert session.query(CitationVerification).count() == 0


def test_live_prepare_propagates_item_old_version_to_equivalent_final_citation(review_cli_db, tmp_path):
    from database.db import record_argument
    with get_session(review_cli_db) as session:
        record_argument(session, case_id='review', side='plaintiff', stage=1,
                        position='依契約評估', reasoning='依書面契約內容評估。',
                        cited_statutes=['民法第205條'], structured_json={
                            'items': [{'id': 'P1', 'label': '契約請求', 'kind': 'legal', 'status': 'asserted',
                                       'elements': [{'element': '契約成立', 'state': 'met', 'source': 'F1'}],
                                       'citations': ['民法第205條'], 'version_hint': '舊法',
                                       'needs_from_client': []}],
                            'position_basis': ['P1'], 'internal_notes': {}})
    result = _review_cli(tmp_path, review_cli_db, [], prepare=True,
                         candidate={'citations_used': ['民法第205條第1項']})
    assert result.returncode == 0, result.stdout + result.stderr
    prepared = json.loads(result.stdout)
    assert '民法第205條第1項' in prepared['version_hints']
