# 兩個小修:重播帶商工查核、評估理由的重複用語

> 組長不在時交給組員(Claude Code)的第 1 批。兩個版本(`main-finals-fixes`、`pleading-exchange`)都用得到。
> 分支 `mff-small-fixes`,從 `origin/main-finals-fixes` `fdc2c0d` 開。

## 1. 要修的

| # | 問題 | 來源 |
|---|---|---|
| 1 | `export-demo` 會另外匯出 `recorded_party_checks.json`,但案件 fixture 不含 `party_checks` 表,`seed_if_empty` 只匯入 `_TABLES`。斷網重播時案件沒有商工查核,起訴審查卡片寫「本案尚未查核當事人商工登記」,機械彙整的程序事項區對有統編的原告寫「未提供統一編號」;要先到「當事人查核」按一次才正確 | [C1](C1-rerun.md) 交給使用者決定的 V39、[T6](T6-export-replay.md) V39 結果、審查 W8-5 |
| 2 | 評估理由顯示「對於 讓步條件 與讓步條件的逐條回應」,原文是「falsifier 與讓步條件」。`delabelJargon` 把 `falsifier` 換成「讓步條件」後和後面的中文重複 | 組長交辦 |

## 2. 做法

1. `server/seed.py`:`_TABLES` 加上 `("party_checks", PartyCheck)`。案件 fixture 因此多一張表,匯出時照既有規則跳過案件已不在 `cases` 表的列(孤兒列);沒有指定案件的單獨查詢照舊匯出(和 `write_party_checks` 一致)。匯入依原始 id 順序,所以每方「最新一筆」和錄製時相同。`orphan_rows` 原本另外加上 `party_checks`,現在 `_TABLES` 已含,改成直接用 `_TABLES`。
   - `recorded_party_checks.json` 照舊匯出、照舊用:它是「重新按查核、即時查詢失敗時」的錄製回退,只有統編,沒有案件與角色,不能拿來還原卡片。
   - 舊的 fixture(沒有 `party_checks` 鍵)照樣能匯入,該表 0 筆。
2. `ui/app.js`:`TEXT_JARGON` 最後加兩條,把代換後並列的重複說法收成一個:「讓步條件 與/和/及/、// 讓步條件」與「讓步條件(讓步條件)」(含「雙方讓步條件」)。放在最後,所以 `falsifier`、`weak_points` 先換完再收。只收「完全重複」的並列,「原告讓步條件與被告讓步條件」不動。

## 3. 實作紀錄

- 2026-11-03 12:10–12:25(組員,Claude Code)。基準 `fdc2c0d`。
- 基準離線全套:**331 通過、1 略過、13 未選**。

| # | 做了什麼 | 看到什麼 | 決定 |
|---|---|---|---|
| 1 | 讀 `seed.py`、`app.py`、`services.party_check_one`、`latest_party_checks`、T6 與 C1 的 V39 紀錄 | `recorded_party_checks.json` 沒有 `case_id`、`role`,卡片讀的是 `latest_party_checks(case_id)` | 不改那個檔的格式,改把 `party_checks` 表放進案件 fixture(C1 寫的「匯入時一併匯入」) |
| 2 | 先寫 `tests/test_seed_party_checks.py` 4 項 | 4 項紅燈 | 照預期 |
| 3 | `_TABLES` 加表、`orphan_rows` 去掉重複 | 新測試與 `test_server.py`、`test_gcis.py` 全過 | |
| 4 | 找「falsifier 與讓步條件」的原文 | `demo/recorded_cases.json` 的評估沒有這句(只有「原告falsifier(6)」這類),應是 C1 那次實跑的評估 | 用規則收重複,不針對單一句 |
| 5 | 先寫 `tests/test_ui_delabel.py`(用 node 執行 `app.js` 裡 `TEXT_JARGON` 到 `delabelJargon` 那段)再改 `app.js` | 對改之前的 `app.js` 跑:4 項紅、1 項綠(一般代換不變那項);改之後 5 項全過;`node --check ui/app.js` 通過 | |

- 做完離線全套:**340 通過、1 略過、13 未選**(多 9 項,都是新測試;沒有改既有測試的預期)。
- 新增測試:
  - `tests/test_seed_party_checks.py`
    - `test_case_party_checks_go_into_the_case_fixture`:案件 fixture 含商工查核;孤兒列不匯出;沒指定案件的照舊匯出。
    - `test_seeded_database_restores_the_latest_check_per_role`:匯入後 `latest_party_checks` 和來源資料庫完全相同(包括「後查的失敗那筆才是最新」)。
    - `test_old_fixture_without_party_checks_still_seeds`:舊 fixture 照樣匯入。
    - `test_replayed_case_shows_the_procedural_card_without_a_new_check`:空資料庫啟動、由 fixture 匯入後,`/api/cases/<id>` 不必再按查核就有商工查核。
  - `tests/test_ui_delabel.py`:「對於 falsifier 與讓步條件的逐條回應」→「對於讓步條件的逐條回應」;三種並列寫法;一般代換(含「原告讓步條件與被告讓步條件」)不變。沒有 node 時略過。
- 改了的檔:`server/seed.py`、`ui/app.js`、上面兩個測試檔、本文件、`README.md` 任務表。
- 沒驗證:
  - 沒有用真的示範資料庫重新匯出、斷網重播看畫面;`demo/recorded_cases.json` 沒有重新匯出(要等 11/4 版本定案,由組長在 W8/W11 匯出)。**重新匯出前,現在 `demo/` 裡的 fixture 仍然沒有商工查核**,重播時照舊要先按一次查核。
  - 沒有在瀏覽器看評估分頁,只用 node 執行同一段程式。C1 那句原文沒有在本機資料庫找到,測試用的是組長轉述的句子。
