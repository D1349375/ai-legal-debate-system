# T7 把 main-finals-fixes 合併進 pleading-exchange

- **分支 / 工作目錄**:`pleading-exchange` / `.claude/worktrees/pleading-exchange`
- **做的人**:Codex。檢核:Claude。前提:T1–T6 與 C1 都已完成並 commit。

## 為什麼

`pleading-exchange` 是從 `cf6f98c` 開出來的,T1–T6 修在 `main-finals-fixes`。新架構也要有這些修正,而且 W0 的根因(F1、F2、F3、F5、F7)在新分支一樣存在。

## 要做的

1. 確認兩個工作目錄都乾淨。`pleading-exchange` 有未 commit 的檔就停下來回報,不要 stash。
2. 在 `pleading-exchange` 執行 `git merge main-finals-fixes`(一般 merge,不要 rebase、不要 squash)。
3. 預期衝突的地方(兩邊都改過):`main.py`(新分支加了很多指令)、`server/live_run.py`(新分支改了 `DISALLOWED_TOOLS`、`SNAPSHOT_ENV`)、`server/app.py`、`server/services.py`、`database/db.py`。
   - `DISALLOWED_TOOLS`:新分支的既有規則**全部保留**,再加 T5 的 `PowerShell`。
   - `SNAPSHOT_ENV` 不動。
   - `server/services.py` `_anchor_check`、`get_case_detail`:新分支改過不少,T2 的比對邏輯要套在新分支的版本上,不要整段蓋掉。
   - 每個衝突怎麼解,寫進實作紀錄(檔案、衝突內容一句話、怎麼解、為什麼)。
4. T3、T4 的量測工具在新分支重跑一次(新分支的示範資料與 `protocol=v2` 案件),確認沒有新增誤擋或誤報。
5. 更新新分支的文件:
   - `docs/zh/pleading-exchange-handoff.md` 第 2 節:加一列「W0 後修正 T1–T6 已併入」,commit 先寫「未 commit」。
   - `docs/zh/iteration-log.md`:依該檔格式加一列,來源「實跑」(W0)與「查核」。
   - `docs/zh/pleading-exchange-plan.md` 的 W0 列改成已完成。

不要做:不 push;不併 `main`;不動組員維護的檢索模組。

## 測試

- 合併後離線全套測試(新分支基準約 427 項)全過。
- 連網測試 11 項(手冊第 4 節的指令)若環境可連網就跑,不能就寫「沒跑」。
- 另開埠(用暫存資料庫)用瀏覽器看一個舊案、一個 `protocol=v2` 新案,確認 UI 正常、機械彙整核對顯示正確。

## 完成定義

- merge 完成、沒有殘留衝突標記(`git grep -n '<<<<<<<'` 為空)。
- 測試數字寫進紀錄。

## 檢核方式(Claude)

- 看 merge commit 的衝突解法,特別是 `DISALLOWED_TOOLS`、`_anchor_check`。
- 跑全套測試;另開埠看 UI。

## 實作紀錄(Codex 填寫)

- 開始時間:
- 結束時間:
- 合併前兩邊的 commit:
- 合併前基準測試(指令與數字):

### 衝突與解法

| 檔案 | 衝突內容 | 解法 | 理由 |
|---|---|---|---|
| | | | |

### 迭代過程

| # | 做了什麼 | 看到什麼 | 決定 |
|---|---|---|---|
| 1 | | | |

### 結果

- 最後測試(指令與數字):
- T3、T4 量測在新分支的結果:
- 改了的檔(合併以外):
- 沒解決或沒驗證的事:

## 檢核結果(Claude 填寫)

- 日期:
- 結果:
- 要改的地方:
