"""職責分離協議的確定性驗證與投影；本模組不呼叫模型。"""
import copy
import json
import re

from database.schema import Case, DebateArgument, CourtQuestion, JudgeBundle, Verdict, PleadingDraft, CaseCitationCheck

PROTOCOL_VERSION = 'v2-role-separation-2026-10-31'
SIDES = ('plaintiff', 'defendant')
HOLDERS = ('own_client', 'opponent', 'third_party')
POSITION_MAX = 200
ARGUMENT_MAX = 8000
DISCLAIMER = '本結果為爭點分析與書狀骨架初稿，非法院判決預測，語氣潤飾與正式訴狀撰寫仍需律師覆核。'
ITEM_REF = re.compile(r'(plaintiff|defendant):([A-Za-z][A-Za-z0-9_-]*)(?:@S([123]))?')
FACT_REF = re.compile(r'\bF\d+\b')
ADMISSIONS = re.compile(r'自承|自認|坦承')
QUALIFIER = re.compile(r'待確認|若|假設|尚未確認|有待確認')


def decoded(value, default=None):
    if value is None:
        return {} if default is None else copy.deepcopy(default)
    return json.loads(value) if isinstance(value, str) else copy.deepcopy(value)


def public_copy(value):
    """公開投影使用白名單欄位後，連帶移除任意巢狀位置的私密欄位。"""
    private = {'internal_notes', 'update_conditions', 'prep_responses', 'prep_items'}
    if isinstance(value, dict):
        return {key: public_copy(v) for key, v in value.items() if key not in private}
    if isinstance(value, list):
        return [public_copy(v) for v in value]
    return copy.deepcopy(value)


def case_row(session, case_id):
    case = session.query(Case).filter_by(case_id=case_id).one_or_none()
    if case is None:
        raise ValueError(f'找不到案件 {case_id}')
    return case


def is_v2(case):
    return case is not None and case.represented_side in SIDES


def procedure_warning(claim_amount=None, claims=''):
    if claim_amount is not None and (isinstance(claim_amount, bool) or not isinstance(claim_amount, int) or claim_amount < 0):
        raise ValueError('claim_amount 必須為非負整數或 null')
    if claim_amount is None:
        procedure = '待確認'
        message = '金額未定，程序別待確認'
    elif claim_amount <= 100000:
        procedure, message = '小額', '依請求金額可能適用小額程序，請使用者確認'
    elif claim_amount <= 500000:
        procedure, message = '簡易', '依請求金額可能適用簡易程序，請使用者確認'
    else:
        procedure, message = '通常', '依請求金額屬通常程序範圍'
    warnings = [] if procedure == '通常' else [message]
    if any(word in claims for word in ('原起訴', '變更聲明', '變更訴之聲明')):
        warnings.append('本系統只支援起訴前；請確認聲明未混入既有訴訟程序用語')
    return {'procedure': procedure, 'message': message, 'warnings': warnings,
            'legal_basis': ['民事訴訟法第427條', '民事訴訟法第436條之8'],
            'case_type_note': '民事訴訟法第427條第2項另依案件類型適用簡易程序，須由律師確認，本程式不自動判斷。'}


def facts_for(case):
    represented = case.represented_side or 'plaintiff'
    groups = {g: getattr(case, g, None) or '' for g in ('uncontested_facts', 'plaintiff_facts', 'defendant_facts')}
    if not any(groups.values()):
        groups[f'{represented}_facts'] = case.facts_summary
    result = []
    for group, raw in groups.items():
        if group == 'uncontested_facts':
            attribution = '使用者判斷：預期雙方不爭執（多為書證）；不是已確認之雙方自認'
        elif group == f'{represented}_facts':
            attribution = ('原告' if represented == 'plaintiff' else '被告') + '當事人陳述或其提出的書證'
        else:
            attribution = ('原告轉述' if represented == 'plaintiff' else '被告轉述') + '或書證所載的對方說法，非對方親述'
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.match(r'^〔書證[：:]([^〕]*)〕\s*(.*)$', line)
            result.append({'id': f'F{len(result)+1}', 'text': match[2] if match else line,
                           'source': '書證' if match else '陳述', 'source_name': match[1] if match else None,
                           'group': group, 'attribution': attribution})
    return result


def all_arguments(session, case_id):
    return session.query(DebateArgument).filter_by(case_id=case_id).order_by(DebateArgument.stage, DebateArgument.side).all()


def item_index(session, case_id, stage=None):
    result = {}
    for row in all_arguments(session, case_id):
        if stage is not None and row.stage != stage:
            continue
        for item in decoded(row.structured_json).get('items', []):
            result[f'{row.side}:{item["id"]}@S{row.stage}'] = item
            result[f'{row.side}:{item["id"]}'] = item
    return result


def resolve_ref(ref, index, *, require_stage=False):
    if not isinstance(ref, str) or not ITEM_REF.fullmatch(ref) or (require_stage and '@S' not in ref):
        raise ValueError(f'item 參照格式錯誤：{ref}，應為 side:id' + ('@S1/2/3' if require_stage else ''))
    if ref not in index:
        raise ValueError(f'不存在的 item 參照：{ref}')
    return index[ref]


def needs_rows(item, default_holder):
    out = []
    needs = item.get('needs_from_client', [])
    if not isinstance(needs, list):
        raise ValueError('needs_from_client 必須是陣列')
    for need in needs:
        if isinstance(need, str):
            out.append({'text': need, 'holder': default_holder})
        elif isinstance(need, dict) and need.get('holder') in HOLDERS and isinstance(need.get('text'), str) and need['text'].strip():
            out.append(copy.deepcopy(need))
        else:
            raise ValueError('needs_from_client 每筆須有 text 與合法 holder')
    return out


def factual_assertion(item):
    return (item.get('status') == 'asserted' and item.get('factual_statement') is True
            and item.get('kind') != 'factual_hypothesis'
            and bool(item.get('elements'))
            and all(e.get('state') == 'met' and FACT_REF.fullmatch(str(e.get('source', ''))) for e in item['elements']))


def validate_argument(session, case, side, stage, position, argument, data):
    if not isinstance(data, dict):
        raise ValueError('新協議須提供 structured_json 物件（含 items、position_basis、internal_notes）')
    if not isinstance(position, str) or not position.strip() or len(position) > POSITION_MAX:
        raise ValueError(f'position 須為非空字串，上限 {POSITION_MAX} 字')
    if not isinstance(argument, str) or len(argument) > ARGUMENT_MAX:
        raise ValueError(f'argument 上限 {ARGUMENT_MAX} 字')
    items = data.get('items')
    if not isinstance(items, list) or not items:
        raise ValueError('items 須為非空陣列')
    if not isinstance(data.get('position_basis'), list):
        raise ValueError('position_basis 必須為 item id 陣列')
    if not isinstance(data.get('internal_notes'), (dict, list, str)):
        raise ValueError('internal_notes 為必要欄位')
    facts = {f['id'] for f in facts_for(case)}
    ids = set()
    own = side == case.represented_side
    if own and stage == 2:
        prep_ids = {p['id'] for p in judge_data(session, case.case_id).get('prep_items', [])}
        notes = data['internal_notes']
        responses = notes.get('prep_responses', []) if isinstance(notes, dict) else []
        if isinstance(responses, dict):
            response_ids = {key for key, value in responses.items() if str(value).strip()}
        elif isinstance(responses, list):
            response_ids = {r.get('id') or r.get('prep_id') for r in responses if isinstance(r, dict) and str(r.get('response') or r.get('text') or '').strip()}
        else:
            response_ids = set()
        if prep_ids - response_ids:
            raise ValueError(f'internal_notes.prep_responses 須逐筆回應準備清單：{sorted(prep_ids-response_ids)}')
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', item['id']):
            raise ValueError('item id 格式不合法')
        if item['id'] in ids:
            raise ValueError(f'item id 重複：{item["id"]}')
        ids.add(item['id'])
        if not isinstance(item.get('label'), str) or not item['label'].strip():
            raise ValueError('item label 必填')
        if item.get('kind') not in ('legal', 'evidence_gap', 'factual_hypothesis'):
            raise ValueError('item kind 不合法')
        if item.get('status') not in ('asserted', 'to_confirm', 'withdrawn'):
            raise ValueError('item status 不合法')
        if not isinstance(item.get('elements'), list):
            raise ValueError('elements 必須是陣列')
        for element in item['elements']:
            if not isinstance(element, dict) or not element.get('element') or element.get('state') not in ('met', 'unmet', 'unknown'):
                raise ValueError('element/state 不合法')
            source = element.get('source')
            if source == 'inference':
                if not any(isinstance(element.get(k), str) and element[k].strip() for k in ('inference', 'basis', 'reason', 'explanation')):
                    raise ValueError('inference 須附一句推論根據')
            elif source not in facts:
                raise ValueError(f'不存在的事實編號：{source}')
        if not isinstance(item.get('citations'), list) or not all(isinstance(c, str) for c in item['citations']):
            raise ValueError('items.citations 必須為字串陣列')
        item['needs_from_client'] = needs_rows(item, 'own_client' if own else 'opponent')
        if not own and item['kind'] == 'factual_hypothesis' and item['status'] not in ('to_confirm', 'withdrawn'):
            raise ValueError('對造 factual_hypothesis 必須維持 to_confirm')
    by_id = {i['id']: i for i in items}
    for ref in data['position_basis']:
        if ref not in by_id or by_id[ref]['status'] != 'asserted' or any(e['state'] == 'unknown' for e in by_id[ref]['elements']):
            raise ValueError(f'position_basis 不得引用不存在、待確認或含 unknown 要件的 item：{ref}')
    previous = session.query(DebateArgument).filter_by(case_id=case.case_id, side=side, stage=stage-1).one_or_none() if stage > 1 else None
    if stage > 1 and previous is None:
        raise ValueError(f'須先完成 {side} Stage {stage-1}')
    prior = {i['id']: i for i in decoded(previous.structured_json).get('items', [])} if previous else {}
    missing = set(prior) - ids
    if missing:
        raise ValueError(f'後續階段 item 不得消失：{sorted(missing)}')
    index = item_index(session, case.case_id)
    for item in items:
        before = prior.get(item['id'])
        if item['status'] == 'withdrawn' and (before is None or before['status'] != 'withdrawn'):
            reason = item.get('withdraw_reason')
            if not isinstance(reason, dict) or reason.get('type') not in ('record_negates', 'opponent_defeats', 'strategy'):
                raise ValueError('withdraw_reason 僅允許 record_negates/opponent_defeats/strategy；資料不足不是撤回理由')
            if reason['type'] == 'record_negates':
                refs = reason.get('fact_ids', [])
                if not refs or any(f not in facts for f in refs):
                    raise ValueError('withdraw_reason.record_negates 須附存在的事實編號')
            elif reason['type'] == 'opponent_defeats':
                refs = reason.get('item_ids') or reason.get('opponent_item_ids') or reason.get('items') or []
                if not refs:
                    raise ValueError('withdraw_reason.opponent_defeats 須附對方 item id')
                for ref in refs:
                    resolve_ref(ref, index)
                    if not ref.startswith(('defendant' if side == 'plaintiff' else 'plaintiff') + ':'):
                        raise ValueError('opponent_defeats 必須引用對方 item')
            elif not own or not str(reason.get('explanation') or reason.get('reason') or '').strip():
                raise ValueError('strategy 策略撤回僅限代理方，且須附說明')
        if before and before['status'] == 'to_confirm' and item['status'] == 'asserted':
            old_sources = {e.get('source') for e in before.get('elements', [])}
            new_sources = {e.get('source') for e in item['elements'] if e.get('state') == 'met'} - old_sources
            if not new_sources.intersection(facts):
                raise ValueError('to_confirm 變 asserted 須有新增事實編號支持，未知不得改為確定')
    conditions = data.get('defeat_conditions', [])
    if not isinstance(conditions, list):
        raise ValueError('defeat_conditions 必須為陣列')
    if own and conditions:
        raise ValueError('代理方 update_conditions 只可寫在 internal_notes，不得公開 defeat_conditions')
    for condition in conditions:
        if not isinstance(condition, dict):
            raise ValueError('defeat_conditions 每筆須有 item 與 condition')
        ref = condition.get('item') or condition.get('item_id')
        local = ref.split(':')[-1] if isinstance(ref, str) else None
        if local not in by_id or (':' in ref and not ref.startswith(side + ':')) or not str(condition.get('condition') or condition.get('text') or '').strip():
            raise ValueError('defeat_conditions 須指自己的 item 並附條件')
        condition['item'] = f'{side}:{local}'
    if stage == 3 and any(not isinstance(data.get(k), str) for k in ('claim_statement', 'rebuttal')):
        raise ValueError('Stage3 必須分別提供 claim_statement 與 rebuttal 字串')
    from engine.verify import validate_precedent_notes, JUDGMENT_CITATION_RE
    precedents = list(dict.fromkeys(data.get('cited_precedents', []) +
                                   [c for item in items for c in item.get('citations', []) if JUDGMENT_CITATION_RE.search(c)]))
    notes = data.get('precedent_notes', [])
    if not isinstance(notes, list):
        raise ValueError('precedent_notes 必須為陣列')
    from engine.verify import parse_citation
    def key(c):
        p = parse_citation(c)
        return (p.get('jyear'), p.get('jcase'), p.get('jno'))
    for citation in precedents:
        if not any(key(n.get('citation', '')) == key(citation) for n in notes):
            raise ValueError(f'判例 {citation} 缺 precedent_notes；未讀全文者只能放 precedent_leads')
    data['precedent_checks'] = validate_precedent_notes(notes)
    data['protocol_version'] = PROTOCOL_VERSION
    return data


def validate_question(session, case, question_text, target_side, based_on, question_type):
    if question_type not in ('legal', 'factual'):
        raise ValueError('question_type 必須為 legal 或 factual')
    if target_side != case.represented_side and question_type == 'factual':
        raise ValueError('對造模擬不得收到 factual 事實題，應轉為代理方 prep_items')
    refs = [m.group(0) for m in ITEM_REF.finditer(based_on if isinstance(based_on, str) else json.dumps(based_on))]
    if not refs:
        raise ValueError('based_on 須含存在的 side:item id 與說明')
    index = item_index(session, case.case_id, stage=1)
    items = [resolve_ref(ref, index) for ref in refs]
    if any(not ref.startswith(target_side + ':') for ref in refs):
        raise ValueError('based_on 須指向被訊問方的 item')
    if ADMISSIONS.search(question_text) and not all(factual_assertion(i) for i in items):
        raise ValueError('自承／自認／坦承只可指 asserted 的事實陳述，不能指假設或推論')
    return {'review_flags': [w for w in ('有無證據', '是否持有', '為何') if w in question_text]}


def validate_judge_bundle(session, case, data):
    index = item_index(session, case.case_id, stage=1)
    if not isinstance(data.get('questions'), list):
        raise ValueError('questions 必須為陣列')
    prep_ids = set()
    for prep in data.get('prep_items', []):
        if not isinstance(prep, dict) or not prep.get('id') or prep['id'] in prep_ids or prep.get('is_hypothesis') is not True or prep.get('holder') not in HOLDERS:
            raise ValueError('prep_items 須有唯一 id、is_hypothesis=true 與合法 holder')
        prep_ids.add(prep['id'])
        resolve_ref(prep.get('affects'), index)
        if not prep.get('hypothesis') or not prep.get('prepare'):
            raise ValueError('prep_items 須有 hypothesis 與 prepare')
    issue_ids = set()
    for issue in data.get('issues', []):
        if not isinstance(issue, dict) or not issue.get('issue_id') or issue['issue_id'] in issue_ids or not issue.get('label'):
            raise ValueError('issues 須有唯一 issue_id 與 label')
        issue_ids.add(issue['issue_id'])
        refs = issue.get('items') or issue.get('related_items') or issue.get('item_ids') or []
        if not refs:
            raise ValueError('issue 須附相關 item id')
        for ref in refs:
            resolve_ref(ref, index)
    for point in data.get('uncontested_points', []):
        if not isinstance(point, dict):
            raise ValueError('uncontested_points 須為含 text 與 item_ids 的結構化事實')
        refs = point.get('item_ids') or point.get('items') or []
        if len(refs) < 2 or not any(r.startswith('plaintiff:') for r in refs) or not any(r.startswith('defendant:') for r in refs):
            raise ValueError('不爭執須由雙方 asserted 同內容事實支持，單方沉默不算')
        items = [resolve_ref(ref, index) for ref in refs]
        if not all(factual_assertion(i) for i in items) or len({i.get('fact_text', i['label']) for i in items}) != 1:
            raise ValueError('不爭執須雙方 asserted 且內容一致的事實陳述')


def public_argument(row):
    data = decoded(row.structured_json)
    return public_copy({'side': row.side, 'stage': row.stage, 'position': row.position, 'argument': row.reasoning,
            'items': data.get('items', []), 'position_basis': data.get('position_basis', []),
            'claim_statement': data.get('claim_statement'), 'rebuttal': data.get('rebuttal'),
            'defeat_conditions': data.get('defeat_conditions', []),
            'cited_statutes': decoded(row.cited_statutes, []), 'cited_precedents': decoded(row.cited_precedents, []),
            'precedent_notes': data.get('precedent_notes', []), 'citation_warnings': data.get('citation_warnings', [])})


def role_view(session, case_id, role):
    if role not in (*SIDES, 'judge'):
        raise ValueError('role 必須為 plaintiff/defendant/judge')
    case = case_row(session, case_id)
    has_client = role in SIDES and role == (case.represented_side or 'plaintiff')
    rows = all_arguments(session, case_id)
    arguments = []
    for row in rows:
        if role in SIDES and row.side != role:
            continue  # 對造內容由獨立 summary 檔供應；避免依落地順序破壞 Stage1 盲判。
        arg = public_argument(row)
        if role == row.side:
            arg['internal_notes'] = decoded(row.structured_json).get('internal_notes', {})
        arguments.append(arg)
    out = {'case_id': case_id, 'case_type': case.case_type, 'represented_side': case.represented_side,
           'protocol_version': case.protocol_version or 'legacy', 'role': role, 'has_client': has_client,
           'role_description': ('我方代理人，有使用者當事人' if has_client else '法官：整理爭點，不得把沉默當不爭執' if role == 'judge' else '對造模擬（紅隊），沒有當事人；只提出法律攻擊、證據缺口與待確認假設'),
           'procedure_stage': '起訴前', 'facts': facts_for(case), 'claims': case.claims,
           'claim_amount': case.claim_amount, 'procedure': procedure_warning(case.claim_amount, case.claims), 'arguments': arguments}
    if role == 'judge' and all(any(r.stage == 3 and r.side == s for r in rows) for s in SIDES):
        from database.db import finalize_case
        anchors = finalize_case(session, case_id=case_id)
        out['anchors'] = judge_anchor_projection(anchors)
        out['issues'] = issues_with_grades(session, case_id)
    return out


def argument_summary(session, case_id, side, stage):
    row = session.query(DebateArgument).filter_by(case_id=case_id, side=side, stage=stage).one_or_none()
    if row is None:
        raise ValueError(f'找不到 {side} Stage{stage} 論證')
    arg = public_argument(row)
    unconfirmed = []
    for item in arg['items']:
        unknown = [e for e in item.get('elements', []) if e.get('state') == 'unknown']
        if item['status'] == 'to_confirm' or unknown:
            unconfirmed.append({'item': f'{side}:{item["id"]}', 'status': item['status'], 'label': item['label'],
                                'qualification': '待確認', 'elements': unknown, 'needs_from_client': item.get('needs_from_client', [])})
    return {'case_id': case_id, 'side': side, 'stage': stage, 'position': arg['position'],
            'items': [{k: i.get(k) for k in ('id', 'label', 'kind', 'status')} for i in arg['items']],
            'unconfirmed_facts': unconfirmed, 'defeat_conditions': arg['defeat_conditions'],
            'citations': arg['cited_statutes'] + arg['cited_precedents']}


def judge_data(session, case_id):
    row = session.query(JudgeBundle).filter_by(case_id=case_id).one_or_none()
    return decoded(row.structured_json) if row else {}


def preparation_materials(session, case_id, role):
    case = case_row(session, case_id)
    if role != case.represented_side:
        raise ValueError('準備清單僅提供代理方，不提供對造模擬或法官')
    return {'case_id': case_id, 'role': role, 'prep_items': judge_data(session, case_id).get('prep_items', [])}


def judge_anchor_projection(anchors):
    return {k: copy.deepcopy(anchors.get(k, {} if k in ('pending', 'procedural_issues') else [])) for k in ('defeat_conditions', 'pending', 'procedural_issues')}


def reference_grade(own_items, opponent_items):
    if not own_items:
        return '中'
    if any(any(e.get('state') == 'unmet' or e.get('source') == 'inference' for e in i.get('elements', [])) or
           (i.get('status') == 'withdrawn' and i.get('withdraw_reason', {}).get('type') == 'opponent_defeats') for i in own_items):
        return '低'
    if any(i.get('status') == 'to_confirm' or any(e.get('state') == 'unknown' for e in i.get('elements', [])) for i in own_items) or any(i.get('status') == 'asserted' for i in opponent_items):
        return '中'
    if all(i.get('status') == 'asserted' and bool(i.get('elements')) and all(e.get('state') == 'met' and FACT_REF.fullmatch(str(e.get('source', ''))) for e in i['elements']) for i in own_items):
        return '高'
    return '中'


def issues_with_grades(session, case_id):
    case = case_row(session, case_id)
    index = item_index(session, case_id, stage=3)
    result = []
    for raw in judge_data(session, case_id).get('issues', []):
        issue = copy.deepcopy(raw)
        refs = issue.get('items') or issue.get('related_items') or issue.get('item_ids') or []
        refs = [ref.split('@S', 1)[0] for ref in refs]
        own = [index[r] for r in refs if r in index and r.startswith(case.represented_side + ':')]
        other = [index[r] for r in refs if r in index and not r.startswith(case.represented_side + ':')]
        issue['reference_grade'] = reference_grade(own, other)
        result.append(issue)
    return result


def validate_verdict(session, case, data, anchors):
    from engine.verify import JUDGMENT_CITATION_RE, parse_citation, validate_precedent_notes
    notes = data.get('precedent_notes', [])
    for citation in data.get('citations_used', []):
        if JUDGMENT_CITATION_RE.search(citation):
            parsed = parse_citation(citation)
            if not any(parse_citation(n.get('citation', '')) == parsed for n in notes):
                raise ValueError(f'評估判例 {citation} 缺本輪 precedent_notes 文件身分與原文摘句')
    if notes:
        data['precedent_checks'] = validate_precedent_notes(notes)
    index = item_index(session, case.case_id)
    facts = {f['id'] for f in facts_for(case)}
    issues = data.get('issues')
    if not isinstance(issues, list):
        raise ValueError('評估必須提供 issues 陣列')
    known = {i['issue_id']: i for i in issues_with_grades(session, case.case_id)}
    if set(i.get('issue_id') for i in issues) != set(known):
        raise ValueError('評估 issues 必須沿用且涵蓋法官整理的 issue_id')
    for issue in issues:
        grade = known[issue['issue_id']]['reference_grade']
        if issue.get('reference_grade') not in (None, grade):
            raise ValueError('reference_grade 由程式決定，不得自行改寫')
        issue['reference_grade'] = grade
        if issue.get('grade') not in ('高', '中', '低') or (issue['grade'] != grade and not str(issue.get('grade_reason') or '').strip()):
            raise ValueError('grade 不合法或與 reference_grade 不同但缺 grade_reason')
        for key in ('own_items', 'opponent_items'):
            for ref in issue.get(key, []):
                resolve_ref(ref, index, require_stage=True)
                if ref.startswith(case.represented_side + ':') != (key == 'own_items'):
                    raise ValueError(f'{key} 引用錯方；own_items 只能為代理方，opponent_items 只能為對造')
        if any(f not in facts for f in issue.get('basis', [])):
            raise ValueError('評估 basis 含不存在的事實編號')
    text = '\n'.join(str(data.get(k, '')) for k in ('summary', 'verdict_main_text', 'verdict_analysis', 'verdict_reasoning'))
    # 每一段可讀文字單獨核對；JSON 陣列不能把下一句的限定語借給上一句。
    strings = []
    def collect(value):
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for k, v in value.items():
                if k not in ('mechanical_anchor_json', 'internal_notes', 'reference_grade', 'ref'):
                    collect(v)
        elif isinstance(value, list):
            for v in value:
                collect(v)
    collect(data)
    for string in strings:
        for ref in ITEM_REF.finditer(string):
            resolve_ref(ref.group(0), index, require_stage=True)
        for sentence in re.split(r'[。！？\n]', string):
            refs = [m.group(0) for m in ITEM_REF.finditer(sentence)]
            resolved = [resolve_ref(ref, index, require_stage=True) for ref in refs]
            if any(i.get('status') == 'to_confirm' for i in resolved) and not QUALIFIER.search(sentence) and not ITEM_REF.fullmatch(sentence.strip()):
                raise ValueError('評估提到 to_confirm 項目時須保留「待確認」或「若」')
            if ADMISSIONS.search(sentence) and (not resolved or not all(factual_assertion(i) for i in resolved)):
                raise ValueError('評估自承／自認／坦承須指 asserted 的事實陳述')
            if re.search(r'相互印證|互相印證|佐證', sentence):
                fs = set(FACT_REF.findall(sentence))
                if len(fs) < 2 or not fs.issubset(facts):
                    raise ValueError('相互印證／佐證須在同句列兩個不同且存在的事實編號')
            if ('→' in sentence or '轉為' in sentence or '改為' in sentence) and len(refs) >= 2:
                for left, right in zip(refs, refs[1:]):
                    a, b = ITEM_REF.fullmatch(left), ITEM_REF.fullmatch(right)
                    if a.group(1, 2) == b.group(1, 2) and a[3] != b[3] and index[left]['status'] == index[right]['status']:
                        raise ValueError('宣稱主張狀態改變，但 status_changes 無對應變化')
    responses = data.get('anchor_responses', [])
    if not isinstance(responses, list):
        raise ValueError('anchor_responses 必須為陣列')
    needed = {p['id'] for values in anchors.get('pending', {}).values() for p in values}
    needed.update(c['id'] for c in anchors.get('defeat_conditions', []))
    needed.update(p['id'] for p in anchors.get('procedural_issues', {}).get('issues', []))
    actual = {r.get('ref') for r in responses if isinstance(r, dict) and str(r.get('comment') or '').strip()}
    if needed - actual:
        raise ValueError(f'錨點覆蓋不足，缺少回應：{sorted(needed-actual)}')
    for ref in actual - needed:
        resolve_ref(ref, index, require_stage=True)
    data['quoted_items'] = {ref: public_copy(index[ref]) for string in strings for ref in [m.group(0) for m in ITEM_REF.finditer(string)]}
    return data


def validate_breakdown(session, case, breakdown):
    if not isinstance(breakdown, list):
        raise ValueError('claim_breakdown 必須為陣列')
    facts = {f['id'] for f in facts_for(case)}
    index = item_index(session, case.case_id)
    accepted, pending = [], []
    for raw in breakdown:
        part = copy.deepcopy(raw)
        if not isinstance(part, dict) or not part.get('name') or isinstance(part.get('amount'), bool) or not isinstance(part.get('amount'), int) or part['amount'] < 0:
            raise ValueError('claim_breakdown 須有 name 及非負整數 amount')
        ref = part.get('item')
        item = resolve_ref(ref, index, require_stage=True)
        if not ref.endswith('@S3'):
            raise ValueError('金額明細只能引用 Stage3 最終 item（@S3），不得用前輪狀態繞過最終撤回或待確認')
        if not ref.startswith(case.represented_side + ':'):
            raise ValueError('金額明細須引用代理方 item')
        basis = part.get('basis', [])
        if not isinstance(basis, list) or any(f not in facts for f in basis) or (not basis and not part.get('formula')):
            raise ValueError('金額明細 basis 須為存在的事實編號，basis/formula 至少一項')
        if item['status'] == 'to_confirm':
            part['note'] = '律師附註：待確認後再決定是否請求'
            pending.append(part)
        elif item['status'] != 'asserted':
            raise ValueError('金額明細 item 須 asserted，撤回項目不得列請求')
        else:
            accepted.append(part)
    total = sum(p['amount'] for p in accepted)
    warnings = []
    if case.claim_amount is not None and total != case.claim_amount:
        warnings.append(f'明細合計 {total} 元與案件請求金額 {case.claim_amount} 元不同，請確認')
    initial, final = procedure_warning(case.claim_amount), procedure_warning(total if breakdown else case.claim_amount)
    if initial['procedure'] != final['procedure']:
        warnings.append(f'明細加總後程序別由{initial["procedure"]}變為{final["procedure"]}，請確認')
    return {'items': accepted, 'pending': pending, 'total': total, 'warnings': warnings, 'procedure': final}


def build_report(session, case_id):
    from database.db import finalize_case, latest_party_checks
    from engine.party_issues import procedural_issues
    case = case_row(session, case_id)
    rows = all_arguments(session, case_id)
    complete = all(any(r.side == s and r.stage == 3 for r in rows) for s in SIDES)
    anchors = finalize_case(session, case_id=case_id) if complete else {'pending': {h: [] for h in HOLDERS}, 'defeat_conditions': [], 'status_changes': [], 'citation_set_change': {}}
    represented = case.represented_side or 'plaintiff'
    opponent = 'defendant' if represented == 'plaintiff' else 'plaintiff'
    final_opp = next((r for r in rows if r.side == opponent and r.stage == 3), None)
    verdict = session.query(Verdict).filter_by(case_id=case_id).one_or_none()
    checks = []
    for r in session.query(CaseCitationCheck).filter_by(case_id=case_id).order_by(CaseCitationCheck.id).all():
        try:
            support_note = json.loads(r.support_note) if r.support_note else None
        except (TypeError, ValueError):
            support_note = r.support_note
        checks.append({'citation_text': r.citation_text, 'status': r.status, 'source_file': r.source_file,
                       'checked_at': r.checked_at, 'verifier_run_id': r.verifier_run_id, 'support_note': support_note,
                       'lawyer_review': r.status in ('unsupported_law', 'version_unverified', 'needs_explanation')})
    items = []
    for item in decoded(final_opp.structured_json).get('items', []) if final_opp else []:
        items.append({**public_copy(item), 'prediction_label': '預測，非對方實際主張', 'qualification': '待確認' if item['status'] == 'to_confirm' else item['status']})
    pleadings = []
    for row in session.query(PleadingDraft).filter_by(case_id=case_id).order_by(PleadingDraft.id).all():
        pleadings.append({'id': row.id, 'side': row.side, 'draft_text': row.draft_text,
                          'claim_breakdown': decoded(row.claim_breakdown_json, {}), 'warnings': decoded(row.warnings_json, [])})
    return {'case_id': case_id, 'protocol_version': case.protocol_version or 'legacy', 'represented_side': represented,
            'pending': anchors.get('pending', {h: [] for h in HOLDERS}),
            'opponent_preview': {'label': '預測，非對方實際主張', 'items': items,
                                 'defeat_conditions': [{**c, 'prediction_label': '預測，非對方實際主張'} for c in anchors.get('defeat_conditions', [])],
                                 'prep_items': [{**p, 'prediction_label': '預測，非對方實際主張'} for p in judge_data(session, case_id).get('prep_items', [])]},
            'issues': decoded(verdict.structured_json).get('issues', []) if verdict else issues_with_grades(session, case_id),
            'quoted_items': decoded(verdict.structured_json).get('quoted_items', {}) if verdict else {},
            'own_internal_notes': [{'stage': r.stage, 'notes': decoded(r.structured_json).get('internal_notes', {})} for r in rows if r.side == represented],
            'pleadings': pleadings,
            'process': {'status_changes': anchors.get('status_changes', []), 'citation_set_change': anchors.get('citation_set_change', {}),
                        'citation_checks': checks, 'procedural_issues': procedural_issues(latest_party_checks(session, case_id))},
            'disclaimer': DISCLAIMER}


def render_report(report):
    lines = [f'案件 {report["case_id"]}：起訴前準備回報', '', '一、待確認與準備事項']
    for holder, label in (('own_client', '問當事人'), ('opponent', '對方可能有'), ('third_party', '向第三方或法院調閱')):
        lines.append(label)
        for pending in report['pending'].get(holder, []):
            lines.append(f'- 待確認 [{pending["id"]}] {pending.get("text", "")}')
    lines.extend(['', '二、對方可能怎麼打 × 我要準備什麼'])
    for item in report['opponent_preview']['items']:
        lines.append(f'- 預測，非對方實際主張 [{item["id"]}] {item["label"]}（{item["qualification"]}）')
    for key in ('defeat_conditions', 'prep_items'):
        for item in report['opponent_preview'][key]:
            lines.append('- 預測，非對方實際主張 ' + json.dumps(item, ensure_ascii=False))
    lines.extend(['', '三、逐爭點強弱表', json.dumps(report['issues'], ensure_ascii=False, indent=2),
                  '引用原文：' + json.dumps(report['quoted_items'], ensure_ascii=False, indent=2),
                  '', '四、我方內部備註', json.dumps(report['own_internal_notes'], ensure_ascii=False, indent=2),
                  '', '五、書狀骨架、金額明細與律師附註', json.dumps(report['pleadings'], ensure_ascii=False, indent=2),
                  '', '六、過程紀錄與律師待核', json.dumps(report['process'], ensure_ascii=False, indent=2), '', report['disclaimer']])
    return '\n'.join(lines)
