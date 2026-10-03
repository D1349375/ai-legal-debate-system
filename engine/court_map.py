"""普通民事地方法院管轄區域；資料來源：司法院公報「各級法院管轄區域一覽表」。

來源：https://www.judicial.gov.tw/tw/communique/dl-1325-cc1e7976cf0246aca7c8fd1f14688a48.html
另與司法院各法院資訊核對：https://www.judicial.gov.tw/tw/cp-1898-119101-8a7a0-1.html
取得及核對日期：2026-10-03。無法確定行政區時不指定單一法院。
"""
import re

SOURCE_URL = "https://www.judicial.gov.tw/tw/communique/dl-1325-cc1e7976cf0246aca7c8fd1f14688a48.html"
NOTICE = "管轄區域以司法院公告為準；本建議不含合意管轄、專屬管轄等其他情形。"

CITY_COURTS = {
    "基隆市": ["臺灣基隆地方法院"], "桃園市": ["臺灣桃園地方法院"],
    "新竹市": ["臺灣新竹地方法院"], "新竹縣": ["臺灣新竹地方法院"],
    "苗栗縣": ["臺灣苗栗地方法院"], "臺中市": ["臺灣臺中地方法院"],
    "彰化縣": ["臺灣彰化地方法院"], "南投縣": ["臺灣南投地方法院"],
    "雲林縣": ["臺灣雲林地方法院"], "嘉義市": ["臺灣嘉義地方法院"],
    "嘉義縣": ["臺灣嘉義地方法院"], "臺南市": ["臺灣臺南地方法院"],
    "屏東縣": ["臺灣屏東地方法院"], "宜蘭縣": ["臺灣宜蘭地方法院"],
    "花蓮縣": ["臺灣花蓮地方法院"], "臺東縣": ["臺灣臺東地方法院"],
    "澎湖縣": ["臺灣澎湖地方法院"], "金門縣": ["福建金門地方法院"],
    "連江縣": ["福建連江地方法院"],
    "臺北市": ["臺灣臺北地方法院", "臺灣士林地方法院"],
    "新北市": ["臺灣臺北地方法院", "臺灣士林地方法院", "臺灣新北地方法院", "臺灣基隆地方法院"],
    "高雄市": ["臺灣高雄地方法院", "臺灣橋頭地方法院"],
}

_DISTRICTS = {
    "臺北市": {
        "臺灣臺北地方法院": "中正 松山 信義 文山 大安 萬華 中山",
        "臺灣士林地方法院": "士林 北投 大同 內湖 南港",
    },
    "新北市": {
        "臺灣臺北地方法院": "新店 烏來 深坑 石碇 坪林",
        "臺灣士林地方法院": "汐止 淡水 八里 三芝 石門",
        "臺灣新北地方法院": "土城 板橋 三重 永和 中和 新莊 蘆洲 三峽 樹林 鶯歌 泰山 五股 林口",
        "臺灣基隆地方法院": "瑞芳 貢寮 雙溪 平溪 金山 萬里",
    },
    "高雄市": {
        "臺灣高雄地方法院": "小港 旗津 前鎮 苓雅 新興 前金 三民 鼓山 鹽埕 鳳山 大寮 林園",
        "臺灣橋頭地方法院": "楠梓 左營 大樹 大社 仁武 鳥松 岡山 橋頭 燕巢 田寮 阿蓮 路竹 湖內 茄萣 永安 彌陀 梓官 旗山 美濃 六龜 甲仙 杉林 內門 茂林 桃源 那瑪夏",
    },
}
DISTRICT_COURTS = {city: {district + "區": court for court, names in groups.items()
                          for district in names.split()} for city, groups in _DISTRICTS.items()}


def resolve_address(address, basis="民事訴訟法第2條"):
    value = str(address or "").replace("台", "臺")
    city_match = re.search(r"(?:臺北|新北|桃園|臺中|臺南|高雄|基隆|新竹|嘉義)市|(?:新竹|苗栗|彰化|南投|雲林|嘉義|屏東|宜蘭|花蓮|臺東|澎湖|金門|連江)縣", value)
    if not city_match:
        return {"primary": None, "candidates": [], "note": "地址無法解析縣市，請人工確認"}
    city = city_match.group()
    courts = CITY_COURTS[city]
    tail = value[city_match.end():]
    district = re.match(r"([^\d\s]{1,4}區)", tail)
    district = district.group(1) if district else None
    if len(courts) > 1:
        selected = DISTRICT_COURTS.get(city, {}).get(district)
        if selected is None:
            return {"primary": None, "candidates": courts, "city": city, "district": district,
                    "basis": basis, "note": "需依行政區確認"}
        court = selected
    else:
        court = courts[0]
    return {"primary": {"court": court, "city": city, "district": district, "basis": basis,
                        "source_url": SOURCE_URL}, "candidates": [], "note": None}


def jurisdiction(address, branch_addresses=()):
    main = resolve_address(address)
    alternatives, seen = [], set()
    for branch in branch_addresses:
        resolved = resolve_address(branch, basis="民事訴訟法第6條")
        candidate = resolved["primary"]
        if candidate:
            if candidate["court"] in seen:
                continue
            seen.add(candidate["court"])
            alternatives.append({**candidate, "address": branch, "condition": "限該分公司業務涉訟"})
        elif resolved["candidates"]:
            for court in resolved["candidates"]:
                if court not in seen:
                    seen.add(court)
                    alternatives.append({"court": court, "address": branch, "basis": "民事訴訟法第6條",
                                         "condition": "限該分公司業務涉訟；需依行政區確認", "source_url": SOURCE_URL})
    return {"primary": main["primary"], "primary_candidates": main["candidates"],
            "alternatives": alternatives, "note": main["note"], "notice": NOTICE, "source_url": SOURCE_URL}
