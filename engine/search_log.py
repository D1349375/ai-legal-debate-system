"""檢索紀錄與每輪查詢預算。

檢索指令(search-judgments、search-statutes、article、judgment)加 --log <檔案> 時，每次查詢的條件、命中數、
取得哪些全文與來源自動附加到該檔(JSON Lines，一行一筆)。路徑由調度員給(佔位符 {SEARCH_LOG_PATH})，
每個角色每輪一個檔，例如 <實跑資料夾>/search_logs/plaintiff_stage1.jsonl；搜過哪些詞本身透露策略方向，對造不得讀取。

預算(2026-11-01 階段二評估定案)由指令依同一份紀錄計數，超過就拒絕並說明原因，不靠 prompt 自律：
- 搜尋次數：search-judgments 的執行次數(search-statutes 與 article 只記錄、不計入)。
- 全文份數：實際上網抓的判決全文；快照、長期快取或預先內容已有的不計入。
輪次由紀錄檔名的 stage1／stage2／stage3 判斷，而不是另一個設定檔：UI 實跑的角色對實跑資料夾有寫入權限，
設定檔改得到，檔名則由調度員在 prompt 裡指定。檔名看不出輪次時套用最嚴的預算(Stage 2、3)。
"""
import json
import os
import re
from datetime import datetime, timezone

BUDGETS = {1: {'searches': 8, 'fetches': 10}, 2: {'searches': 4, 'fetches': 5}, 3: {'searches': 4, 'fetches': 5}}
DEFAULT_STAGE = 2
_STAGE_RE = re.compile(r'stage[_-]?([123])', re.I)


class BudgetExceeded(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class SearchLog:
    def __init__(self, path):
        self.path = path
        m = _STAGE_RE.search(os.path.basename(path))
        self.stage = int(m.group(1)) if m else None
        self.budget = BUDGETS[self.stage or DEFAULT_STAGE]
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

    def stage_label(self):
        return f"Stage {self.stage}" if self.stage else f"輪次不明，套用 Stage {DEFAULT_STAGE}、3"

    def summary(self):
        return (f"本輪檢索（{self.stage_label()}）：搜尋 {self.searches_used}/{self.budget['searches']} 次、"
                f"上網抓全文 {self.fetches_used}/{self.budget['fetches']} 份（快取已有的不計）")

    def check_search(self):
        if self.searches_used >= self.budget['searches']:
            raise BudgetExceeded(f"已達本輪搜尋預算（{self.stage_label()} 上限 {self.budget['searches']} 次）；"
                                 "請用已取得的結果，或以 judgment 依字號讀快取中的全文")

    def check_fetch(self):
        if self.remaining_fetches() <= 0:
            raise BudgetExceeded(f"已達本輪全文預算（{self.stage_label()} 上限 {self.budget['fetches']} 份）；"
                                 "快照或快取已有的全文仍可讀取")

    def append(self, command, query, status, *, hits=None, fetched=(), counts_as_search=False, note=None):
        """fetched 為 [{'jid' 或 'key', 'served_from', 'kind'}]；判決(kind 預設 judgment)且 served_from 為 live 的
        才計入全文預算，條文不計。"""
        fetched = list(fetched)
        entry = {'at': _now(), 'command': command, 'query': query, 'status': status, 'hits': hits,
                 'fetched': fetched, 'live_fetches': sum(1 for f in fetched if f.get('served_from') == 'live'
                                                         and f.get('kind', 'judgment') == 'judgment'),
                 'counts_as_search': counts_as_search, 'stage': self.stage}
        if note:
            entry['note'] = note
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        self.entries.append(entry)
        return entry
