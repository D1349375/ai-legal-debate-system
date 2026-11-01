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

- 開始時間:2026-11-02 02:03（Asia/Taipei）
- 結束時間:2026-11-02 02:23（Asia/Taipei）
- 檢核後修正開始時間:2026-11-02 02:30（Asia/Taipei）
- 檢核後修正結束時間:2026-11-02 02:38（Asia/Taipei）
- 基準 commit:`e9e045b`
- 基準測試(指令與數字):`python -X utf8 -m pytest -q -m "not network" -p no:cacheprovider --basetemp t2tmp --tb=short`（以可存取工作樹的執行權限）→ `288 passed, 1 skipped, 13 deselected`（173.28 秒）。

### 迭代過程

| # | 做了什麼 | 看到什麼 | 決定 |
|---|---|---|---|
| 1 | 在工作樹內指定 `.t2-pytest-tmp` 執行離線全套基準。 | Windows 拒絕讀取 pytest 建立的暫存資料夾，測試出現多項 `PermissionError`；中止此輪，未取得有效總結。 | 依 T1 的方式，使用可存取工作樹的執行權限並指定 `--basetemp t2tmp --tb=short` 重跑。 |
| 2 | 以可存取工作樹的權限重跑離線全套。 | `288 passed, 1 skipped, 13 deselected`。 | 以此為 T2 基準，先量測舊資料再補測試。 |
| 3 | 將 `demo/recorded_cases.json` 匯入工作樹內的 `t2-measure.db`，逐案比較 `finalize_case` 與落地錨點。 | 匯入 5 案、5 份評估；3 案完全一致，`test-2026-08-09-e2e-001` 的兩方論證摘錄缺失、原告讓步條件只差括號補充文字，`test-2026-10-27-gcis-001` 的程序事項 ID 由 `plaintiff:dissolved` 變為空集合。 | 將真正不同的落地欄位另列 `stored_differs`；括號差異維持現有 `minor_differences`；UI 清楚說明舊紀錄與目前重算不一致，不推斷有竄改。 |
| 4 | 先補 verdict 落地與錨點比對 6 個回歸測試。 | 修正前 `5 failed, 1 passed`：缺欄位造成 `KeyError`、被改過的值未警告、摘錄與程序 ID 差異未檢出。 | 實作前確認測試確實抓得到 T2 問題。 |
| 5 | `main.py verdict` 改用 `finalize_case`；API 比對完整錨點，UI 顯示落地欄位差異。 | 新測試加既有 3 個錨點測試共 `9 passed`；新案 CLI 不帶欄位也能落地。 | 更新 SKILL 與假 Claude，檢查即時執行。 |
| 6 | 第一次套用 SKILL 與假 Claude 的補丁格式不符，工具拒絕整份補丁；修正格式再套用。 | 第一次未更動檔案；第二次成功。假 Claude 改由不帶錨點的 verdict JSON 呼叫 CLI，且預期資料庫位址必須明確設定。 | 跑完整即時執行回歸，確認護欄不影響模擬流程。 |
| 7 | 跑 `tests/test_live_run.py`，再在 8397 埠以 `t2-measure.db` 開啟 UI，查看 1 新案及 2 差異舊案。 | `41 passed`；新案顯示一致，舊案分別顯示兩方論證摘錄及程序事項 ID 的差異，畫面無錯誤或空白。 | 保留既有差異分類 `differences`，把新增的落地欄位差異獨立放 `stored_differs`。 |
| 8 | 將受保護資料庫先複製成 `t2-w0-copy.db`，只讀該副本作補充核對。 | W0 的兩案 `live-2026-11-02-gcis-w0`、`live-2026-11-02-gcis-w0b` 均有原告與被告的論證摘錄差異；原檔僅用於複製，未直接開啟或寫入。 | 在量測表下註明這是補充量測，不與示範 fixture 的 5 案混算。 |
| 9 | 檢查分類語意，將新檢出的論證摘錄與程序事項 ID 從既有 `differences` 移到獨立的 `stored_differs`；新增「同 ID 僅文字變動仍一致」測試。 | 先前版本兩欄重複列出差異；調整後 API 分類互不重複，重啟本次 8397 埠服務後，瀏覽器顯示單一、清楚的差異提示。修改發生在一輪全套測試期間，該輪得 `295 passed, 1 skipped, 13 deselected`，但不視為最終驗證。 | 固定程式碼後再跑一次離線全套，最後才填測試結果。 |
| 10 | 最終程式碼再跑離線全套、檢查 JavaScript 語法與 diff，並清理測試暫存資料。 | `295 passed, 1 skipped, 13 deselected`（165.65 秒）；`node --check ui/app.js` 與 `git diff --check` 通過。已清除 3 個 pytest 暫存資料夾、2 個暫存資料庫及測試 verdict JSON；受保護資料庫的檔案時間與開工前相同。 | 留待 Claude 檢核與 C1 真實執行。 |
| 11（檢核意見 1） | 先新增「落地有程序事項、案件無商工查核」測試，修正前 `1 failed, 1 passed`；再讓 `_anchor_check` 在該案件沒有任何查核列時略過程序 ID，比對結果另帶 `notes`，UI 以中性藍色顯示未比對說明。既有「有查核、ID 不同」測試補上實際查核列。 | 修正後 3 個針對性測試 `3 passed`；重新匯入示範資料後，解散案 `consistent=true`、`stored_differs=[]`，瀏覽器顯示一致與「沒有商工查核紀錄，無法重算程序事項，沒有比對」兩則訊息，沒有紅色警示。 | 無查核時不拿缺資料的重算結果判定程序 ID 差異；有查核時仍比較。綠色提示明確說「已比對欄位」，避免暗示程序 ID 也已核對。 |
| 12（檢核意見 2） | 先補論證摘錄與程序事項 ID 的「落地欄位未存／有欄位但內容不同」測試，修正前 `4 failed`；再按欄位是否存在分類 `stored_differs`，不把缺漏與內容差異合併顯示。 | 修正後兩項意見合計 6 個針對性測試 `6 passed`；兩欄都能輸出「(落地紀錄未存)」或「(內容與重算不同)」。重新匯入示範資料後，瀏覽器確認 e2e 案兩方均顯示「論證摘錄(落地紀錄未存)」。 | 缺欄位與欄位存在但值不同保留相同警示等級，只把具體原因寫清楚。 |
| 13（檢核後驗證） | 在最終程式碼上重跑離線全套、檢查 JavaScript 語法與 diff；只停止本輪 8397 埠的暫存服務。 | `298 passed, 1 skipped, 13 deselected`（171.52 秒），較 T2 原版多 3 項測試；`node --check ui/app.js`、`git diff --check` 通過。 | 更新結果與總清單，清理本輪暫存資料；真實 Claude 實跑仍由 C1 驗證。 |

### 舊示範資料量測

以下為檢核意見修正後，重新將 `demo/recorded_cases.json` 匯入本次暫存資料庫的結果；5 案均沒有商工查核紀錄，因此程序 ID 均未比對。表內「無差異」只指已比對欄位。

| 案件 ID | 不同的欄位 | 原因判斷 | 畫面顯示 |
|---|---|---|---|
| `test-2026-08-08-001` | 已比對欄位無差異；程序 ID 未比對。 | 落地與目前重算的已比對欄位相同；資料庫沒有該案商工查核紀錄。 | 一致提示，另以中性訊息說明程序事項沒有比對。 |
| `test-2026-08-08-002` | 已比對欄位無差異；程序 ID 未比對。 | 落地與目前重算的已比對欄位相同；資料庫沒有該案商工查核紀錄。 | 一致提示，另以中性訊息說明程序事項沒有比對。 |
| `test-2026-08-08-003` | 已比對欄位無差異；程序 ID 未比對。 | 落地與目前重算的已比對欄位相同；資料庫沒有該案商工查核紀錄。 | 一致提示，另以中性訊息說明程序事項沒有比對。 |
| `test-2026-08-09-e2e-001` | 原告、被告 `response_excerpt` 未存；原告 `falsifier` 只差括號補充語；程序 ID 未比對。 | 落地錨點沒有兩方 `response_excerpt`，重算為完整 Stage 3 論證；原告讓步條件落地文字省略一段括號說明，依既有規則屬細微差異；資料庫沒有該案商工查核紀錄。 | 「落地時的機械彙整與重算不同」；「落地欄位差異：原告論證摘錄(落地紀錄未存)、被告論證摘錄(落地紀錄未存)」；另提示括號差異及程序事項未比對。 |
| `test-2026-10-27-gcis-001` | 已比對欄位無差異；程序 ID 未比對。 | 落地有 `plaintiff:dissolved`，但示範 fixture 沒有匯入該案商工查核紀錄；重算環境缺資料，因此不拿空集合判定差異。 | 已比對欄位一致，沒有紅色警示；中性訊息顯示「這個資料庫沒有該案件的商工查核紀錄，無法重算程序事項，沒有比對。」 |

補充量測（不計入上表 5 案，為檢核前從副本量得的結果）：先複製 `database/legal_debate.db` 到暫存的 `t2-w0-copy.db` 再讀副本。W0 兩案 `live-2026-11-02-gcis-w0`、`live-2026-11-02-gcis-w0b` 都檢出原告與被告 `response_excerpt` 欄位存在但內容不同；依檢核後的分類文字應為「論證摘錄(內容與重算不同)」，本輪沒有重讀該副本。UI 的共同說明文字為「落地時的機械彙整與重算不同。這是落地紀錄與目前資料重算的差異；單憑比對不能判定原因。」，再列出具體欄位；不使用「竄改」。

### 結果

- 最後測試(指令與數字):`python -X utf8 -m pytest -q -m "not network" -p no:cacheprovider --basetemp t2-review-tmp --tb=short`（以可存取工作樹的執行權限）→ `298 passed, 1 skipped, 13 deselected`（171.52 秒），較 T2 基準新增 10 passed，較檢核前新增 3 passed；檢核前 `tests/test_live_run.py` 單跑 `41 passed`；`node --check ui/app.js` 與 `git diff --check` 通過。瀏覽器以暫存資料庫、獨立 8397 埠看過解散案與 e2e 案的修正後訊息；檢核前亦看過 1 新案。驗證服務已停止。
- 新增測試與各自測什麼:`tests/test_cli.py` 4 項：不帶錨點可落地且值相同、帶改過的錨點會警告並存重算值、帶相同錨點不警告、Stage 3 不齊拒絕落地；`tests/test_server.py` 6 項：論證摘錄內容不同、程序事項 ID 內容不同、同 ID 僅程序文字改變仍一致，以及檢核後新增的「無查核則跳過程序 ID」、「論證摘錄未存」、「程序事項 ID 未存」。既有 3 項錨點測試仍通過。
- 改了的檔:`main.py`（verdict 自行重算與警告）；`server/services.py`（比對全部指定欄位、無查核時略過程序 ID，並區分缺漏與內容差異）；`ui/app.js`（顯示差異欄位、中性未比對說明與不歸因的說明）；`ui/app.css`（雙提示間距）；`.claude/skills/legal-debate/SKILL.md`（Step 6/8 不再轉抄錨點）；`tests/fake_claude.py`（不帶錨點走 CLI，強制核對測試資料庫位址）；`tests/test_cli.py`（verdict 回歸）；`tests/test_server.py`（錨點比對回歸）；`tests/test_live_run.py`（假 Claude 執行時設定預期資料庫位址）；本文件（迭代與量測）；`docs/zh/main-finals-fix-list.md`（T2 列）。
- 與本文件不同的做法與原因:`server/live_run.py` 給主 agent 的 prompt 本來沒有要求輸出 `mechanical_anchor_json`，因此未修改該 prompt；續跑匯出的 `landed.json` 仍如實包含資料庫已存的錨點。假 Claude 原本直接呼叫 `record_verdict`，改以不帶該欄位的 JSON 呼叫 `main.py verdict`，才能模擬新流程；額外強制 `FAKE_CLAUDE_EXPECT_DB_URL` 避免測試寫錯資料庫。
- 沒解決或沒驗證的事:未執行真實 Claude 的 C1 實跑；W0 兩案只從受保護資料庫的副本進行程式比對，未另開 UI 查看該副本。程序事項文字只比對 ID，依任務規格不檢查文字。

## 檢核結果(Claude 填寫)

- 日期:2026-11-02
- 結果:**未通過,要改 2 處。** 其餘都符合任務文件:`main.py verdict` 改成自己算、SKILL 改得正確、`stored_differs` 獨立分類、不用「竄改」字眼、量測表完整、W0 資料庫只讀副本。
- 要改的地方:
  1. **`test-2026-10-27-gcis-001` 的紅色警示是假警報,決賽示範會出現。** 這個案件就是商工解散案,是決賽要展示的重點案件。
     - 原因:`server/seed.py` 的 `_TABLES` 沒有商工查核表,斷網重播的資料庫裡沒有這個案件的查核紀錄,所以重算時程序事項是空的。落地紀錄本身沒有問題,是重算的環境缺資料。
     - 改法:資料庫裡**沒有該案件任何商工查核紀錄**時,不比對程序事項 ID,也不算進 `stored_differs`;`anchor_check` 另外帶一個說明(例如 `notes: ["這個資料庫沒有該案件的商工查核紀錄,無法重算程序事項,沒有比對"]`),UI 顯示成中性的說明,不用紅色。有查核紀錄時照現在的方式比對。
     - 測試:有落地程序事項、資料庫沒有查核紀錄 → `consistent` 不受影響且帶說明;有查核紀錄但 ID 不同 → 仍列入 `stored_differs`(既有測試應已涵蓋,確認仍過)。
     - 改完用 `demo/recorded_cases.json` 匯入暫存資料庫再看一次 gcis-001,把畫面結果補進量測表。
  2. **把「落地時缺這個欄位」和「內容不同」分開寫。** 查過 git 歷史,`response_excerpt` 從第一個 commit 就有,所以 e2e-001 落地時沒有這個欄位,和 W0 被換成「摘錄從略」是同一類問題,列在 `stored_differs` 是對的。但畫面目前都寫成「論證摘錄」,看不出是缺漏還是被改寫。
     - 改法:落地紀錄沒有這個欄位時寫「原告論證摘錄(落地紀錄未存)」,有但內容不同時寫「原告論證摘錄(內容與重算不同)」。程序事項 ID 照同樣原則處理。紅色或黃色維持現狀即可,不用改等級。
     - 測試:缺欄位與內容不同各一項,檢查 `stored_differs` 的文字。
  - 改完重跑離線全套,在迭代過程加列,不要 commit。
- 附記:任務文件寫的 `server/live_run.py` prompt 沒提到這個欄位,所以沒改,這點沒問題。

### 第二次檢核(2026-11-02)

- 結果:**通過。**
- 兩條意見都已處理:
  1. 資料庫沒有該案件的商工查核紀錄時,不比對程序事項 ID,改帶 `notes`,UI 以中性的 `rec` 樣式顯示。有查核紀錄時仍會比對。
  2. `stored_differs` 分別寫「(落地紀錄未存)」與「(內容與重算不同)」,程序事項 ID 也一樣。
- Claude 自己驗證:
  - 離線全套 `298 passed, 1 skipped, 13 deselected`(165.90 秒),和回報一致。
  - 用暫存資料庫從 `demo/recorded_cases.json` 匯入,另開 8132 埠,API 與畫面都看過:
    - `test-2026-10-27-gcis-001`:綠色「已比對欄位與落地時的計算結果一致」,下方是中性說明「這個資料庫沒有該案件的商工查核紀錄…沒有比對」。決賽示範不會再出現紅色假警報。
    - `test-2026-08-09-e2e-001`:紅色,「原告論證摘錄(落地紀錄未存)、被告論證摘錄(落地紀錄未存)」。這是真實的落地缺漏,照實顯示是對的。
    - `test-2026-08-08-001`:綠色一致。
    - console 沒有錯誤。
- 提醒使用者:e2e-001 在示範畫面會是紅色。這個案件原本就決定不在決賽講(見決賽統整),不影響;若評審點進去,照實說明是早期落地時主 agent 沒存摘錄,這正是 T2 要修的問題。
- 仍待 C1:真實 Claude 落地時不再轉抄機械彙整。
