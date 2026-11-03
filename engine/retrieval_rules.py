"""各階段的檢索規則(retrieval-rules 指令的輸出)。

新框架的範本只放 {RETRIEVAL_RULES} 佔位符，由調度員以 `python main.py retrieval-rules --phase <階段>` 的輸出填入；
之後改規則只改這裡，範本不用動。預算數字讀 engine/search_log.PHASES，不另寫一份。
內容依 docs/zh/retrieval-phase3-handoff.md 第三節(2026-11-01 與使用者討論後定案的雙軌制檢索步驟)。

輸出會直接貼進角色 prompt：不含大括號(範本之後可能再經 str.format 填其他佔位符)；沒給 --case-dir 時路徑寫成
<快照資料夾>、<紀錄檔>，由範本另外給的 {RETRIEVAL_CACHE_DIR}、{SEARCH_LOG_PATH} 對應。
"""
from engine.search_log import PHASE_ALIASES, PHASES

SIDES = ('plaintiff', 'defendant')
SIDE_LABEL = {'plaintiff': '原告', 'defendant': '被告'}
# 不檢索的階段：法官(P3 爭點整理表、P6 診斷)與獨立查證；沒有預算，也不給紀錄檔
NO_SEARCH = {'p3': ('P3 爭點整理表', '法官'), 'p6': ('P6 診斷', '法官'), 'verify': ('獨立查證', '查證角色')}

TOP_DOWN = ("依訴之聲明，按請求權基礎的檢查順序列候選：契約 → 類似契約關係（締約上過失、無權代理）→ 無因管理 → "
            "物上請求權 → 不當得利 → 侵權行為。這是為了不漏掉路徑、依邏輯先後檢查，不是把侵權行為當保底；數個請求權可以競合")
ARTICLE_STEP = "用 article 讀選定請求權基礎的現行條文"
SEARCH_STEP = ("用 search-judgments 以「法條＋要件詞」搜（例如 --kw 民法第184條 --kw 相當因果關係）；官網沒有相似案件搜尋與"
               "相關度排序，要靠要件詞縮小範圍。加 --fetch 時看輸出最後「常一起引用的法條」，檢查有沒有漏掉該一起主張的補充性法條")
READ_STEP = "用 judgment 讀要引用的判決全文"
# 書狀交換流程:同一份判決常被不同 subagent 重複讀全文(2026-11-03 實跑一次 28 次、只有 11 份不同)。讀過全文就記筆記,
# 之後看筆記與段落摘錄;「本案讀過」一次就夠正式引用(verify --read-by 不分階段)
READ_NOTE_STEP = "用 judgment 讀要引用、本方還沒讀過全文的判決，讀完用 --save-note 記下要用的原句與命題"
REUSE_STEP = ("本方先前讀過全文的判決，用 judgment <字號> --kw <關鍵詞> 只看本方筆記與相關段落，不重讀全文"
              "（本方在本案讀過全文就可以正式引用）")
V2_NOTE_PHASES = ('p1', 'p2', 'p4', 'p5')  # 指令清單多列段落摘錄與記筆記

# 需要檢索的階段：sides 為可執行的角色(給 --side 時檢查)，issue 為是否每次都要加 --issue
SEARCH_RULES = {
    'p1': {'sides': ('plaintiff',), 'mode': '主要檢索', 'issue': False,
           'target': ["準備在起訴狀主張的請求權基礎（先位／備位），以及預想被告抗辯會攻擊的要件",
                      "列出但不打算主張的候選請求權基礎只用 article 讀條文，不搜判決",
                      "P1 的分析與撰狀共用同一個紀錄檔與預算。分析只搜不讀全文：候選判決的字號寫在公開論證，標「待撰狀讀全文」；"
                      "每個 subagent 讀的全文都留在自己的上下文，分析讀了也交不出摘句，撰狀還要重讀"],
           'steps': [TOP_DOWN, ARTICLE_STEP, SEARCH_STEP, "撰狀用 judgment 讀要引用的判決全文，讀完用 --save-note 記下要用的原句與命題（分析不做這一步）"]},
    'p2': {'sides': ('defendant',), 'mode': '主要檢索', 'issue': False,
           'target': ["起訴狀的請求權基礎與被告的抗辯（例如清償、抵銷、時效）",
                      "起訴狀引用的判決：先看角色檔 complaint.precedents 的摘句、命題與核對結果；"
                      "要爭執它的見解或自己也要引用時，撰狀才依字號用 judgment 讀全文",
                      "P2 的防禦分析與答辯狀撰狀共用同一個紀錄檔與預算（擴充的答辯劇本也是）。分析只搜不讀全文："
                      "要攻擊的起訴狀判決與搜到的候選判決，字號寫在公開論證，標「待撰狀讀全文」；"
                      "每個 subagent 讀的全文都留在自己的上下文，分析讀了也交不出摘句，撰狀還要重讀"],
           'steps': ["用 article 讀起訴狀的請求權基礎與抗辯所依據的現行條文",
                     SEARCH_STEP.replace("相當因果關係）", "相當因果關係），只搜有爭議的要件與抗辯"),
                     "撰狀用 judgment 讀要引用的判決全文，讀完用 --save-note 記下要用的原句與命題（分析不做這一步）"]},
    'p4': {'sides': SIDES, 'mode': '補充檢索', 'issue': True,
           'target': ["依爭點整理表的爭點補充，每次 search-judgments、judgment 都加 --issue <爭點id>",
                      "對方書狀引用的判決先看書狀角色檔的 precedents（摘句已比對全文、已獨立核對）；"
                      "要爭執它的見解或自己也要引用時，才用 judgment 讀全文",
                      "要改用或追加請求權基礎時，須先在書狀標記民事訴訟法第255條（訴之變更、追加），標記後才可為它新搜判決"],
           'steps': [REUSE_STEP, ARTICLE_STEP.replace("選定請求權基礎", "本爭點涉及"), SEARCH_STEP, READ_NOTE_STEP]},
    'p5': {'sides': SIDES, 'mode': '少量檢索', 'issue': True,
           'target': ["只深化既有爭點，每次 search-judgments、judgment 都加 --issue <爭點id>",
                      "不新增請求權基礎（這是系統為了收斂而設的限制，不是法律禁止引用新法條）"],
           'steps': [REUSE_STEP, "仍不足時才用 search-judgments 補搜既有爭點的要件", READ_NOTE_STEP]},
    'stage1': {'sides': SIDES, 'mode': '主要檢索（現行三輪，相容用）', 'issue': False,
               'target': ["本方的請求權基礎或抗辯所依據的條文與判決"],
               'steps': [TOP_DOWN, ARTICLE_STEP, SEARCH_STEP, READ_STEP]},
    'stage2': {'sides': SIDES, 'mode': '補充檢索（現行三輪，相容用）', 'issue': False,
               'target': ["回應對方上一輪的論點；優先用 judgment 讀對方引用的判決"],
               'steps': ["用 judgment 讀對方上一輪引用的判決", SEARCH_STEP, READ_STEP]},
}
SEARCH_RULES['stage3'] = {**SEARCH_RULES['stage2']}

# 2026-11-02 評估：最高法院「意旨參照」常引的舊判例(民國85年以前)在官網只有掃描檔，搜不到也讀不到；
# 但以判例字號為關鍵字，都搜得到援引它、幾乎逐字重述要旨的近年判決(15 則各 7～54 份)。
OLD_PRECEDENT_RULE = ("民國85年以前的裁判（多為舊判例，例如73年台上字第1173號）官網沒有可讀全文，不能正式引用。要用它的見解時，"
                      "用 search-judgments --kw 73年台上字第1173號（換成該字號）找援引它的近年判決，用 judgment 讀其中一份全文後"
                      "引用那份近年判決，摘句取它重述該見解的原句、命題不得比原句更廣；舊判例字號只放 precedent_leads。"
                      "查無援引的近年判決時，不要用這個見解，或寫「待確認」")

WHEN_TO_CITE = [
    "只在這四種情況引用法條：涵攝要件、爭執舉證責任、發動或反擊法定抗辯、回應法官闡明或切換請求權基礎",
    "只有涵攝或抗辯有爭議時才搜判決",
    "正式引用判決須本輪用 judgment 讀過全文，並附原文摘句與命題；沒讀過全文的判決不得正式引用。查證會核對本方是否"
    "用 judgment 讀過（search-judgments --fetch 只看到命中句，不算），沒讀過的回 not_read_by_side、不放行",
    OLD_PRECEDENT_RULE,
]
ON_FAILURE = [
    "retrieval_unavailable：官網連線失敗（指令已自動重試一次），不代表查無資料。相關內容寫「待確認」，不得用記憶充當"
    "查得結果；記憶中的判決只能放 precedent_leads，不能正式引用。不要自己反覆重試",
    "full_text_unavailable：連上官網但頁面無法辨認全文，不代表判決不存在或引用寫錯。這份判決本輪沒讀到全文，"
    "不得正式引用，相關內容寫「待確認」；民國85年以前的裁判一律沒有全文",
    "budget_exceeded：已達本階段預算，用已取得的結果；快照或快取已有的全文仍可用 judgment 讀",
    "ambiguous：同字號有多份文件，加 --doc-date YYYYMMDD 指定",
]
FORBIDDEN = [
    "上網只能透過上列 python main.py 指令；不得用 WebFetch、WebSearch",
    "不得用 Read、Glob、Grep 直接讀檢索快取、快照或檢索紀錄的資料夾，一律透過指令讀",
]


class UnknownPhase(ValueError):
    pass


def phase_names():
    """retrieval-rules 認得的階段名稱：search_log 的階段代碼與別名，加上不檢索的 p3、p6、verify。"""
    return sorted(PHASES) + sorted(PHASE_ALIASES) + list(NO_SEARCH)


def canonical_phase(phase):
    name = (phase or '').strip().lower()
    if name in NO_SEARCH:
        return name
    name = PHASE_ALIASES.get(name, name)
    return name if name in PHASES else None


def case_paths(code, side=None, case_dir=None):
    """案件資料夾 → 該角色本階段的快照資料夾、紀錄檔，以及查證與落地用的案件快照根目錄。路徑一律用 /。"""
    if not case_dir:
        return {}
    root = case_dir.replace('\\', '/').rstrip('/')
    paths = {'case_snapshot': f'{root}/retrieval_cache'}
    if code in SEARCH_RULES and side:
        paths.update(snapshot=f'{root}/retrieval_cache/{side}', log=f'{root}/search_logs/{side}_{code}.jsonl')
    return paths


def _bullets(lines):
    return [f"- {line}" for line in lines]


def _numbered(lines):
    return [f"{i}. {line}" for i, line in enumerate(lines, 1)]


def _exclude_args(exclude):
    return ''.join(f' --exclude {value}' for value in exclude)


def _search_text(code, side, paths, exclude):
    rule, (label, searches, fetches) = SEARCH_RULES[code], PHASES[code]
    who = SIDE_LABEL[side] if side else '、'.join(SIDE_LABEL[s] for s in rule['sides'])
    snapshot, log = paths.get('snapshot', '<快照資料夾>'), paths.get('log', '<紀錄檔>')
    issue = (' --issue <爭點id>' if rule['issue'] else ' [--issue <爭點id>]') + _exclude_args(exclude)
    where = (f"本角色快照資料夾 {snapshot}；本階段紀錄檔 {log}。以下指令照抄路徑，不要改成其他資料夾。" if paths.get('log') else
             "以下 <快照資料夾>、<紀錄檔> 是範本給你的本角色快照資料夾與本階段紀錄檔路徑，每個指令都要帶。")
    return [
        f"檢索規則：{label}（{who}）",
        f"檢索方式：{rule['mode']}",
        f"本階段預算：search-judgments 最多 {searches} 次；上網抓判決全文最多 {fetches} 份。快照或快取已有的全文、"
        "article、search-statutes 不計入；超過時指令會拒絕（budget_exceeded）。",
        "", "目標：", *_bullets(rule['target']),
        "", "步驟：", *_numbered(rule['steps']),
        "", "指令：", where,
        f"- 讀條文：python main.py article <法規名稱> <條號> --snapshot {snapshot} --log {log}",
        f"- 依關鍵字找條文：python main.py search-statutes --kw <關鍵字> [--law <法規名稱>] --log {log}",
        f"- 搜判決：python main.py search-judgments --kw <法條> --kw <要件詞> [--fetch <份數>] [--title <案由>] "
        f"--snapshot {snapshot} --log {log}{issue}",
        f"- 讀判決全文：python main.py judgment <字號> [--doc-date YYYYMMDD] --snapshot {snapshot} --log {log}{issue}",
        *([f"- 看筆記與相關段落（不算讀過全文）：python main.py judgment <字號> --kw <關鍵詞> --snapshot {snapshot} --log {log}{issue}",
           f"- 記筆記（讀過全文後）：python main.py judgment <字號> --save-note --quote \"<全文逐字原句>\" "
           f"--proposition \"<支持的命題>\" --snapshot {snapshot}{issue}"] if code in V2_NOTE_PHASES else []),
        "", "引用：", *_bullets(WHEN_TO_CITE),
        "", "檢索失敗時：", *_bullets(ON_FAILURE),
        "", "禁止：", *_bullets(FORBIDDEN + ["不得使用對造的快照資料夾或紀錄檔"]),
    ]


def _no_search_text(code, paths, exclude):
    label, who = NO_SEARCH[code]
    lines = [f"檢索規則：{label}（{who}）", "檢索方式：不搜尋。不得使用 search-judgments、search-statutes。", "", "可用指令："]
    if code == 'verify':
        root = paths.get('case_snapshot', '<案件快照根目錄>')
        lines += [f"- 查證：python main.py verify <引用...> --snapshot {root} --read-by <plaintiff 或 defendant>"
                  "（查哪一方的書狀就填哪一方）",
                  f"- 讀判決全文：python main.py judgment <字號> [--doc-date YYYYMMDD] --snapshot {root}"
                  "（與雙方角色讀的是同一版本）",
                  "", "查證：",
                  "- 以案件快照根目錄比對雙方讀過的同一份全文與條文",
                  "- not_read_by_side：字號存在，但引用方沒有用 judgment 讀過全文，不放行",
                  "- 只有 published 放行；network_error（官網無法連線）與 full_text_unavailable（官網頁面無法辨認）"
                  "都不代表查無或引用寫錯，照實回報，不得改判為 published"]
    else:
        lines += [f"- 看相關段落：python main.py judgment <字號> --kw <關鍵詞>{_exclude_args(exclude)}"
                  "（只印含關鍵詞的句子與前後文；雙方起訴狀、答辯狀引用的判決，角色檔 precedents 已有摘句與核對結果）",
                  f"- 讀判決全文：python main.py judgment <字號> [--doc-date YYYYMMDD]{_exclude_args(exclude)}"
                  "（段落不足以判斷時才讀；不加 --snapshot、--log）",
                  "- 讀條文：python main.py article <法規名稱> <條號>"]
        if code == 'p6':
            lines += ["", "診斷：",
                      "- 建議新增的請求權基礎只做存在性查證：用 article 確認條文存在且為現行條文，不搜判決",
                      "- 提示切換法律關係屬民事訴訟法第199條之1的闡明"]
    lines += ["", "檢索失敗時：", *_bullets(ON_FAILURE[:2] + ON_FAILURE[3:]), "", "禁止：", *_bullets(FORBIDDEN)]
    return lines


def build(phase, side=None, case_dir=None, exclude=()):
    """→ {'phase', 'label', 'searches', 'budget', 'exclude', 'text', 以及有給 case_dir 時的路徑}。未知階段拋
    UnknownPhase，角色與階段不符、缺 --side 或 exclude 不是字號／JID 拋 ValueError。

    exclude(示範案的來源裁判)會帶進角色與法官的 search-judgments、judgment 指令；不說明原因，免得提示模型
    搜尋方向。獨立查證不排除：角色若憑記憶引用了來源裁判，查證仍要能查。"""
    from engine.judgment_search import exclusion_keys
    # 一律寫成不含空白的字號，貼進指令不會被 shell 拆開；排除本來就不分文件日期
    exclude = [f"{y}年度{c}字第{n}號" for y, c, n in sorted(exclusion_keys(exclude))]
    code = canonical_phase(phase)
    if code is None:
        raise UnknownPhase(f"未知階段：{phase}；可用：{'、'.join(phase_names())}")
    if side is not None and side not in SIDES:
        raise ValueError(f"--side 只能是 {'、'.join(SIDES)}")
    searches = code in SEARCH_RULES
    if searches and side and side not in SEARCH_RULES[code]['sides']:
        raise ValueError(f"{PHASES[code][0]}由{SIDE_LABEL[SEARCH_RULES[code]['sides'][0]]}檢索，不是{SIDE_LABEL[side]}")
    if searches and case_dir and not side:
        raise ValueError("給 --case-dir 時要同時給 --side，才能印出該角色的快照資料夾與紀錄檔")
    paths = case_paths(code, side, case_dir)
    exclude = [] if code == 'verify' else exclude
    lines = _search_text(code, side, paths, exclude) if searches else _no_search_text(code, paths, exclude)
    budget = {'searches': PHASES[code][1], 'fetches': PHASES[code][2]} if searches else None
    return {'phase': code, 'label': PHASES[code][0] if searches else NO_SEARCH[code][0], 'searches': searches,
            'budget': budget, 'exclude': exclude, **paths, 'text': '\n'.join(lines)}
