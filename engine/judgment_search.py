"""判決上網檢索：FJUD 進階搜尋(預設最高法院民事) + 抓全文整理 + 選擇性留存。

列表只看得到字號、文種、大小、日期、案由與命中片段；抓全文後才有主文、程序駁回判斷、引用法條與命中句子
(engine/judgment_text.py)。查證引擎只認最高法院民事字號(JID 前綴 TPSV)，列表混入的其他前綴(如家事類 TPSU)
標為不可引用、不抓全文。

上限：每次最多 MAX_PAGES 頁、MAX_FETCH 份全文，請求間隔由 fjud.Session 控制。
全文經 engine/retrieval_cache.py 取得：快照、長期快取或預先內容已有的不上網；上網抓到的寫回快取。
max_live_fetches 為本階段全文預算剩餘份數(engine/search_log.py)，用完時快取沒有的就不抓，列表照常回傳。
exclude 為不提供給角色的裁判(字號或 JID)：示範案改編自真實判決時，排除來源裁判，免得模型搜到原案的答案。
同字號的每一份文件都排除，列表中直接拿掉、不抓全文；judgment 指令也據此拒讀。
"""
import json
import os
import re
import ssl
import urllib.error
from collections import Counter
from datetime import datetime, timezone

from engine import fjud, judgment_text, retrieval_cache
from engine.law_lookup import with_retry
from engine.verify import JUDGMENT_CITATION_RE

MAX_PAGES = 5
MAX_FETCH = 10
VERIFIABLE_PREFIX = "TPSV,"
SORTS = {'size': fjud.SORT_SIZE, 'date': fjud.SORT_DATE}
NETWORK_ERRORS = (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError, OSError)


def _check_date(value, label):
    if value and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError(f"{label}須為 YYYY-MM-DD")


def exclusion_keys(values):
    """--exclude 的字號或 JID → {(年度, 字別, 號)}；不分文件日期。無法解析時拋 ValueError。"""
    keys = set()
    for value in values or ():
        text = (value or '').strip()
        parts = text.split(',')
        m = None if ',' in text else JUDGMENT_CITATION_RE.search(text)
        if len(parts) >= 4:
            keys.add(tuple(parts[1:4]))
        elif m:
            keys.add((m.group(2), m.group(3), m.group(4)))
        else:
            raise ValueError(f"--exclude 須為裁判字號(如 111年度台上字第1069號)或 JID：{value}")
    return keys


def is_excluded(jid, keys):
    return tuple(jid.split(',')[1:4]) in keys


def search_judgments(keywords=(), case_cause=None, date_from=None, date_to=None, pages=2, fetch=0,
                     include_rulings=False, min_size_kb=None, sort='date', save_dir=None, timeout=fjud.DEFAULT_TIMEOUT,
                     snapshot=None, max_live_fetches=None, exclude=()):
    """→ {'query', 'fetched_at', 'total', 'page_count', 'pages_read', 'rows', 'unverifiable', 'saved_to'}。

    搜尋本身連線失敗重試一次，仍失敗時拋出網路例外；抓個別全文失敗只記在該列 fetch_error，不丟掉已取得的列表。
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
    excluded_keys = exclusion_keys(exclude)

    session = fjud.Session(timeout)
    query = {'keywords': keywords, 'case_cause': case_cause, 'date_from': date_from, 'date_to': date_to,
             'pages': pages, 'fetch': fetch, 'include_rulings': include_rulings, 'min_size_kb': min_size_kb,
             'sort': sort, 'court': '最高法院', 'category': '民事', 'exclude': list(exclude or ())}
    result = with_retry(lambda: fjud.advanced_search(keywords, case_cause=case_cause, date_from=date_from, date_to=date_to,
                                                     pages=pages, min_size_kb=min_size_kb, sort=SORTS[sort], session=session))
    rows = [r for r in result['rows'] if not is_excluded(r['jid'], excluded_keys)]
    for row in rows:
        row['verifiable'] = row['jid'].startswith(VERIFIABLE_PREFIX)
    candidates = [r for r in rows if r['verifiable'] and (include_rulings or r['doc_type'] == '判決')][:fetch]
    names = judgment_text.law_names() if candidates else None
    texts = {}
    live_left = max_live_fetches
    for row in candidates:
        try:
            entry = retrieval_cache.get_judgment(row['jid'], snapshot=snapshot, session=session, timeout=timeout,
                                                 allow_live=live_left is None or live_left > 0)
        except retrieval_cache.LiveFetchNotAllowed:
            row['fetch_error'] = '已達本階段全文預算，快取沒有這份，未抓取'
            continue
        except retrieval_cache.FullTextUnavailable as error:
            row['fetch_error'] = f"full_text_unavailable：{error.reason}；{retrieval_cache.FULL_TEXT_UNAVAILABLE_NOTE}"
            continue
        except retrieval_cache.RetrievalUnavailable as error:
            row['fetch_error'] = f"連線失敗（已重試）：{error.reason}；不代表查無資料"
            continue
        if entry['served_from'] == 'live' and live_left is not None:
            live_left -= 1
        texts[row['jid']] = entry['text']
        row.update(judgment_text.summarize(entry['text'], keywords, names), fetched=True, served_from=entry['served_from'])

    output = {'query': query, 'fetched_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
              'total': result['total'], 'page_count': result['page_count'], 'pages_read': result['pages_read'],
              'rows': rows, 'excluded': len(result['rows']) - len(rows), 'unverifiable': sum(not r['verifiable'] for r in rows),
              'statute_counts': statute_counts(rows), 'saved_to': None}
    if save_dir:
        _save(save_dir, output, texts)
    return output


def statute_counts(rows):
    """抓回全文的判決中，各實體法條出現在幾份判決 → [{'statute', 'judgments'}]，多到少(同數依首次出現順序)。
    實務常把完全性法條與補充性法條一起引用(如車禍案的民法第184、191條之2、195條)，用來檢查有沒有漏掉該一起主張的法條。"""
    counts = Counter(statute for row in rows if row.get('fetched') for statute in row['statutes'])
    return [{'statute': statute, 'judgments': n} for statute, n in counts.most_common()]


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
