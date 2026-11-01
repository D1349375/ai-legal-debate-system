"""
建立「法規名稱 → pcode」索引(corpus/statutes/law_index.json)。

全國法規資料庫單條頁面的網址有固定規律:
    https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=B0000001&flno=33   (民法第33條)
只要知道法規的 pcode 就能查任一條。查證引擎原本只內建 STATUTE_PCODES 十幾部法規的 pcode,
本程式改從法務部官方開放資料(https://law.moj.gov.tw/api/swagger)一次取得全部中文法律與命令的
名稱與 pcode,供 `python main.py article <法規名稱> <條號>` 查條文。

索引只存名稱、pcode、位階、廢止註記與異動日期,不存條文內容——條文一律即時回官網單條頁面抓,
避免本地快取過時(同 corpus/statutes/*.txt 的教訓)。

用法:
    python scripts/build_law_index.py
官方資料每週更新,需要時重跑即可覆寫索引檔。
"""
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT_PATH = os.path.join(REPO_ROOT, 'corpus', 'statutes', 'law_index.json')
# 法律(含憲法)與命令(施行細則、辦法、規則等)是兩個獨立資料集,名稱彼此不重複(2026-11-01 實測)。
DATASETS = {
    'law': 'https://law.moj.gov.tw/api/ch/law/json',
    'order': 'https://law.moj.gov.tw/api/ch/order/json',
}
PCODE_RE = re.compile(r'pcode=([A-Za-z0-9]+)')


def download_laws(url):
    """→ (資料更新時間, 法規清單)。官方回傳 zip,內含單一 JSON 檔與 schema/manifest。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        payload = resp.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith('.json'))
        data = json.loads(archive.read(name).decode('utf-8-sig'))
    return data.get('UpdateDate'), data['Laws']


def index_entries(laws):
    entries = {}
    for law in laws:
        m = PCODE_RE.search(law.get('LawURL') or '')
        if not m:
            print(f"跳過 {law.get('LawName')}: 法規網址沒有 pcode", file=sys.stderr)
            continue
        entries[law['LawName']] = {
            'pcode': m.group(1),
            'level': law.get('LawLevel'),
            'abandoned': bool(law.get('LawAbandonNote')),
            'modified_date': law.get('LawModifiedDate') or None,
        }
    return entries


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')

    laws, update_dates = {}, {}
    for key, url in DATASETS.items():
        update_dates[key], items = download_laws(url)
        entries = index_entries(items)
        duplicated = set(entries) & set(laws)
        if duplicated:
            print(f"警告:{key} 與先前資料集有同名法規,以先取得者為準:{sorted(duplicated)[:5]}", file=sys.stderr)
            entries = {k: v for k, v in entries.items() if k not in duplicated}
        laws.update(entries)
        print(f"{key}: {len(entries)} 筆(官方資料更新時間 {update_dates[key]})")

    header = {
        'database': '全國法規資料庫(法務部)開放資料',
        'source_urls': DATASETS,
        'update_dates': update_dates,
        'fetched_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'note': '僅供名稱→pcode 對照;條文內容一律即時查官網單條頁面,不以本檔為權威來源。',
    }
    # 一部法規一行:一萬多筆若逐欄縮排近 2MB,重建索引時的 git diff 也難讀。
    lines = [f"  {json.dumps(name, ensure_ascii=False)}: {json.dumps(entry, ensure_ascii=False)}"
             for name, entry in sorted(laws.items())]
    with open(OUT_PATH, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(header, ensure_ascii=False, indent=1)[:-2])
        f.write(',\n "laws": {\n' + ',\n'.join(lines) + '\n }\n}\n')
    abandoned = sum(1 for v in laws.values() if v['abandoned'])
    print(f"完成。共 {len(laws)} 部法規(其中已廢止 {abandoned} 部),寫入 {os.path.relpath(OUT_PATH, REPO_ROOT)}")


if __name__ == "__main__":
    main()
