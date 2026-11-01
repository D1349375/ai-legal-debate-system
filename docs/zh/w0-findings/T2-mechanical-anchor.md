# T2 機械彙整改由程式落地(F2)

- **分支 / 工作目錄**:`main-finals-fixes` / `.claude/worktrees/main-finals-fixes`
- **做的人**:Codex。檢核:Claude。實跑驗證:C1。
- **調研**:[README 第 2 節 F2](README.md#f2-主-agent-改寫了機械彙整再落地)

## 問題

`mechanical_anchor_json` 由 `python main.py finalize` 算出,再由主 agent 抄進 verdict JSON,`main.py verdict` 原樣存入。W0 的主 agent 把 `weak_points[].response_excerpt`(雙方 Stage 3 全文)換成「摘錄從略」,也刪了 `procedural_issues` 的欄位。UI 標示這份資料是機械彙整,實際上被模型改過;`_anchor_check` 只比 `position_drift` 與 `falsifier`,所以畫面仍顯示一致。

相關程式:

| 位置 | 現況 |
|---|---|
| `main.py` `cmd_verdict` | `mechanical_anchor_json=payload["mechanical_anchor_json"]` |
| `database/db.py` `finalize_case` | 決定性函數,回傳 `weak_points`、`position_drift`、`procedural_issues` |
| `database/db.py` `record_verdict` | 原樣存入 |
| `engine/aggregate.py` `compile_weak_points` | `response_excerpt` = 該方 Stage 3 完整 `reasoning` |
| `server/services.py` `_anchor_check` | 只比 `position_drift`、`falsifier` |
| `.claude/skills/legal-debate/SKILL.md` Step 6、Step 8 | 說 verdict JSON 要含 `mechanical_anchor_json` |
| `tests/fake_claude.py`、`tests/test_cli.py` | 假資料有帶 `mechanical_anchor_json` |

## 要做的

1. **`main.py verdict` 自己算**:落地時呼叫 `finalize_case(session, case_id=...)`,把結果存成 `mechanical_anchor_json`,不讀模型給的版本。
   - payload 沒有這個欄位時照常落地(這是新的正常情況)。
   - payload 仍帶了這個欄位,且和重算結果不同:照常用重算結果落地,stderr 印一行警告,說明模型給的版本與機械彙整不同、已改用機械結果。相同就不印。
   - 雙方 Stage 3 沒齊時 `finalize_case` 會丟 `ValueError`,照現有方式印「拒絕落地」。
2. **`_anchor_check` 比對全部欄位**:`position_drift`、每方 `falsifier`(保留現有「只差括號」的 minor 判斷)、每方 `response_excerpt`、`procedural_issues` 的 issue id 集合。
   - **先量測舊資料**:用 `demo/recorded_cases.json` 匯入暫存資料庫,列出哪些既有案件在新比對下會變成不一致、差在哪個欄位。結果寫進實作紀錄。
   - 舊案若是因為落地時被摘略(例如 `response_excerpt` 含「從略」),UI 要照實顯示「落地時的機械彙整與重算不同(某欄位)」,**不要藏起來,也不要說成被竄改**;用一個獨立的分類(例如 `stored_differs`),和現有的 `differences` 分開,讓畫面能說清楚。具體文字在實作紀錄寫出來給 Claude 檢核。
   - `procedural_issues` 會因之後重新查核商工而改變,只比 issue id,不比文字。
3. **SKILL 與說明**:
   - SKILL Step 6:第一個 `finalize` 指令改為「只供核對,不用抄進 verdict JSON」。
   - SKILL Step 8 的 verdict JSON 欄位清單移除 `mechanical_anchor_json`,並寫明 `main.py verdict` 會自行重算存入。
   - SKILL 第 17 行的禁止規定保留。
   - `server/live_run.py` 給主 agent 的 prompt 若有提到這個欄位,一起改。
4. **假資料**:`tests/fake_claude.py` 改成不帶這個欄位(模擬新行為);另留一個測試帶「被改過的版本」驗證會改用重算結果並警告。

不要做:不改 `engine/aggregate.py` 的輸出格式(`response_excerpt` 存全文是既有設計,UI 已依賴);不刪資料庫欄位。

## 測試(先寫)

- payload 不帶 `mechanical_anchor_json`:落地成功,存入的值等於 `finalize_case` 結果。
- payload 帶了被改過的版本(`response_excerpt` 換成「從略」):落地成功,存的是重算結果,stderr 有警告。
- payload 帶了和重算相同的版本:不警告。
- `_anchor_check`:竄改 `response_excerpt` 或拿掉一個 procedural issue 時能看出來;既有三個 anchor 測試仍過。
- 舊示範資料的量測結果(不是自動測試,寫進紀錄)。

## 完成定義

- 測試全過;離線全套通過數 = 基準 + 新增數。
- 示範資料匯入後,UI 對每個舊案的 anchor 顯示有明確說明,沒有出現錯誤或空白;用瀏覽器看過至少一個舊案與一個新案(另開埠與暫存資料庫,見手冊「worktree 驗證」)。
- 實作紀錄列出量測表:案件 ID、哪個欄位不同、畫面顯示什麼。

## 檢核方式(Claude)

- 讀 diff 與量測表,確認舊案顯示誠實且不誤導。
- 跑全套測試;另開埠看 UI。
- C1 實跑:主 agent 的 verdict JSON 不再含這個欄位(或含了也被替換),落地值等於重算值,UI 顯示一致。

## 實作紀錄(Codex 填寫)

- 開始時間:
- 結束時間:
- 基準 commit:
- 基準測試(指令與數字):

### 迭代過程

| # | 做了什麼 | 看到什麼 | 決定 |
|---|---|---|---|
| 1 | | | |

### 舊示範資料量測

| 案件 ID | 不同的欄位 | 原因判斷 | 畫面顯示 |
|---|---|---|---|
| | | | |

### 結果

- 最後測試(指令與數字):
- 新增測試與各自測什麼:
- 改了的檔:
- 與本文件不同的做法與原因:
- 沒解決或沒驗證的事:

## 檢核結果(Claude 填寫)

- 日期:
- 結果:
- 要改的地方:
