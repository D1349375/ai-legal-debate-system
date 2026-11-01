"""全部測試共用：檢索快取一律改到暫存目錄，不讀也不寫 database/retrieval_cache/ 與實跑快照。"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from engine import retrieval_cache, verify


@pytest.fixture(autouse=True)
def isolated_retrieval_cache(tmp_path, monkeypatch):
    path = tmp_path / "retrieval_cache"
    monkeypatch.setenv(retrieval_cache.CACHE_ENV, str(path))
    monkeypatch.delenv(verify.SNAPSHOT_ENV, raising=False)
    return path


@pytest.fixture
def seed_article(isolated_retrieval_cache):
    """在暫存快取放一筆條文：seed_article("B0000001", "197", days_old=10)。"""
    def seed(pcode, flno, days_old=0, text=None, law_name="民法"):
        fetched = (datetime.now(timezone.utc) - timedelta(days=days_old)).strftime('%Y-%m-%dT%H:%M:%SZ')
        entry = {"kind": "statute", "law_name": law_name, "pcode": pcode, "article_no": flno, "modified_date": "20260817",
                 "url": f"https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode={pcode}&flno={flno}",
                 "fetched_at": fetched, "origin": "live", "text": text or f"第 {flno} 條\n快取條文"}
        folder = isolated_retrieval_cache / "statutes"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{pcode}_{flno}.json").write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
        return entry
    return seed
