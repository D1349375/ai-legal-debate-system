"""既有 verify CLI 的獨立第三層輸入；所有機械查證使用本地裁判全文。"""
import json
import sys

import pytest

import main
from database.db import DB_URL_ENV, get_session, record_case, _assert_all_published
from database.schema import CaseCitationCheck, CitationVerification
from engine import verify

CITATION = '最高法院114年度台上字第1945號'


@pytest.fixture
def review_cli(tmp_path, monkeypatch):
    url = f'sqlite:///{tmp_path / "review.db"}'
    monkeypatch.setenv(DB_URL_ENV, url)
    corpus = tmp_path / 'judgments'
    corpus.mkdir()
    stem = 'TPSV,114,台上,1945,20260513,1'
    (corpus / (stem + '.txt')).write_text('最高法院民事判決\n本件契約成立後仍應依約給付。', encoding='utf-8')
    (corpus / (stem + '_source.json')).write_text(json.dumps({'jid': stem, 'jdate': '20260513', 'jtitle': '給付價金'}), encoding='utf-8')
    monkeypatch.setattr(verify, 'JUDGMENTS_DIR', str(corpus))
    with get_session(url) as session:
        record_case(session, case_id='c1', case_type='契約', claims='請求給付', represented_side='plaintiff', plaintiff_facts='契約已成立。')
    note = {'citation': CITATION, 'doc_date': '20260513', 'doc_type': '判決', 'case_cause': '給付價金',
            'quote': '契約成立後仍應依約給付', 'proposition': '應依契約給付', 'analogy_reason': None}
    notes_path = tmp_path / 'notes.json'
    notes_path.write_text(json.dumps([note], ensure_ascii=False), encoding='utf-8')

    def run(review, *, citation=CITATION, notes=None, case_id='c1'):
        if notes is not None:
            notes_path.write_text(json.dumps(notes, ensure_ascii=False), encoding='utf-8')
        path = tmp_path / 'review.json'
        path.write_text(json.dumps(review, ensure_ascii=False), encoding='utf-8')
        argv = ['main.py', 'verify', citation, '--case-id', case_id,
                '--precedent-notes', str(notes_path), '--review-json', str(path)]
        monkeypatch.setattr(sys, 'argv', argv)
        with pytest.raises(SystemExit) as exited:
            main.main()
        return exited.value.code

    return url, note, run


def payload(citation=CITATION, case_id='c1', **overrides):
    check = {'citation_text': citation, 'status': 'published', 'reason': '原文直接支持契約給付命題。',
             'existence': True, 'document_identity': True, 'supports_proposition': True}
    check.update(overrides)
    return {'case_id': case_id, 'verifier_run_id': 'independent-review-1', 'checks': [check]}


def test_review_json_publishes_case_specific_precedent_after_real_identity_and_quote_checks(review_cli):
    url, _, run = review_cli
    assert run(payload()) == 0
    with get_session(url) as session:
        row = session.query(CaseCitationCheck).one()
        assert row.verifier_run_id == 'independent-review-1'
        assert row.status == 'published'
        assert json.loads(row.metadata_json)['supports_proposition'] is True
        _assert_all_published(session, [CITATION], case_id='c1')


@pytest.mark.parametrize('failure', ['historical', 'document_type', 'existence_only'])
def test_review_cannot_upgrade_historical_or_document_failure(review_cli, failure):
    url, note, run = review_cli
    citation, notes = CITATION, [note]
    if failure == 'historical':
        citation, notes = '108年民法第205條', []
    elif failure == 'document_type':
        notes = [{**note, 'doc_type': '裁定'}]
    elif failure == 'existence_only':
        notes = []
    assert run(payload(citation), citation=citation, notes=notes) != 0
    with get_session(url) as session:
        assert session.query(CaseCitationCheck).count() == 0
        assert session.query(CitationVerification).count() == 0


def test_review_wrong_case_is_rejected_without_writing_any_check(review_cli):
    url, _, run = review_cli
    assert run(payload(case_id='other-case')) != 0
    with get_session(url) as session:
        assert session.query(CaseCitationCheck).count() == 0
        assert session.query(CitationVerification).count() == 0


@pytest.mark.parametrize('mutation', ['duplicate', 'missing', 'empty_reason', 'bad_status'])
def test_review_rejects_malformed_or_non_bijective_check_lists(review_cli, mutation):
    url, _, run = review_cli
    data = payload()
    if mutation == 'duplicate':
        data['checks'].append(dict(data['checks'][0]))
    elif mutation == 'missing':
        data['checks'] = []
    elif mutation == 'empty_reason':
        data['checks'][0]['reason'] = ' '
    else:
        data['checks'][0]['status'] = 'trust_me'
    assert run(data) != 0
    with get_session(url) as session:
        assert session.query(CaseCitationCheck).count() == 0


def test_prepare_only_reads_case_notes_history_and_candidate_citations(review_cli, tmp_path, monkeypatch, capsys):
    from database.db import record_argument
    url, note, _ = review_cli
    with get_session(url) as session:
        record_argument(session, case_id='c1', side='plaintiff', stage=1, position='依法請求。', reasoning='公開論證。',
                        cited_statutes=['民法第205條'], cited_precedents=[CITATION], structured_json={
                            'items': [{'id': 'P1', 'label': '利息請求', 'kind': 'legal', 'status': 'asserted',
                                       'elements': [{'element': '契約成立', 'state': 'met', 'source': 'F1'}],
                                       'citations': ['民法第205條', CITATION], 'needs_from_client': [], 'applicable_version': '108年版'}],
                            'position_basis': ['P1'], 'internal_notes': {'secret': 'PRIVATE_DO_NOT_EXPORT'}, 'precedent_notes': [note]})
    candidate_path = tmp_path / 'candidate.json'
    candidate_path.write_text(json.dumps({'citations_used': ['銀行法第29條', '民法第205條第1項'], 'precedent_notes': []}, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['main.py', 'verify', '--case-id', 'c1', '--prepare-only', '--candidate-json', str(candidate_path)])
    with pytest.raises(SystemExit) as exited:
        main.main()
    assert exited.value.code == 0
    output = capsys.readouterr().out
    data = json.loads(output)
    assert set(data['citations']) == {'民法第205條', CITATION, '銀行法第29條', '民法第205條第1項'}
    assert data['precedent_notes'] == [note]
    assert '民法第205條' in data['version_hints']
    assert '民法第205條第1項' in data['version_hints']
    assert data['adopted_citations'] == ['銀行法第29條', '民法第205條第1項']
    assert 'PRIVATE_DO_NOT_EXPORT' not in output
    with get_session(url) as session:
        assert session.query(CaseCitationCheck).count() == 0


def test_prepare_only_removes_private_fields_nested_in_elements_and_precedent_notes(review_cli, monkeypatch, capsys):
    from database.db import record_argument
    url, note, _ = review_cli
    with get_session(url) as session:
        record_argument(session, case_id='c1', side='plaintiff', stage=1, position='依法請求。', reasoning='公開論證。',
                        cited_statutes=['民法第205條'], cited_precedents=[CITATION], structured_json={
                            'items': [{'id': 'P1', 'label': '利息請求', 'kind': 'legal', 'status': 'asserted',
                                       'elements': [{'element': '契約成立', 'state': 'met', 'source': 'F1',
                                                     'internal_notes': {'secret': 'ELEMENT_PRIVATE_SENTINEL'}}],
                                       'citations': ['民法第205條'], 'needs_from_client': [], 'applicable_version': '108年版'}],
                            'position_basis': ['P1'], 'internal_notes': {},
                            'precedent_notes': [{**note, 'update_conditions': ['PRECEDENT_PRIVATE_SENTINEL'],
                                                 'extra': {'prep_responses': ['NESTED_RESPONSE_PRIVATE_SENTINEL']}}]})
    monkeypatch.setattr(sys, 'argv', ['main.py', 'verify', '--case-id', 'c1', '--prepare-only'])
    with pytest.raises(SystemExit) as exited:
        main.main()
    assert exited.value.code == 0
    output = capsys.readouterr().out
    assert 'PRIVATE_SENTINEL' not in output
    assert 'internal_notes' not in output and 'update_conditions' not in output and 'prep_responses' not in output
    data = json.loads(output)
    assert data['precedent_notes'][0]['quote'] == note['quote']
    assert '民法第205條' in data['version_hints']
