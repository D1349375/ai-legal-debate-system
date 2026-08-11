"""
Phase 0 語料蒐集:抓取最高法院民事裁判種子語料。

用法(使用者自行執行,帳密由使用者自己的環境變數提供,本程式不會把密碼寫進任何檔案或傳給任何第三方):

    JUDICIAL_USER=你的帳號 JUDICIAL_PASSWORD=你的密碼 python scripts/fetch_judgments.py

依 https://data.judicial.gov.tw/jdg/api/ 之官方規格說明(裁判書開放API規格說明 114.08.22版):
- API 服務時間僅每日 00:00-06:00,其餘時間會失敗屬正常現象,請在該時段內執行。
- JList 只回傳「7 天內有異動」的全國各級法院裁判 ID,不是可任意搜尋的資料庫,
  所以本次執行抓到的筆數多寡取決於這 7 天內最高法院民事裁判的異動量。
- 「TPSV」為推論出的最高法院民事裁判 JID 前綴(TPS = 最高法院,V = 民事,
  依官方文件之裁判類別代碼與 tps.judicial.gov.tw 為最高法院官方子網域交叉推得,
  非官方文件明文列出的對照表,故程式同時用全文開頭是否為「最高法院」做二次驗證,
  避免前綴推論有誤導致收錄非最高法院之裁判)。
"""
import json
import os
import re
import sys
import urllib.request
import urllib.error

API_BASE = "https://data.judicial.gov.tw/jdg/api"
TARGET_PREFIX = "TPSV"  # 最高法院(TPS) + 民事(V)，見上方說明
TARGET_COUNT = 20
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "corpus", "judgments")


def call(path, payload):
    req = urllib.request.Request(
        f"{API_BASE}/{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')}", file=sys.stderr)
        raise


def main():
    user = os.environ.get("JUDICIAL_USER")
    password = os.environ.get("JUDICIAL_PASSWORD")
    if not user or not password:
        print("請先設定環境變數 JUDICIAL_USER / JUDICIAL_PASSWORD 再執行。", file=sys.stderr)
        sys.exit(1)

    auth = call("Auth", {"user": user, "password": password})
    token = auth.get("Token")
    if not token:
        print(f"驗證失敗:{auth}", file=sys.stderr)
        sys.exit(1)
    print("驗證成功,取得 token。")

    jlist = call("JList", {"token": token})
    all_jids = [jid for day in jlist for jid in day.get("list", [])]
    candidates = [j for j in all_jids if j.startswith(TARGET_PREFIX)]
    print(f"7 日異動清單共 {len(all_jids)} 筆,前綴符合 {TARGET_PREFIX} 的有 {len(candidates)} 筆。")

    os.makedirs(OUT_DIR, exist_ok=True)
    saved = 0
    for jid in candidates:
        if saved >= TARGET_COUNT:
            break
        doc = call("JDoc", {"token": token, "j": jid})
        if "error" in doc:
            print(f"跳過 {jid}: {doc['error']}")
            continue
        full = doc.get("JFULLX", {})
        content = full.get("JFULLCONTENT", "")
        if not content.strip().startswith("最高法院"):
            print(f"跳過 {jid}: 全文開頭非「最高法院」,前綴推論可能有誤,不予收錄。開頭:{content[:20]!r}")
            continue

        safe_name = re.sub(r'[\\/:*?"<>|]', "_", jid)
        txt_path = os.path.join(OUT_DIR, f"{safe_name}.txt")
        meta_path = os.path.join(OUT_DIR, f"{safe_name}_source.json")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(content)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "jid": jid,
                    "jyear": doc.get("JYEAR"),
                    "jcase": doc.get("JCASE"),
                    "jno": doc.get("JNO"),
                    "jdate": doc.get("JDATE"),
                    "jtitle": doc.get("JTITLE"),
                    "full_type": full.get("JFULLTYPE"),
                    "source_api": f"{API_BASE}/JDoc",
                    "database": "司法院裁判書開放API(data.judicial.gov.tw)",
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"已存 {jid} -> {txt_path}")
        saved += 1

    print(f"完成,共存入 {saved} 筆最高法院民事裁判。")


if __name__ == "__main__":
    main()
