"""檢索紀錄與每輪查詢預算。

檢索指令(search-judgments、search-statutes、article、judgment)加 --log <檔案> 時，每次查詢的條件、命中數、
取得哪些全文與來源自動附加到該檔(JSON Lines，一行一筆)。路徑由調度員給(佔位符 {SEARCH_LOG_PATH})，
每個角色每個階段一個檔，放在案件資料夾，例如 <案件資料夾>/search_logs/plaintiff_p1.jsonl；搜過哪些詞本身透露
策略方向，對造不得讀取。search-judgments 與 judgment 可加 --issue <爭點id>，記下這次查詢是為了哪個爭點。

預算(2026-11-01 階段二評估定案)由指令依同一份紀錄計數，超過就拒絕並說明原因，不靠 prompt 自律：
- 搜尋次數：search-judgments 的執行次數(search-statutes 與 article 只記錄、不計入)。
- 全文份數：實際上網抓的判決全文；快照、長期快取或預先內容已有的不計入。
階段由紀錄檔名判斷，而不是另一個設定檔：UI 實跑的角色對實跑資料夾有寫入權限，設定檔改得到，檔名則由調度員在
prompt 裡指定。檔名中以 _ - . 分隔的一段若是下表的階段名稱就套用其預算；看不出階段時套用 4 次／5 份。
- 書狀交換架構(組長改版規格 P1～P5)：p1／complaint 起訴狀、p2／scenario／answer 答辯劇本與答辯狀(兩步共用一檔)、
  p4／brief 準備書狀、p5／closing 言詞辯論意旨狀。法官(P3、P6)與獨立查證不檢索，沒有預算。
- 現行三輪：stage1、stage2、stage3。
"""
import json
import os
import re
from datetime import datetime, timezone

# 階段 → (說明, 搜尋次數, 全文份數)
PHASES = {
    'p1': ('P1 起訴狀', 8, 10),
    'p2': ('P2 答辯劇本與答辯狀', 8, 10),
    'p4': ('P4 準備書狀', 4, 5),
    'p5': ('P5 言詞辯論意旨狀', 2, 3),
    'stage1': ('Stage 1', 8, 10),
    'stage2': ('Stage 2', 4, 5),
    'stage3': ('Stage 3', 4, 5),
}
PHASE_ALIASES = {'complaint': 'p1', 'scenario': 'p2', 'scenarios': 'p2', 'answer': 'p2', 'brief': 'p4',
                 'closing': 'p5', 'stage_1': 'stage1', 'stage-1': 'stage1', 'stage_2': 'stage2', 'stage-2': 'stage2',
                 'stage_3': 'stage3', 'stage-3': 'stage3'}
DEFAULT_BUDGET = (4, 5)
_PHASE_RE = re.compile(r'(?:^|[_.-])(stage[_-]?[123]|p[1245]|complaint|scenarios?|answer|brief|closing)(?=$|[_.-])', re.I)


class BudgetExceeded(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def phase_of(path):
    """紀錄檔名 → 階段代碼(p1、stage2…)，看不出時 None。"""
    m = _PHASE_RE.search(os.path.basename(path))
    if not m:
        return None
    name = m.group(1).lower()
    return PHASE_ALIASES.get(name, name)


class SearchLog:
    def __init__(self, path):
        self.path = path
        self.phase = phase_of(path)
        searches, fetches = PHASES[self.phase][1:] if self.phase else DEFAULT_BUDGET
        self.budget = {'searches': searches, 'fetches': fetches}
        self.entries = []
        if os.path.isfile(path):
            with open(path, encoding='utf-8') as f:
                for line in f:
                    try:
                        self.entries.append(json.loads(line))
                    except ValueError:
                        continue

    @property
    def searches_used(self):
        return sum(1 for e in self.entries if e.get('counts_as_search'))

    @property
    def fetches_used(self):
        return sum(e.get('live_fetches', 0) for e in self.entries)

    def remaining_fetches(self):
        return max(0, self.budget['fetches'] - self.fetches_used)

    def phase_label(self):
        return PHASES[self.phase][0] if self.phase else "階段不明，套用預設"

    def summary(self):
        return (f"本階段檢索（{self.phase_label()}）：搜尋 {self.searches_used}/{self.budget['searches']} 次、"
                f"上網抓全文 {self.fetches_used}/{self.budget['fetches']} 份（快取已有的不計）")

    def check_search(self):
        if self.searches_used >= self.budget['searches']:
            raise BudgetExceeded(f"已達本階段搜尋預算（{self.phase_label()} 上限 {self.budget['searches']} 次）；"
                                 "請用已取得的結果，或以 judgment 依字號讀快取中的全文")

    def check_fetch(self):
        if self.remaining_fetches() <= 0:
            raise BudgetExceeded(f"已達本階段全文預算（{self.phase_label()} 上限 {self.budget['fetches']} 份）；"
                                 "快照或快取已有的全文仍可讀取")

    def append(self, command, query, status, *, hits=None, fetched=(), counts_as_search=False, note=None, issue=None):
        """fetched 為 [{'jid' 或 'key', 'served_from', 'kind'}]；判決(kind 預設 judgment)且 served_from 為 live 的
        才計入全文預算，條文不計。issue 為這次查詢針對的爭點 id(選填)。"""
        fetched = list(fetched)
        entry = {'at': _now(), 'command': command, 'query': query, 'status': status, 'hits': hits,
                 'fetched': fetched, 'live_fetches': sum(1 for f in fetched if f.get('served_from') == 'live'
                                                         and f.get('kind', 'judgment') == 'judgment'),
                 'counts_as_search': counts_as_search, 'phase': self.phase}
        if issue:
            entry['issue'] = issue
        if note:
            entry['note'] = note
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        self.entries.append(entry)
        return entry
