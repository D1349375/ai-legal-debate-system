# T6 匯出到指定位置與斷網重播(F9、V39)

- **分支 / 工作目錄**:`main-finals-fixes` / `.claude/worktrees/main-finals-fixes`
- **做的人**:Codex。檢核:Claude。不需要 Claude 實跑。
- **調研**:[README 第 2 節 F9](README.md#f9-v39-沒跑匯出會寫進-git-的-fixture資料庫還有作廢那次的殘留)

## 問題

V39 要求「新案件用 `export-demo` 匯出後,乾淨 clone 斷網可重播」,W0 沒做,因為:

- `python main.py export-demo` 一定寫到 `demo/recorded_cases.json`(進 git),沒辦法先匯到別處驗證。
- `server/seed.py` `export_fixture` 匯出**整顆資料庫**。worktree 資料庫有 W0 第 1 次(作廢,案件 ID `live-2026-11-02-gcis-w0`)的論證、訊問、評估、書狀,沒有對應案件列,會一起匯出。
- `demo/recorded_live_checks.json` 的 `checks` 在本分支是 0 筆(`main` 是 2 筆),斷網示範「查無字號」可能沒有錄製結果。

## 要做的

1. **`export-demo` 加 `--out <資料夾>`**:三個 fixture 檔都寫到該資料夾,不寫 `demo/`。沒給時維持現行行為。
2. **孤兒列檢查**:`_TABLES` 裡有 `case_id` 欄位的表(`debate_arguments`、`court_questions`、`verdicts`、`pleading_drafts`),匯出前找出 `case_id` 不在 `cases` 表的列,**不匯出**,並在輸出列出各表筆數與案件 ID。`citation_verifications` 沒有 `case_id`,照舊全部匯出。不刪資料庫裡的列。商工查核(`--party-checks`)另走 `write_party_checks`,一併檢查是否有同樣問題,有就同樣處理。
3. **做 V39**(不改進 git 的 `demo/`):
   1. 把 `database/legal_debate.db` **複製**到暫存資料夾,以 `LEGALDEBATE_DB_URL` 指向複本(T1 完成後伺服器與指令都會用它)。
   2. `python main.py export-demo --out <暫存>/fixture`(要不要加 `--live-checks` 見第 4 點)。
   3. 另開一個乾淨 clone(暫存資料夾,`git clone` 本機分支即可),把暫存 fixture 放進該 clone 的 `demo/`。
   4. 在 clone 內斷網(或設定讓連網查證失敗)啟動 `python main.py serve --port <未用的埠> --no-browser`,用瀏覽器打開 W0 案件 `live-2026-11-02-gcis-w0b`,逐分頁確認能顯示:總覽、起訴前檢查、攻防、評估、引用查證、兩份書狀。
   5. 記下哪些分頁或功能在斷網時顯示「查證失敗」或空白,照實寫,不要修飾。
4. **`recorded_live_checks.json` 0 筆的影響**:查清楚斷網時「查無字號」示範需要哪些錄製結果、目前缺什麼。`--live-checks` 需要連網,**先不跑**,寫出建議交給使用者決定。
5. 用完刪掉暫存 clone;暫存資料庫複本保留,路徑寫進紀錄(紀錄不進 git 的部分可寫本機路徑,進 git 的文件不寫)。

不要做:不覆寫 `demo/` 下任何檔;不刪資料庫裡的孤兒列;不跑需要連網的 `--live-checks`。

## 測試(先寫)

- `--out` 寫到指定資料夾,`demo/` 檔案不變。
- 有孤兒列時不匯出、輸出列出筆數。
- 既有 export / seed 測試仍過。

## 完成定義

- 測試全過;離線全套通過數 = 基準 + 新增數。
- 實作紀錄有 V39 逐分頁結果表。
- `git status` 顯示 `demo/` 沒有變動。

## 檢核方式(Claude)

- 讀 diff;確認 `demo/` 未變。
- 依紀錄的暫存位置,自己開一次斷網重播抽查。
- 把 V39 結果更新到 `docs/zh/main-finals-fix-list.md` 與 `docs/live-run-records/w0-2026-11-02.md`。

## 實作紀錄(Codex 填寫)

> 本項由組員以 Claude Code 實作(不是 Codex),工作分支 `t6-export-out`。依組長分工,組員只做第 1、2 點(`--out` 與孤兒列);第 3–5 點的 V39 斷網重播、`recorded_live_checks.json` 的建議由組長做,下面兩節留空。

- 開始時間:2026-11-02 21:33
- 結束時間:2026-11-02 21:50
- 基準 commit:`982075a`(`main-finals-fixes`);commit 前改接在 `t5-windows-tools`(`998d66b`)之後,見迭代第 8 列
- 基準測試(指令與數字):`python -m pytest -q -m "not network" --basetemp <暫存資料夾>` → `307 passed, 1 skipped, 13 deselected`(在 `982075a`)

### 迭代過程

| # | 做了什麼 | 看到什麼 | 決定 |
|---|---|---|---|
| 1 | 讀 `server/seed.py`、`main.py` `cmd_export_demo` 與既有測試 | 有 `case_id` 的表是 `debate_arguments`、`court_questions`、`verdicts`、`pleading_drafts`;`party_checks` 也有 `case_id`(可為空,UI 單獨查詢時就是空),但匯出的商工檔只有統編、時間與回應,不帶 `case_id`,重播以統編比對 | 商工查核同樣處理:`case_id` 有值且不在 `cases` 表的不匯出;`case_id` 為空的單獨查詢照舊匯出 |
| 2 | 先寫 3 個測試,第一次跑紅燈 | 新的 CLI 測試在 `--out` 還不存在時照舊寫進 worktree 的 `demo/`,把 `recorded_cases.json`、`recorded_party_checks.json` 蓋掉 | `git checkout -- demo/` 還原。測試改成把 `seed.FIXTURE_PATH` 等三個常數指到暫存的假 `demo/` |
| 3 | 再跑一次紅燈 | `demo/` 又被蓋掉:`write_fixture(session, path=FIXTURE_PATH)` 的預設值在定義時就綁定,改模組常數沒用 | 再還原。實作改成 `cmd_export_demo` 每次都明確傳路徑(呼叫當下讀常數),這樣測試的替換才有效;之後的綠燈與全套測試 `demo/` 都沒再變動 |
| 4 | `seed.py` 加 `orphan_rows`(只列出,不刪)、`export_fixture` 與 `write_party_checks` 跳過孤兒列;`main.py` 加 `--out`,匯出前逐表印出不匯出的筆數與案件 ID | 新測試過;舊的 `test_export_demo_flag_keeps_existing_live_checks_behavior` 失敗,因為它的替身函數只收 `session`,而且以 `object()` 當 session | 替身改成收 `session, path`、另替換 `orphan_rows`,`SimpleNamespace` 補 `out=None`。斷言(呼叫哪些匯出、順序)沒改 |
| 5 | 離線全套 | `310 passed, 1 skipped, 13 deselected` | 通過數 = 基準 307 + 新增 3 |
| 6 | 用本機資料庫的**複本**實跑 `export-demo --out <暫存>` 與 `--party-checks --out <暫存>` | 這顆資料庫沒有孤兒列,5 件案件全匯出;商工 0 筆;`demo/` 沒變 | 為了在真資料上看到孤兒列,在**複本**刪掉一筆案件列再匯出 |
| 7 | 同上,複本刪掉 `test-2026-08-08-001` 的案件列 | 印出 4 行「不匯出」:論證 6、訊問 4、評估 1、書狀 1 筆;fixture 剩 4 件,`citation_verifications` 166 筆照舊 | 符合預期 |
| 8 | T5 與 T6 都在 `main-finals-fix-list.md` 文末加一列,分開合併會衝突 | rebase 到 `origin/t5-windows-tools` 時該檔衝突,兩列都保留 | T6 接在 T5 之後;組長先合 T5 再合 T6 就不會衝突。重跑全套 `312 passed, 1 skipped, 13 deselected`(T5 後的 309 + 新增 3) |

### 孤兒列

本機資料庫沒有孤兒列(迭代第 6 列)。W0 第 1 次作廢的 `live-2026-11-02-gcis-w0` 在組長那顆 worktree 資料庫,組長跑 `export-demo --out` 時會印出實際筆數。

| 表 | 筆數 | 案件 ID |
|---|---|---|
| (本機無) | 0 | — |

### V39 斷網重播結果

由組長做,本次沒做。

| 分頁 / 功能 | 結果 | 說明 |
|---|---|---|
| 總覽 | | |
| 起訴前檢查 | | |
| 攻防 | | |
| 評估 | | |
| 引用查證 | | |
| 起訴狀 | | |
| 答辯狀 | | |

### `recorded_live_checks.json` 的影響與建議

由組長做,本次沒查。`--out` 也套用到 `--live-checks`(寫到同一個資料夾),組長之後要錄製時可以先寫到暫存位置。

### 結果

- 最後測試(指令與數字):`python -m pytest -q -m "not network" --basetemp <暫存資料夾>` → `312 passed, 1 skipped, 13 deselected`(接在 T5 後,基準 `309 passed`;只在 `982075a` 上時是 `310 passed`)
- 新增測試與各自測什麼:
  - `tests/test_server.py` `TestSeed.test_orphan_rows_are_listed_and_left_out_of_the_fixture`:論證與訊問各一筆屬於不存在的案件時,`orphan_rows` 列出兩表各 1 筆;fixture 不含這兩筆,其他筆數不變;資料庫的列仍在。
  - `tests/test_server.py` `TestSeed.test_export_demo_out_writes_elsewhere_and_leaves_demo_alone`:`export-demo --out` 與 `--party-checks --out` 把檔寫到指定資料夾,預設位置的檔內容不變;輸出列出孤兒列的表名與案件 ID。
  - `tests/test_gcis.py` `test_party_check_export_skips_rows_of_cases_no_longer_in_the_database`:三筆商工查詢(案件存在、未指定案件、案件不存在)只匯出前兩筆;`orphan_rows` 列出 `party_checks` 1 筆;資料庫仍是 3 筆。
- 改了的檔:
  - `server/seed.py`:新增 `orphan_rows`;`export_fixture`、`write_party_checks` 跳過案件已不在 `cases` 表的列。
  - `main.py`:`export-demo --out`;匯出前印出孤兒列;三種匯出都明確傳路徑;用法說明加 `--out`。
  - `tests/test_server.py`、`tests/test_gcis.py`:新增 3 個測試;既有 `export-demo` 旗標測試的替身函數配合新呼叫方式(迭代第 4 列)。
  - 本文件與 `docs/zh/main-finals-fix-list.md`:實作紀錄。
- 暫存資料庫複本位置(本機,不進 git):組員電腦的 Claude Code 暫存資料夾 `t6real/copy.db`(其中一筆案件列已刪,只供驗證孤兒列,不要拿來重播)。
- 與本文件不同的做法與原因:
  - 第 3–5 點(V39 斷網重播、乾淨 clone、`recorded_live_checks.json` 建議)依組長分工由組長做。
  - 既有測試 `test_export_demo_flag_keeps_existing_live_checks_behavior` 的替身函數簽名有改,斷言沒改(迭代第 4 列)。
- 沒解決或沒驗證的事:
  - 沒在組長那顆有 W0 作廢殘留的資料庫上跑過,實際孤兒筆數待組長匯出時確認。
  - `seed_if_empty` 匯入時不檢查孤兒列;既有的 `demo/recorded_cases.json` 有沒有孤兒列沒查(本次不改 `demo/`)。

## 檢核結果(Claude 填寫)

- 日期:2026-11-02
- 結果:**第 1、2 點通過**(第 3–5 點 V39 由組長另做,見下)。
  - `--out` 三種匯出都寫到指定資料夾,沒給時維持寫 `demo/`;測試把預設路徑指到暫存的假 `demo/`,就算 `--out` 失效也不會覆寫進 git 的檔。
  - 孤兒列只列出、不匯出、不刪;商工查核 `case_id` 為空的單獨查詢照舊匯出,合理。
  - Claude 在暫存 worktree 重跑離線全套:`312 passed, 1 skipped, 13 deselected`,和紀錄一致。
  - Claude 用 W0 資料庫**複本**跑 `export-demo --out <暫存>`:印出作廢那次 `live-2026-11-02-gcis-w0` 的論證 6、訊問 7、評估 1、書狀 2 筆不匯出;fixture 6 件案件,`citation_verifications` 100 筆;worktree 的 `demo/` 沒變。
- 待做(組長):V39 斷網重播、`recorded_live_checks.json` 0 筆的影響與建議。
- 要改的地方:無。
