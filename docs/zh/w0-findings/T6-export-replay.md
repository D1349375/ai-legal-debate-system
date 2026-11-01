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

- 開始時間:
- 結束時間:
- 基準 commit:
- 基準測試(指令與數字):

### 迭代過程

| # | 做了什麼 | 看到什麼 | 決定 |
|---|---|---|---|
| 1 | | | |

### 孤兒列

| 表 | 筆數 | 案件 ID |
|---|---|---|
| | | |

### V39 斷網重播結果

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

### 結果

- 最後測試(指令與數字):
- 新增測試與各自測什麼:
- 改了的檔:
- 暫存資料庫複本位置(本機,不進 git):
- 與本文件不同的做法與原因:
- 沒解決或沒驗證的事:

## 檢核結果(Claude 填寫)

- 日期:
- 結果:
- 要改的地方:
