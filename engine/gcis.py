"""經濟部商工行政資料開放平臺 client；只處理 HTTP 與欄位格式。"""
import datetime
import json
import re
import urllib.error
import urllib.parse
import urllib.request

GCIS_BASE = "https://data.gcis.nat.gov.tw/od/data/api"
DATASETS = {
    "entity_type": ("673F0FC0-B3A7-429F-9041-E9866836B66D", "統編查是否為公司、分公司及商業", "https://data.gcis.nat.gov.tw/od/detail?oid=2AE8EE8F-D39E-4DAD-B3F2-7898F61342EA"),
    "company": ("5F64D864-61CB-4D0D-8AD9-492047CC1EA6", "公司登記基本資料-應用一", "https://data.gcis.nat.gov.tw/od/detail?oid=8776818F-EB3C-445F-BE95-AE22577CBEBC"),
    "directors": ("4E5F7653-1B91-4DDC-99D5-468530FAE396", "公司登記董監事資料", "https://data.gcis.nat.gov.tw/od/detail?oid=7CD44707-5D43-4C93-BC45-50E22F67EB01"),
    "branches": ("FDB8D2C8-573D-4276-BFA4-8D3925ABE1CB", "統編查分公司資料", "https://data.gcis.nat.gov.tw/od/detail?oid=3F69570B-8936-40C1-9AAD-8526C5ADE237"),
    "keyword": ("6BBA2268-1367-4B42-9CCA-BC17499EBE8C", "公司登記關鍵字查詢", "https://data.gcis.nat.gov.tw/od/detail?oid=311892F7-9BA6-4DDB-B5F6-AE1EF24FDD6A"),
    "business": ("426D5542-5F05-43EB-83F9-F1300F14E1F1", "商業登記基本資料-應用三", "https://data.gcis.nat.gov.tw/od/detail?oid=06BCF9F6-A6D0-4F82-A1F2-EA08144D7057"),
}
ATTRIBUTION = "提供機關/經濟部商業發展署"
HEADERS = {"User-Agent": "Mozilla/5.0 (LegalDebate party check; official open data)", "Accept": "application/json"}


def validate_ban(text):
    value = re.sub(r"\s+", "", str(text or ""))
    return value if re.fullmatch(r"[0-9]{8}", value) else None


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _query(dataset, filter_text, *, top=1, timeout=6):
    api_id = DATASETS[dataset][0]
    params = urllib.parse.urlencode({"$format": "json", "$filter": filter_text, "$skip": "0", "$top": str(top)},
                                    quote_via=urllib.parse.quote)
    url = f"{GCIS_BASE}/{api_id}?{params}"
    out = {"ok": False, "rows": [], "url": url, "fetched_at": None, "error": None, "dataset": dataset}
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8-sig").strip()
        rows = json.loads(body) if body else []
        if not isinstance(rows, list):
            raise ValueError("API 回應不是資料陣列")
        out.update(ok=True, rows=rows, fetched_at=_now())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError, UnicodeError) as exc:
        reason = f"{type(exc).__name__}: {exc}"
        kind = "逾時" if "timed out" in reason.lower() or isinstance(exc, TimeoutError) else "連線或回應錯誤"
        out["error"] = f"商工資料{kind}：{reason}"
    return out


def entity_type(ban, timeout=6):
    return _query("entity_type", f"NO eq {ban}", top=3, timeout=timeout)


def company_basic(ban, timeout=6):
    return _query("company", f"Business_Accounting_NO eq {ban}", timeout=timeout)


def directors(ban, timeout=6):
    return _query("directors", f"Business_Accounting_NO eq {ban}", top=100, timeout=timeout)


def branches(ban, top=50, timeout=6):
    return _query("branches", f"Business_Accounting_NO eq {ban}", top=min(max(1, top), 50), timeout=timeout)


def business_basic(ban, timeout=6):
    return _query("business", f"President_No eq {ban}", timeout=timeout)


def search_companies(keyword, top=10, timeout=6):
    # 不提供姓名查詢；關鍵字只交給公司名稱欄。
    clean = str(keyword or "").strip().replace("'", "")[:80]
    return _query("keyword", f"Company_Name like {clean} and Company_Status eq 01", top=min(max(1, top), 10), timeout=timeout)


def roc_date_iso(value):
    value = str(value or "").strip()
    if not re.fullmatch(r"[0-9]{7}", value):
        return None
    try:
        return datetime.date(int(value[:3]) + 1911, int(value[3:5]), int(value[5:7])).isoformat()
    except ValueError:
        return None


def roc_date(value):
    iso = roc_date_iso(value)
    if iso is None:
        return None
    date = datetime.date.fromisoformat(iso)
    return f"民國{date.year - 1911}年{date.month}月{date.day}日"
