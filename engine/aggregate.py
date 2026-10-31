"""機械聚合層:攻防弱點彙整與立場位移統計。

純函數、不碰 DB、不呼叫 LLM——同 DebateSystem 的邊界原則，法官 Stage 4 的判決敘述
不得偏離這裡算出來的錨點方向(見 database/schema.py 的 Verdict.mechanical_anchor_json)。

輸入的每個 argument 皆為 dict，欄位對應 database.schema.DebateArgument 落地後的內容
(cited_statutes/cited_precedents 已由呼叫端從 JSON 字串解析為 list，本檔案不處理 JSON)。
"""

VALID_SIDES = ("plaintiff", "defendant")


def compile_weak_points(stage3_arguments):
    """stage3_arguments: list of {side, reasoning, falsifier} → 排序過的弱點清單。

    每一方在 stage3 的 falsifier(「若對方補上何種證據，我方將讓步」)本質上就是
    這一方案件的弱點所在，機械彙整、不做語意判斷。排序鍵:有 falsifier 的排前面
    (代表這一方有明確、可稽核的弱點)，同層再依 side 字母序排列，確保結果決定性。
    """
    if not stage3_arguments:
        raise ValueError("stage3_arguments 不可為空")
    points = []
    for arg in stage3_arguments:
        side = arg.get("side")
        if side not in VALID_SIDES:
            raise ValueError(f"非法 side: {side}")
        points.append({
            "side": side,
            "falsifier": arg.get("falsifier"),
            "response_excerpt": arg.get("reasoning"),
        })
    points.sort(key=lambda p: (p["falsifier"] is None, p["side"]))
    return points


def disagreement(stage1_arguments, stage3_arguments):
    """依「引用法條/判例集合」在 stage1→stage3 間的變化量，衡量各方立場位移程度。

    position/reasoning 為自由文字，非結構化方向欄位(不同於 DebateSystem 的 Bullish/
    Bearish/Neutral)，無法在不呼叫 LLM 的前提下做語意比對；改用兩階段引用集合的
    Jaccard 距離作為機械可算的位移代理指標——新增/放棄的法律依據代表實質論證變化，
    單純用字遣詞不同則不計入。回傳 {side: drift_ratio}，drift_ratio 範圍 0-1，
    0 代表兩階段引用集合完全相同、1 代表完全不重疊。單方缺席任一階段時該方回傳 None。
    """
    def by_side(arguments):
        result = {}
        for arg in arguments:
            side = arg.get("side")
            if side not in VALID_SIDES:
                raise ValueError(f"非法 side: {side}")
            citations = set(arg.get("cited_statutes") or []) | set(arg.get("cited_precedents") or [])
            result[side] = citations
        return result

    s1 = by_side(stage1_arguments)
    s3 = by_side(stage3_arguments)

    drift = {}
    for side in VALID_SIDES:
        if side not in s1 or side not in s3:
            drift[side] = None
            continue
        set1, set3 = s1[side], s3[side]
        if not set1 and not set3:
            drift[side] = 0.0
            continue
        union = set1 | set3
        intersection = set1 & set3
        drift[side] = round(1 - len(intersection) / len(union), 4)
    return drift


def aggregate_role_items(arguments, represented_side, questions=None, prep_items=None, procedural_issues=None):
    """v2 聚合：只取公開結構化欄位，不複製任何內部備註。"""
    from engine.verify import parse_citation
    opponent = next(s for s in VALID_SIDES if s != represented_side)
    pending = {h: [] for h in ('own_client', 'opponent', 'third_party')}
    conditions, changes = [], []
    final = [a for a in arguments if a['stage'] == 3]

    def add_pending(holder, text, source, item=None, hypothesis=False):
        pending[holder].append({'id': f'pending:{holder}:{len(pending[holder])+1}', 'holder': holder,
                                'text': text, 'source': source, 'item': item,
                                'qualification': '待確認', 'is_hypothesis': hypothesis})

    for arg in sorted(final, key=lambda a: a['side']):
        side = arg['side']
        for item in arg.get('items', []):
            ref = f'{side}:{item["id"]}'
            needs = item.get('needs_from_client', [])
            for need in needs:
                holder = need.get('holder', 'own_client' if side == represented_side else 'opponent') if isinstance(need, dict) else ('own_client' if side == represented_side else 'opponent')
                text = need.get('text', '') if isinstance(need, dict) else need
                add_pending(holder, text, f'{ref}@S3', ref, side == opponent)
            if item.get('status') == 'to_confirm' and not needs:
                add_pending('own_client' if side == represented_side else 'opponent', item['label'], f'{ref}@S3', ref, side == opponent)
            for element in item.get('elements', []):
                if element.get('state') == 'unknown':
                    add_pending('own_client' if side == represented_side else 'opponent', element['element'], f'{ref}@S3', ref, side == opponent)
        if side == opponent:
            for condition in arg.get('defeat_conditions', []):
                conditions.append({'id': f'defeat:{opponent}:{len(conditions)+1}', 'item': condition['item'],
                                   'condition': condition.get('condition') or condition.get('text'),
                                   'label': '代理方要準備的證據', 'is_hypothesis': True})
    for question in questions or []:
        if question.get('target_side') == represented_side and question.get('question_type') == 'factual':
            add_pending('own_client', question['question_text'], f'question:{question["id"]}')
    for prep in prep_items or []:
        add_pending(prep['holder'], prep['hypothesis'] + '；準備：' + prep['prepare'], prep['id'], prep['affects'], True)
    prior = {}
    for arg in sorted(arguments, key=lambda a: (a['stage'], a['side'])):
        for item in arg.get('items', []):
            key = f'{arg["side"]}:{item["id"]}'
            if key in prior and prior[key][1] != item['status']:
                changes.append({'item': key, 'from_stage': prior[key][0], 'to_stage': arg['stage'],
                                'from_status': prior[key][1], 'to_status': item['status'],
                                'withdraw_reason': item.get('withdraw_reason')})
            prior[key] = (arg['stage'], item['status'])

    def canonical(citation):
        parsed = parse_citation(citation)
        if parsed['type'] == 'statute':
            return ('statute', parsed['law_name'], parsed['article_no'])
        if parsed['type'] == 'judgment':
            return ('judgment', parsed['jyear'], parsed['jcase'], parsed['jno'])
        return ('unknown', citation)

    differences = {}
    for side in VALID_SIDES:
        first = next((a for a in arguments if a['side'] == side and a['stage'] == 1), None)
        last = next((a for a in arguments if a['side'] == side and a['stage'] == 3), None)
        if first is None or last is None:
            differences[side] = None
            continue
        before = {canonical(c) for c in first.get('cited_statutes', []) + first.get('cited_precedents', [])}
        after = {canonical(c) for c in last.get('cited_statutes', []) + last.get('cited_precedents', [])}
        differences[side] = round(1-len(before & after)/len(before | after), 4) if before | after else 0.0
    return {'defeat_conditions': conditions, 'pending': pending, 'status_changes': changes,
            'citation_set_change': differences, 'procedural_issues': procedural_issues or {}}
