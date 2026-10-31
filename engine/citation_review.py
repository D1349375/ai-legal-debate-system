"""交叉驗證獨立查證 JSON 與同次機械查證；不自行判斷命題支持性。"""
import copy
import json
import re


REVIEW_STATUSES = {
    'published', 'needs_explanation', 'unsupported', 'unsupported_law', 'version_unverified',
    'not_found', 'ambiguous', 'network_error', 'unparseable', 'doc_type_mismatch', 'quote_not_found',
    'analogy_required', 'document_identity_unverified', 'invalid_precedent_note', 'invalid_document_date',
}


def propagate_version_hints(citations, hints):
    """同一條法規不同項款寫法，不得藉字串差異遺失歷史版本限制。"""
    from engine.verify import parse_citation, citation_warning
    result = copy.deepcopy(hints or {})
    historical = {}
    for citation in list(dict.fromkeys(list(citations) + list(result))):
        warning = citation_warning(citation, version_hint=result.get(citation))
        if warning and warning['status'] == 'version_unverified':
            parsed = parse_citation(citation)
            historical[(parsed['law_name'], parsed['article_no'])] = result.get(citation) or {'note': '歷史版本，律師待核', 'source_citation': citation}
    for citation in citations:
        parsed = parse_citation(citation)
        if parsed['type'] == 'statute' and (parsed['law_name'], parsed['article_no']) in historical:
            result[citation] = copy.deepcopy(historical[(parsed['law_name'], parsed['article_no'])])
    return result


def case_verification_inputs(session, case_id, candidate=None):
    """Step8 一次投影查證輸入；不解析每輪法條，不含角色內部備註。"""
    from database.schema import DebateArgument, Verdict
    from engine.role_protocol import case_row, public_copy
    case_row(session, case_id)
    if candidate is not None and (not isinstance(candidate, dict) or candidate.get('case_id', case_id) != case_id):
        raise ValueError('候選評估 case_id 與 --case-id 不一致')
    citations, notes, hints, adopted, contexts = [], {}, {}, [], []

    def add(citation):
        if isinstance(citation, str) and citation not in citations:
            citations.append(citation)

    def consume(data, side=None, stage=None, final=False):
        data = public_copy(data)
        for field in ('cited_statutes', 'cited_precedents', 'citations_used'):
            for citation in data.get(field, []):
                add(citation)
                if final and field == 'citations_used' and citation not in adopted:
                    adopted.append(citation)
        for note in data.get('precedent_notes', []):
            if isinstance(note, dict) and isinstance(note.get('citation'), str):
                add(note['citation'])
                notes[note['citation']] = copy.deepcopy(note)
        for item in data.get('items', []):
            item_citations = item.get('citations', [])
            explicit = {k: item[k] for k in ('version_hint', 'version', 'applicable_version', 'historical_version', 'version_note', 'law_version', 'statute_version') if item.get(k)}
            explicit_historical = any(str(value).lower() not in ('current', '現行', '現行法') for value in explicit.values())
            context = json.dumps({'label': item.get('label'), 'elements': item.get('elements'), **explicit}, ensure_ascii=False)
            historical = explicit_historical or bool(re.search(r'修正前|舊法|舊版|歷史版本|\d{2,4}\s*年(?:度)?版', context))
            for citation in item_citations:
                add(citation)
                contexts.append({'citation_text': citation, 'side': side, 'stage': stage, 'item': item.get('id'), 'proposition': item.get('label')})
                if historical:
                    hints[citation] = {'note': '歷史版本，律師待核', 'item': item.get('id'), 'context': context}

    for row in session.query(DebateArgument).filter_by(case_id=case_id).order_by(DebateArgument.stage, DebateArgument.side).all():
        data = json.loads(row.structured_json or '{}')
        data['cited_statutes'] = json.loads(row.cited_statutes or '[]')
        data['cited_precedents'] = json.loads(row.cited_precedents or '[]')
        consume(data, row.side, row.stage)
    verdict = session.query(Verdict).filter_by(case_id=case_id).one_or_none()
    if verdict:
        consume(json.loads(verdict.structured_json or '{}'), final=True)
    if candidate is not None:
        consume(candidate, final=True)
    return {'case_id': case_id, 'citations': citations, 'precedent_notes': list(notes.values()),
            'version_hints': propagate_version_hints(citations, hints), 'adopted_citations': adopted, 'citation_contexts': contexts}


def validate_review_payload(payload, case_id, citations, mechanical_results, adopted_citations=None):
    if not isinstance(payload, dict) or not case_id or payload.get('case_id') != case_id:
        raise ValueError('獨立查證 case_id 必須與 --case-id 相同')
    run_id = payload.get('verifier_run_id')
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError('獨立查證 verifier_run_id 為必填非空字串')
    checks = payload.get('checks')
    if not isinstance(checks, list) or len(set(citations)) != len(citations):
        raise ValueError('checks 必須為陣列，命令列引用不得重複')
    by_citation = {}
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get('citation_text'), str):
            raise ValueError('checks 每筆須有 citation_text 字串')
        citation = check['citation_text']
        if citation in by_citation:
            raise ValueError(f'獨立查證 citation_text 重複：{citation}')
        if check.get('status') not in REVIEW_STATUSES:
            raise ValueError(f'獨立查證 status 不合法：{check.get("status")}')
        if not isinstance(check.get('reason'), str) or not check['reason'].strip():
            raise ValueError(f'獨立查證 reason 必須為非空字串：{citation}')
        for field in ('existence', 'document_identity', 'supports_proposition'):
            value = check.get(field)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f'{field} 只能是 true、false 或 null')
        by_citation[citation] = check
    if set(by_citation) != set(citations) or len(checks) != len(citations):
        raise ValueError('checks 必須與本批命令列引用一一對應，不得缺漏或加入其他引用')
    mechanical = {r['citation_text']: r for r in mechanical_results}
    if set(mechanical) != set(citations) or len(mechanical_results) != len(citations):
        raise ValueError('機械查證結果與本批引用不一致')
    results = []
    for citation in citations:
        check, original = by_citation[citation], mechanical[citation]
        status = check['status']
        mechanical_status = original['status']
        if status == 'published':
            if mechanical_status not in ('published', 'needs_explanation'):
                raise ValueError(f'{citation} 機械查證為 {mechanical_status}，獨立查證不得升級為 published')
            if any(check.get(field) is False for field in ('existence', 'document_identity', 'supports_proposition')):
                raise ValueError(f'{citation} 查證判斷為 false，不得標 published')
            if original.get('source_type') == 'judgment':
                adopted = adopted_citations is None or citation in adopted_citations
                claims_support = check.get('supports_proposition') is True
                if (adopted or claims_support) and (not original.get('precedent_note') or not original.get('support_review_required') or not all(original.get(field) for field in ('doc_type', 'jtitle', 'full_text'))):
                    raise ValueError(f'{citation} 尚未完成判例文件身分與原文摘句檢查，僅存在性不能升級 published')
                if adopted and not all(check.get(field) is True for field in ('existence', 'document_identity', 'supports_proposition')):
                    raise ValueError(f'{citation} 判例 published 須 existence、document_identity、supports_proposition 全為 true')
        # 機械失敗不得被改寫成另一種成功或限制；其原始狀態必須留存。
        if mechanical_status not in ('published', 'needs_explanation'):
            status = mechanical_status
        result = copy.deepcopy(original)
        result.update(status=status, mechanical_status=mechanical_status, review_status=check['status'],
                      reason=check['reason'], support_note=check['reason'], support_reviewed=check.get('supports_proposition') is not None,
                      existence=check.get('existence'), document_identity=check.get('document_identity'),
                      supports_proposition=check.get('supports_proposition'))
        result['independent_review'] = copy.deepcopy(check)
        results.append(result)
    return run_id, results
