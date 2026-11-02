"""把雙方論證裡的內部檢討段落濾掉:純函數、不碰 DB、不呼叫 LLM。

自我弱點寫進給法官看的論證，會被讀成承認(組員紀錄 001、002、003 都有)。main 不新增 JSON 欄位
(範本輸出欄位曾和 reasoning_extraction 分類器中止同時出現)，所以用標記段落隔開:法官、對手摘要、
書狀素材與自承檢查都只讀濾掉後的文字，資料庫與畫面保留全文給律師看。
"""
import re

START = "【內部檢討】"
END = "【內部檢討結束】"
# 只有開頭沒有結尾時，後面全部當內部檢討:寧可少給法官，不要外洩
_SECTION_RE = re.compile(re.escape(START) + r".*?(?:" + re.escape(END) + r"|\Z)", re.S)
_SELF_REVIEW_RE = re.compile(
    r"弱點|最大風險|最大缺口|對我方不利|對本方不利|我方不利|本方不利|基礎薄弱|自我檢討"
    r"|內部風險|力道會減弱|力道減弱|承認有疑義|承認[^。！？!?；;\n]{0,60}本有疑義"
)


def strip_internal_review(text):
    return _SECTION_RE.sub("", text or "").strip()


def review_warnings(text):
    """模型可能忘了標記或沒寫結尾。只能用關鍵字推測，所以只警告。"""
    text = text or ""
    warnings = []
    if text.count(START) != text.count(END):
        warnings.append(f"內部檢討段落沒有成對的 {END},後面的內容都不會給法官")
    leaked = sorted(set(_SELF_REVIEW_RE.findall(strip_internal_review(text))))
    if leaked:
        warnings.append("公開論證疑似含自我檢討(" + "、".join(leaked) + "),法官會讀到")
    return warnings
