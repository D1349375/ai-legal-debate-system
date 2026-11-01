"""判決全文整理：去排版換行、擷取主文與引用法條、判斷程序駁回。上網抓回與本地語料共用。

判決原文約每 30 字換行並縮排，詞組跨行時 grep 找不到(本地語料實測漏掉 5～15%)。flatten 只移除空白、
不改任何文字，查證端比對摘句時同樣忽略空白(verify.verify_precedent_note)，所以從整理後全文複製的摘句
可直接通過查證。

純函數、不連網；法規名稱索引(corpus/statutes/law_index.json)僅在擷取法條時延遲載入。
"""
import re

_WHITESPACE = re.compile(r'\s+')
# 文種為裁定、主文第一句是短句且以「（上訴／抗告／聲請／…之訴）駁回」結尾者，視為程序駁回(上訴不合法、
# 抗告無理由等)，對實體爭點參考價值低。主文寫法多樣(「上訴人之上訴均駁回」「上訴及擴張之訴均駁回」)，只看結尾。
_PROCEDURAL_DISPOSITION = re.compile(r'^[^。]{0,24}(?:上訴|抗告|聲請|之訴)(?:均)?駁回。$')
# 第三審程序套語：本地語料中各出現在數十至數百份裁判，直接拿來搜尋會淹沒實體見解，另列不混入實體法條。
PROCEDURAL_BOILERPLATE = {
    ('民事訴訟法', n) for n in (
        '78', '85', '87', '95', '249', '444', '449', '466', '466-1', '466-3', '467', '468', '469', '469-1',
        '470', '471', '475', '476', '477', '477-1', '478', '481', '484', '486', '490', '491', '495-1', '496',
        '502', '507',
    )
}
_CITATION = re.compile(r'第(\d+)條(?:之(\d+))?')
# 「民事訴訟法第467條、第469條之1」：與前一條之間只隔項款與連接詞時，沿用前一條的法規名。
_LISTED_AFTER = re.compile(r'(?:第\d+項|第\d+款|第\d+目|前段|後段|但書|本文|[、及與暨或])+')
_DEFINED_ALIAS = re.compile(r'([^，。；（）]{2,30}?)（下稱([^，。；（）]{2,12})）')
_TRAILING_PAREN = re.compile(r'（[^（）]{0,15}）$')


def _longest_name(before, names):
    """→ before 的後綴中，最長且是已知法規名的那一段；沒有則 None。"""
    return next((before[i:] for i in range(len(before)) if before[i:] in names), None)
_NAME_WINDOW = 20


def flatten(text):
    """→ 移除所有空白後以句號斷行，一句一行。"""
    flat = _WHITESPACE.sub('', text or '')
    return re.sub(r'(?<=。)(?!$)', '\n', flat)


def document_type(text):
    first = next((line.strip() for line in (text or '').splitlines() if line.strip()), '')
    m = re.search(r'(判決|裁定)', first)
    return m.group(1) if m else None


def disposition(text):
    """→ 主文第一句；找不到「主文…理由」結構時回 None(例如部分裁定沒有分段標題)。"""
    flat = _WHITESPACE.sub('', text or '')
    m = re.search(r'主文(.+?)理由', flat)
    if not m:
        return None
    return m.group(1).split('。')[0] + '。'


def is_procedural(doc_type, disposition_text):
    return doc_type == '裁定' and bool(disposition_text) and bool(_PROCEDURAL_DISPOSITION.match(disposition_text))


def law_names():
    """→ {判決中可能出現的法規名稱: 官方全名}；查證引擎認得的簡稱(如「勞基法」)對應到全名。"""
    from engine.law_lookup import load_law_index, resolve_law
    from engine.verify import STATUTE_PCODES
    index = load_law_index()
    names = {name: name for name in index}
    for alias in STATUTE_PCODES:
        names.setdefault(alias, (resolve_law(alias, index) or {}).get('law_name', alias))
    return names


def cited_statutes(text, names=None):
    """→ (實體法條, 程序套語法條)，皆依出現順序去重，格式如「民法第184條」「民事訴訟法第469條之1」。

    法規名稱取「第N條」前方文字中、索引裡最長的法規名，避免把「如依同法」「上訴人依民法」整段當名稱；
    「同法第N條」還原為前一個法規名。names 為 law_names() 的對照表，批次處理時由呼叫端傳入以免重複載入。
    """
    names = dict(law_names() if names is None else names)
    flat = _WHITESPACE.sub('', text or '')
    # 「公平交易法（下稱修正前公平法）第31條」：括號內定義的簡稱之後也會單獨出現，先登記成別名。
    for m in _DEFINED_ALIAS.finditer(flat):
        law = _longest_name(m.group(1), names)
        if law:
            names.setdefault(m.group(2), names[law])
    substantive, boilerplate, previous, previous_end = [], [], None, 0
    for m in _CITATION.finditer(flat):
        before = flat[max(0, m.start() - _NAME_WINDOW):m.start()]
        gap = flat[previous_end:m.start()]
        if previous and (before.endswith('同法') or _LISTED_AFTER.fullmatch(gap)):
            name = previous
        else:
            found = _longest_name(_TRAILING_PAREN.sub('', before), names)
            if found is None:
                # 認不出法規名時清掉前一個法規，避免後面的「同法第N條」接到更早的法規。
                previous, previous_end = None, m.end()
                continue
            name = names[found]
        previous, previous_end = name, m.end()
        number = m.group(1) + (f'-{m.group(2)}' if m.group(2) else '')
        label = f"{name}第{m.group(1)}條" + (f"之{m.group(2)}" if m.group(2) else '')
        bucket = boilerplate if (name, number) in PROCEDURAL_BOILERPLATE else substantive
        if label not in bucket:
            bucket.append(label)
    return substantive, boilerplate


def matched_sentences(text, keywords, limit=3):
    """→ 含任一關鍵字的句子(整理後全文的整行)，最多 limit 句。"""
    keys = [_WHITESPACE.sub('', k) for k in keywords if k and k.strip()]
    if not keys:
        return []
    return [line for line in flatten(text).splitlines() if any(k in line for k in keys)][:limit]


def summarize(text, keywords=(), names=None):
    doc_type = document_type(text)
    main = disposition(text)
    statutes, boilerplate = cited_statutes(text, names)
    return {
        'doc_type': doc_type,
        'disposition': main,
        'procedural_only': is_procedural(doc_type, main),
        'statutes': statutes,
        'procedural_statutes': boilerplate,
        'matched_sentences': matched_sentences(text, keywords),
    }
