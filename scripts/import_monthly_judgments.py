"""
Phase 0 語料擴充:匯入司法院「月封裝壓縮檔」(opendata.judicial.gov.tw,會員限定下載,
使用者已自行登入下載並解壓,本程式不涉及帳密)。

範圍收斂(2026-08-08 決定):只匯入「最高法院民事」資料夾,跟既有 20 筆種子語料
(透過 jdg/api 取得)同一範圍,只是延伸月份,不擴大到地方法院/其他案由——避免一次
匯入數萬筆超出目前驗證用途所需的量。

用法:
    python scripts/import_monthly_judgments.py <解壓後的月份資料夾路徑> [<另一個月份路徑> ...]

每個路徑須是解壓後、內含「最高法院民事」子資料夾的目錄
(例如司法院月封裝檔解壓後的 `<年月>/<年月>/最高法院民事/*.json` 那一層之上兩層)。
"""
import json
import os
import sys

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT_DIR = os.path.join(REPO_ROOT, 'corpus', 'judgments')
TARGET_FOLDER_NAME = '最高法院民事'


def find_target_folders(root):
    """在給定的月份解壓根目錄下遞迴尋找所有名為「最高法院民事」的資料夾。"""
    found = []
    for dirpath, dirnames, _ in os.walk(root):
        if os.path.basename(dirpath) == TARGET_FOLDER_NAME:
            found.append(dirpath)
    return found


def import_folder(folder, existing_jids):
    imported, skipped = 0, 0
    for name in os.listdir(folder):
        if not name.endswith('.json'):
            continue
        src_path = os.path.join(folder, name)
        with open(src_path, encoding='utf-8') as f:
            doc = json.load(f)
        jid = doc.get('JID')
        if not jid:
            print(f"跳過 {name}: 缺少 JID 欄位")
            continue
        if jid in existing_jids:
            skipped += 1
            continue

        safe_name = jid.replace('/', '_').replace('\\', '_')
        txt_path = os.path.join(OUT_DIR, f"{safe_name}.txt")
        meta_path = os.path.join(OUT_DIR, f"{safe_name}_source.json")
        content = doc.get('JFULL', '')

        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(content)
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(
                {
                    "jid": jid,
                    "jyear": doc.get('JYEAR'),
                    "jcase": doc.get('JCASE'),
                    "jno": doc.get('JNO'),
                    "jdate": doc.get('JDATE'),
                    "jtitle": doc.get('JTITLE'),
                    "full_type": "text",
                    "source_pdf_url": doc.get('JPDF'),
                    "database": "司法院裁判書開放資料平臺(opendata.judicial.gov.tw,月封裝檔)",
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        existing_jids.add(jid)
        imported += 1
    return imported, skipped


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)
    existing_jids = set()
    for name in os.listdir(OUT_DIR):
        if name.endswith('_source.json'):
            with open(os.path.join(OUT_DIR, name), encoding='utf-8') as f:
                existing_jids.add(json.load(f).get('jid'))

    total_imported, total_skipped = 0, 0
    for root in sys.argv[1:]:
        folders = find_target_folders(root)
        if not folders:
            print(f"{root}: 找不到「{TARGET_FOLDER_NAME}」資料夾,略過")
            continue
        for folder in folders:
            imported, skipped = import_folder(folder, existing_jids)
            print(f"{folder}: 新增 {imported} 筆,重複略過 {skipped} 筆")
            total_imported += imported
            total_skipped += skipped

    print(f"完成。共新增 {total_imported} 筆,重複略過 {total_skipped} 筆。"
          f"corpus/judgments/ 現有 {len(existing_jids)} 筆不重複判決。")


if __name__ == "__main__":
    main()
