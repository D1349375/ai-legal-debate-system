# 組員協作規則(書狀交換改版,決賽前)

> 2026-11-02 起適用,到 11/5 晚上程式凍結。組長與組員都照這份做。
> 「組長」包含組長和他開的 Claude Code session;「組員」包含組員和組員開的 Claude Code session。
> 這份和其他文件說法不同時,以這份為準。

## 1. 分工

照**檔案**分,不照 W 項目分。新流程是一條直線(P1 → P2 → P3 …),每個 W 都要改 `SKILL.md`、範本、`server/`,兩個人各拿一個 W 一定衝突。所以每個 W 拆成兩半:

| 誰 | 負責 | 碰哪些檔 |
|---|---|---|
| **組員** | 每個 W 的**純程式**:檢查函數、組成書狀、資料表、CLI 指令、測試。永遠比組長早一步 | `engine/`、`database/`、`main.py` 的新指令、`scripts/`、`tests/`;檢索相關檔案本來就是組員的 |
| **組長** | 所有**接線**:`SKILL.md`、`templates/`、`server/`、`ui/`;T7 合併;所有分支的檢核與合併 | 上述以外,加上把組員的程式接進流程 |

實跑兩邊都可以跑,條件見第 6 節。

### 1.1 組員的順序

| 順序 | 項目 | 內容 | 備註 |
|---|---|---|---|
| 1 | W4 後半 | `scripts/audit_run.py`(解析 `stream.jsonl`,列出每個 subagent 讀過哪些檔;W4 實跑和 W8 的 X8 稽核都要用)、`main.py answer`、答辯狀組成(T4.6) | 先做 `audit_run.py`,組長接 W4 實跑就要用 |
| 2 | W5 程式 | `IssueSheet` 資料表、`engine/issue_sheet.py` 檢查(T5.1、T5.2、T5.5)、`main.py issue-sheet`、加進匯出 `server/seed.py` `_TABLES`;加上[舊設計殘留](v2-old-design-leftovers.md)第 1 項(自承檢查的來源加入起訴狀與答辯狀) | 第 1 項會卡住 W5 實跑,和 W5 一起做。法官範本、`check-judge` 的接線、UI 留給組長 |
| 3 | W6 程式 | `main.py brief` 組成書狀、爭點涵蓋檢查、第 255 條警告(T6.1–T6.3) | |
| 4 | W7 程式 | v2 起訴狀檢查(T7.1–T7.4)、`risk_map` 新鍵的結構檢查 | [舊設計殘留](v2-old-design-leftovers.md)第 2 項等組長決定 A 或 B 後才做 |
| 5 | T9 程式 | `check-summary`(對手摘要逐字、條件句警告) | |
| 隨時 | 檢索 | 實跑時發現的檢索問題 | |

[舊設計殘留](v2-old-design-leftovers.md)第 3、4 項由組長在 W8 做;第 5 項(續跑指示的 Step 1.5)W3 已處理:v2 的續跑指示(`server/live_run.py` `resume_instructions_v2`)沒有 Step 1.5,剩下那句只在舊流程。

## 2. 分支

1. **不要直接 push `pleading-exchange`、`main-finals-fixes`、`main`。** 一律從目標分支開工作分支,做完 push 工作分支,然後跟組長說一聲。合併由組長做。
2. 一個項目一條分支,名稱寫項目,例如 `w4-answer`、`w5-issue-sheet`、`t9-check-summary`。
3. **開工前**先 pull 目標分支的最新版。**通知組長前**再把目標分支的最新版合併(或 rebase)進工作分支、跑一次全套。目標分支是 `pleading-exchange`(W 系列與 T8、T9)或 `main-finals-fixes`(T1–T6)。
4. 不要合併 `retrieval-optimization`、`role-separation-redesign`。
5. 共用檔 `main.py`、`database/db.py` 兩邊都會加東西:新指令、新函數加在獨立的位置(檔尾或該區塊最後),不要順手重排或改既有函數的寫法,這樣合併通常會自動成功。
6. 不改 `SKILL.md`、`templates/`、`server/`、`ui/`。真的需要改,先跟組長說,由組長改或同意後再改。要給範本的建議寫在文件裡(例如 T8 的 `docs/zh/t8-statute-claims.md` 那樣)。

## 3. 開工前先對齊介面

每個 W 開工前,和組長確認:函數名稱、CLI 參數、JSON 欄位名稱與型別、錯誤訊息怎麼回。依據是 [pleading-exchange-spec.md](pleading-exchange-spec.md) 和[計畫](pleading-exchange-plan.md)。**規格沒寫清楚的地方先問,不要猜**,猜錯就要重做。

目前要對齊的:

| 項目 | 現況 | 怎麼做 |
|---|---|---|
| W4 被告讀哪一版起訴狀 | `defendant_view(session, case_id, complaint_id=None)` 沒給版本時用最新系統原稿 | W3 已有 `database/db.py` `current_complaint`(關卡 1 確認版;還沒確認時是最新系統原稿)。組長接 W4 時改成沒給 `complaint_id` 就用 `current_complaint`;組員之後的程式照這個介面 |
| 答辯狀的欄位 | 規格 5.4 | `main.py answer` 開工前確認 `responses`、`legal_argument`、引用欄位名稱 |

## 4. 實作紀錄

**邊做邊寫,不要做完才補。**

- W 系列寫在[計畫](pleading-exchange-plan.md)第 6 節進度表該 W 那一列(寫明「程式部分完成,分支 xxx,接線待組長」),細節寫進 [iteration-log.md](iteration-log.md) 一列。
- T 系列寫在 `main-finals-fixes` 的 `docs/zh/w0-findings/` 該任務文件的「實作紀錄」。
- 要寫:開始與結束時間、基準 commit、基準測試數字、每次嘗試「做了什麼 → 看到什麼 → 決定怎麼改」(失敗的也寫)、最後測試數字、新增哪些測試各測什麼、改了哪些檔、和計畫不同的地方、沒做或沒驗證的事。

### 測試

- 開工前跑一次離線全套記基準,做完再跑一次:`python -m pytest -q -m "not network" --basetemp <暫存資料夾>`。Windows 上一定要加 `--basetemp`。
- 先寫測試再實作。新的測試盡量放新檔(例如 `tests/test_issue_sheet.py`),少改共用的測試檔。
- 不為了讓測試通過而改既有測試的預期;真的要改,在紀錄寫原因。

## 5. 檢核與合併(組長)

1. 組員通知後,組長看 diff、跑全套,必要時在瀏覽器看畫面。組長電腦記憶體只有 8 GB,全套一次只能跑一組,所以會把幾條分支合在一起測,不一定馬上回。
2. 通過:組長合併進目標分支、push,並在紀錄寫「Claude 檢核通過(日期)」。
3. 不通過:組長寫出要改的地方,組員在同一條分支改完再通知。
4. 合併時遇到的衝突由組長解,解法寫在合併 commit 與 iteration-log。

## 6. 實跑

兩邊都可以跑。條件:

1. **寫明跑的是哪個 commit。** 接線(`SKILL.md`、範本)由組長改,要確認跑的是接好線的版本。
2. **紀錄照 `docs/live-run-records/` 的格式寫**:日期、案件 ID、commit、時間、花費、5 小時額度前後百分比、分類器中止次數、權限被拒次數、結果、發現的問題。**失敗的那幾次也要寫。**
3. **把原始檔傳給組長檢核。** `database/live_runs/` 不進 git,另外傳該次執行資料夾的 `stream.jsonl`、`events.jsonl`、`prompt.txt`(壓縮後傳)。`audit_run.py` 做好後,先自己跑一次,結果附進紀錄。
4. **作業系統寫進紀錄。** PowerShell 這類問題只在 Windows 出現;不是 Windows 跑的「權限被拒 0」不能當成 Windows 也沒問題。
5. **開跑前看 CLI 登入的帳號與額度**(`stream-json` 的 `rate_limit_event` 是 CLI 帳號的,不是桌面 app 的)。全程一次約 12–15 分鐘、3 美元、5 小時額度約 25%。
6. **決賽要展示的案件在組長電腦跑。** 示範資料是整顆資料庫匯出,兩台電腦的案件合不起來。開發中的驗證誰跑都可以;W8 全程實跑與 W11 匯出示範在組長電腦。
7. 示範案的來源裁判(例如 114年度台上字第1987號)在 `corpus/judgments/`。跑完用 `audit_run.py` 或搜尋紀錄確認沒有讀到;讀到就照實寫,不能拿來講「命中」。

## 7. 共同規則

1. 回覆與文件用繁體中文;commit 訊息用英文、祈使句。
2. **公開 repo**:不 commit 資料庫(`database/legal_debate.db`)、`database/live_runs/`、本機絕對路徑、語料全文、個資。量測腳本與輸出放暫存資料夾。
3. **誠實原則**:錄製的要標錄製;查證失敗要顯示;單一案件不是統計;**不手改模型產出的 JSON 後說是模型產出**;沒驗證的寫沒驗證。
4. **不捏造事實**:例如已解散公司的清算人姓名,沒有資料就寫「待查明」。
5. 輸出欄位命名不用 `reasoning`、`thinking`、`trace`、`analysis`、`internal`、`scratch`(分類器風險)。
6. 檢查規則:結構可以硬擋,自然語言只警告;同一份輸出最多退回 2 次。
7. 不放寬 `server/live_run.py` 的 `ALLOWED_TOOLS`;不改 `SNAPSHOT_ENV`、`DISALLOWED_TOOLS` 既有規則。
8. 不用中國機構開發的模型、API 或 MCP。
9. W0 的資料庫(組長電腦 `main-finals-fixes` worktree 的 `database/legal_debate.db`)不能寫入,要用就先複製。

## 8. 時程

- 11/3:W3–W7(組員程式先行,組長接線)。
- 11/4 上午:W8 全程實跑。
- 11/4 晚:決定決賽用 `pleading-exchange` 還是 `main-finals-fixes`。
- 11/5 晚:程式凍結。

## 9. 目前狀態(2026-11-02 晚)

組員到目前為止的分支都已檢核通過並合併:

| 分支 | 內容 | 合併進 | 備註 |
|---|---|---|---|
| `t5-windows-tools`、`t6-export-out` | T5 停用 PowerShell;T6 `export-demo --out`、孤兒列 | `main-finals-fixes`(快轉到 `ed12d84`,檢核紀錄 `d4bee0d`) | T6 用 W0 資料庫複本匯出時,作廢那次 16 筆孤兒列都沒匯出。V39 斷網重播由組長做 |
| `v2-flow-fixes`(到 `8b2d16e`) | P2 檢索規則、舊設計殘留清單 | `pleading-exchange` | |
| `w4-defendant-view` | W4 被告角色檔、逐點表態檢查 | `pleading-exchange` | 計畫表 W3、W4 兩列衝突,保留兩邊。`defendant_view` 改接 `current_complaint` 由組長在接 W4 時做 |
| `t8-statute-claims` | T8 `statute-claims` | `pleading-exchange` | SKILL 與法官範本等 T7 |

合併後 `pleading-exchange` 離線全套 560 passed、2 skipped。之後新的工作從合併後的最新 `pleading-exchange` 開分支。
