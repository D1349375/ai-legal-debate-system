"""判決上網檢索：FJUD 進階搜尋(預設最高法院民事) + 抓全文整理 + 選擇性留存。

列表只看得到字號、文種、大小、日期、案由與命中片段；抓全文後才有主文、程序駁回判斷、引用法條與命中句子
(engine/judgment_text.py)。查證引擎只認最高法院民事字號(JID 前綴 TPSV)，列表混入的其他前綴(如家事類 TPSU)
標為不可引用、不抓全文。

上限：每次最多 MAX_PAGES 頁、MAX_FETCH 份全文，請求間隔由 fjud.Session 控制。
"""
import json
import os
import re
import ssl
import urllib.error
from datetime import datetime, timezone

from engine import fjud, judgment_text

MAX_PAGES = 5
MAX_FETCH = 10
VERIFIABLE_PREFIX = "TPSV,"
SORTS = {'size': fjud.SORT_SIZE, 'date': fjud.SORT_DATE}
NETWORK_ERRORS = (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError, OSError)


def _check_date(value, label):
    if value and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError(f"{label}須為 YYYY-MM-DD")


def search_judgments(keywords=(), case_cause=None, date_from=None, date_to=None, pages=2, fetch=0,
                     include_rulings=False, min_size_kb=None, sort='date', save_dir=None, timeout=fjud.DEFAULT_TIMEOUT):
    """→ {'query', 'fetched_at', 'total', 'page_count', 'pages_read', 'rows', 'unverifiable', 'saved_to'}。

    搜尋本身連線失敗時拋出網路例外；抓個別全文失敗只記在該列 fetch_error，不丟掉已取得的列表。
    """
    keywords = [k.strip() for k in keywords if k and k.strip()]
    if not keywords and not case_cause:
        raise ValueError("至少要有一個關鍵字或案由")
    if not 1 <= pages <= MAX_PAGES:
        raise ValueError(f"頁數須介於 1～{MAX_PAGES}")
    if not 0 <= fetch <= MAX_FETCH:
        raise ValueError(f"全文份數須介於 0～{MAX_FETCH}")
    _check_date(date_from, "起始日期")
    _check_date(date_to, "結束日期")
    if sort not in SORTS:
        raise ValueError("排序須為 size 或 date")

    session = fjud.Session(timeout)
    query = {'keywords': keywords, 'case_cause': case_cause, 'date_from': date_from, 'date_to': date_to,
             'pages': pages, 'fetch': fetch, 'include_rulings': include_rulings, 'min_size_kb': min_size_kb,
             'sort': sort, 'court': '最高法院', 'category': '民事'}
    result = fjud.advanced_search(keywords, case_cause=case_cause, date_from=date_from, date_to=date_to,
                                  pages=pages, min_size_kb=min_size_kb, sort=SORTS[sort], session=session)
    rows = result['rows']
    for row in rows:
        row['verifiable'] = row['jid'].startswith(VERIFIABLE_PREFIX)
    candidates = [r for r in rows if r['verifiable'] and (include_rulings or r['doc_type'] == '判決')][:fetch]
    names = judgment_text.law_names() if candidates else None
    texts = {}
    for row in candidates:
        try:
            document = fjud.fetch_document(row['jid'], session=session)
        except NETWORK_ERRORS as error:
            row['fetch_error'] = f"連線失敗：{error}"
            continue
        if not document['full_text']:
            row['fetch_error'] = '官網頁面無法辨認全文'
            continue
        texts[row['jid']] = document['full_text']
        row.update(judgment_text.summarize(document['full_text'], keywords, names), fetched=True)

    output = {'query': query, 'fetched_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
              'total': result['total'], 'page_count': result['page_count'], 'pages_read': result['pages_read'],
              'rows': rows, 'unverifiable': sum(not r['verifiable'] for r in rows), 'saved_to': None}
    if save_dir:
        _save(save_dir, output, texts)
    return output


def _save(save_dir, output, texts):
    """查詢條件與結果存成 search-<時間>.json，抓到的全文存成 <JID>.txt(原文，未去換行)。"""
    os.makedirs(save_dir, exist_ok=True)
    stamp = output['fetched_at'].replace(':', '').replace('-', '')
    output['saved_to'] = os.path.join(save_dir, f"search-{stamp}.json")
    with open(output['saved_to'], 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    for jid, text in texts.items():
        with open(os.path.join(save_dir, f"{jid}.txt"), 'w', encoding='utf-8') as f:
            f.write(text)
