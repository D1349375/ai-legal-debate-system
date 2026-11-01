"""
階段二評估：以固定查詢集比較本地 grep 與上網檢索(docs/zh/retrieval-optimization-plan.md 第六節)。

每個查詢：
- 本地：原文 grep 命中數、去換行後命中數、其中程序駁回與判決的筆數。
- 上網：FJUD 進階搜尋(最高法院民事)第一頁 20 筆，記錄總筆數、文種、內容大小、日期範圍、與本地語料重疊數、耗時。
- 抓前 N 份可引用判決全文，記錄是否程序駁回、是否找得到命中句子、耗時。

另外用「上網列表與本地語料重疊」的裁判，對照列表上的內容大小(K)與本地的程序駁回判斷，校準 --min-size 門檻。

用法:
    python scripts/evaluate_retrieval.py [--out <資料夾>] [--fetch 3] [--sort date|size]
結果寫入 <資料夾>/results-<排序>.json。
會對司法院網站發出約 (3 + N) × 20 個請求，每次間隔 1.5 秒，約需 5 分鐘。
"""
import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, REPO_ROOT)

from engine import fjud, judgment_text  # noqa: E402
from engine.judgment_search import NETWORK_ERRORS  # noqa: E402

# 法條與要件詞各 10 個，涵蓋侵權、契約、不當得利、時效、舉證等民事常見爭點。
QUERIES = [
    ('statute', '民法第184條'), ('statute', '民法第197條'), ('statute', '民法第179條'),
    ('statute', '民法第227條'), ('statute', '民法第245條之1'), ('statute', '民法第92條'),
    ('statute', '民法第767條'), ('statute', '民法第216條'), ('statute', '民法第213條'),
    ('statute', '民事訴訟法第277條'),
    ('element', '知有損害'), ('element', '締約上過失'), ('element', '無法律上之原因'),
    ('element', '與有過失'), ('element', '所失利益'), ('element', '情事變更'),
    ('element', '不完全給付'), ('element', '相當因果關係'), ('element', '舉證責任之分配'),
    ('element', '默示之意思表示'),
]


def load_local():
    names = judgment_text.law_names()
    docs = {}
    for path in sorted(glob.glob(os.path.join(REPO_ROOT, 'corpus', 'judgments', '*.txt'))):
        with open(path, encoding='utf-8') as f:
            text = f.read()
        summary = judgment_text.summarize(text, names=names)
        docs[os.path.basename(path)[:-4]] = {'raw': text, 'flat': re.sub(r'\s+', '', text),
                                             'chars': len(re.sub(r'\s+', '', text)),
                                             'doc_type': summary['doc_type'], 'procedural': summary['procedural_only']}
    return docs, names


def evaluate_local(term, docs):
    raw = [j for j, d in docs.items() if term in d['raw']]
    flat = [j for j, d in docs.items() if term in d['flat']]
    return {'raw_hits': len(raw), 'flat_hits': len(flat),
            'flat_procedural': sum(docs[j]['procedural'] for j in flat),
            'flat_judgments': sum(docs[j]['doc_type'] == '判決' for j in flat)}


def evaluate_online(term, docs, names, fetch, session, fetched_cache, sort):
    started = time.monotonic()
    try:
        result = fjud.advanced_search([term], pages=1, sort=sort, session=session)
    except NETWORK_ERRORS as error:
        return {'error': str(error)}
    search_seconds = round(time.monotonic() - started, 1)
    rows = result['rows']
    verifiable = [r for r in rows if r['jid'].startswith('TPSV,')]
    fetched = []
    for row in [r for r in verifiable if r['doc_type'] == '判決'][:fetch]:
        started = time.monotonic()
        try:
            text = fetched_cache.get(row['jid']) or fjud.fetch_document(row['jid'], session=session)['full_text']
        except NETWORK_ERRORS as error:
            fetched.append({'jid': row['jid'], 'error': str(error)})
            continue
        fetched_cache[row['jid']] = text
        summary = judgment_text.summarize(text, [term], names)
        fetched.append({'jid': row['jid'], 'seconds': round(time.monotonic() - started, 1), 'chars': len(text),
                        'procedural': summary['procedural_only'], 'disposition': summary['disposition'],
                        'matched': summary['matched_sentences'][:1], 'statutes': summary['statutes'][:8]})
    dates = sorted(r['doc_date'] for r in rows if r['doc_date'])
    return {
        'total': result['total'], 'page_rows': len(rows), 'search_seconds': search_seconds,
        'judgments': sum(r['doc_type'] == '判決' for r in rows), 'rulings': sum(r['doc_type'] == '裁定' for r in rows),
        'unverifiable': len(rows) - len(verifiable), 'in_local': sum(r['jid'] in docs for r in rows),
        'oldest': dates[0] if dates else None, 'newest': dates[-1] if dates else None,
        'rows': [{k: r[k] for k in ('jid', 'doc_type', 'size_kb', 'doc_date', 'case_cause')} for r in rows],
        'fetched': fetched,
    }


def calibrate(results, docs):
    """上網列表與本地重疊的裁判 → (內容大小 K, 本地字數, 文種, 是否程序駁回)。"""
    pairs = {}
    for item in results:
        for row in item['online'].get('rows', []):
            if row['jid'] in docs and row['size_kb']:
                d = docs[row['jid']]
                pairs[row['jid']] = {'size_kb': row['size_kb'], 'chars': d['chars'],
                                     'doc_type': d['doc_type'], 'procedural': d['procedural']}
    return pairs


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=os.path.join(REPO_ROOT, 'docs', 'retrieval-evaluation', '2026-11-01'))
    parser.add_argument('--fetch', type=int, default=3)
    parser.add_argument('--sort', choices=('date', 'size'), default='date')
    args = parser.parse_args()
    sort = fjud.SORT_SIZE if args.sort == 'size' else fjud.SORT_DATE

    docs, names = load_local()
    session, fetched_cache, results = fjud.Session(), {}, []
    for kind, term in QUERIES:
        item = {'kind': kind, 'term': term, 'local': evaluate_local(term, docs),
                'online': evaluate_online(term, docs, names, args.fetch, session, fetched_cache, sort)}
        results.append(item)
        o = item['online']
        print(f"{term}: 本地 {item['local']['raw_hits']}/{item['local']['flat_hits']}｜"
              f"上網 {o.get('total', o.get('error'))}（{o.get('search_seconds')} 秒）", flush=True)

    os.makedirs(args.out, exist_ok=True)
    output = {'evaluated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
              'local_documents': len(docs), 'fetch_per_query': args.fetch, 'sort': args.sort,
              'results': results, 'calibration': calibrate(results, docs),
              'local_size_profile': [{'jid': j, 'chars': d['chars'], 'doc_type': d['doc_type'], 'procedural': d['procedural']}
                                     for j, d in docs.items()]}
    path = os.path.join(args.out, f'results-{args.sort}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=1)
    print(f"已寫入 {os.path.relpath(path, REPO_ROOT)}")


if __name__ == '__main__':
    main()
