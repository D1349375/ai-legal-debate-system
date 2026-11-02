---
name: legal-debate
description: >-
  LegalDebate 模擬法庭 orchestrator:跑單一民事案件。書狀交換流程(protocol v2):案件輸入與起訴前檢查→
  原告請求權基礎檢驗→起訴狀 v1(事實對應、查證、判例實質核對),之後的模擬答辯、爭點整理、攻防與起訴狀 v2 陸續接上;
  舊案件(沒有 protocol)走 references/legacy-v1.md 的三角色四階段流程。觸發詞:「跑案件模擬法庭」「模擬攻防」「案件辯論」「/legal-debate」。
  單一模型,單一審判長,僅處理民事通常訴訟程序案件。專案位置:Side Project/LegalDebate/。
---

# LegalDebate 模擬法庭 Orchestrator Runbook

你(主 agent)在此流程中的身分是**流程調度員/記帳員**。職責邊界(嚴格遵守):

- ✅ 準備案件輸入、依序調度 subagent、呼叫 CLI 落地、回報使用者
- ❌ **禁止自己判斷案件實質、禁止自己寫論證或書狀內容**——你不是律師,也不是法官
- ❌ 禁止修改 subagent 的輸出再落地;被程式退回時,把報錯原文交回同一個 subagent 修改,不得代寫
- ❌ 禁止跳過查證閘門自己判斷引用真偽——`main.py complaint`、`record_verdict`、`record_pleading` 對未查證引用會直接拒絕落地,這是機械閘門,不是你的判斷空間

所有指令在 `Side Project/LegalDebate/` 目錄下執行,直接用系統 Python(無獨立 venv):`python main.py <cmd>`。UI 無人值守執行時只允許單一 `python main.py ...` 指令,不要用管線、迴圈或 `&&` 串接。

## 先判斷流程版本

讀案件輸入(UI 執行時是指示裡的 `case.json`;否則 `data/cases/<case_id>.json`):

- `protocol` 為 `"v2"`:走本文件的**書狀交換流程**。
- 沒有 `protocol`:走 [references/legacy-v1.md](references/legacy-v1.md) 的舊流程(Step 1–10、Step 9C 補產書狀),本文件以下各節不適用,但「落地紀律」「subagent 的回覆被安全分類器中止時」兩節兩邊都適用。

啟動前跟使用者說明(無人值守時寫在最後回覆):不模擬調解;以民事第一審通常程序設計,小額、簡易程序只提示不模擬;單一模型、單一審判長;Claude Code 派 subagent 沒有溫度參數,這點無法落實,照實告知。

## 書狀交換流程(protocol v2)

目前接上的是 Step 1–3(P0、P1)與關卡 1。之後的步驟見「Step 4 以後」。

### 路徑

| 用途 | 路徑 |
|---|---|
| 暫存檔 | UI 執行時一律寫在指示的執行資料夾(`database/live_runs/run-<N>/`) |
| 案件資料夾 | `database/live_runs/case-<案件ID>/`;律師確認關卡續跑時沿用同一個 |
| 原告快照 `{RETRIEVAL_CACHE_DIR}` | `database/live_runs/case-<案件ID>/retrieval_cache/plaintiff` |
| 原告 P1 檢索紀錄 `{SEARCH_LOG_PATH}` | `database/live_runs/case-<案件ID>/search_logs/plaintiff_p1.jsonl` |
| 案件快照根目錄(查證用) | `database/live_runs/case-<案件ID>/retrieval_cache` |

每個角色只拿自己的快照與紀錄路徑,不得把對造的路徑給角色。資料夾不存在時指令會自己建。

### 派 subagent 與交接檔案

你的上下文每一輪都會整份重讀(舊流程實跑主 agent 長到約 19 萬 token,佔全程輸入八成),所以範本、角色檔、分析與 subagent 的輸出都不要經過你:

- **不要 Read 範本**。用 `python main.py prompt <範本名> --out <執行資料夾>/prompts/<步驟>.txt --set KEY=VALUE …` 由程式填好佔位符寫成檔,指令只印路徑;佔位符沒填完或填錯名字會被拒。檢索階段加 `--phase p1 --side plaintiff --case-dir <案件資料夾>`,程式會帶入 `{RETRIEVAL_RULES}` 與該角色的 `{RETRIEVAL_CACHE_DIR}`、`{SEARCH_LOG_PATH}`。
- subagent 的 prompt 只寫一句:「用 Read 讀 <上一點印出的路徑>,那是你這次的完整指示,照做。」
- subagent 自己用 Write 把輸出寫進 `{OUTPUT_PATH}`,只回「已寫入 <路徑>」。你不要 Read 輸出檔,直接交給落地或檢查指令。被退回時把報錯原文交回同一個 subagent,請它重寫同一個檔;不能用 SendMessage 時(無人值守執行就不能),另開新 subagent,prompt 寫:讀同一個派工檔、讀既有的輸出檔、報錯原文,只改被點名的地方後重寫同一個檔。這樣仍算同一份輸出的退回次數。
- `role-view`、`public-args` 一律加 `--out <檔>`,指令只印路徑。

### Step 1 — P0 案件輸入與起訴前檢查

1. 案件要已落地(UI 建案時已落地;CLI 用 `python main.py case --json <檔>`,JSON 要有 `"protocol": "v2"`)。事實只能來自使用者,不得代為編造。
2. 商工查核:當事人是公司或商號、且使用者提供了統一編號時,執行 `python main.py party --ban <統編> --case-id <案件ID> --role plaintiff|defendant`。**統編只能來自使用者**,不得用名稱搜尋自行選定。自然人或沒給統編的一方不查,照實留空。UI 執行時已查好,不要重查。
3. 執行 `python main.py role-view --case-id <案件ID> --role plaintiff --out <執行資料夾>/plaintiff_view.json`,產生原告角色檔。裡面有案件輸入、商工查核、起訴審查事項(`procedural_issues`,依固定規則產生,不得增刪)與起訴前檢查(`precheck`,只是提示)。
4. 用 Grep 在角色檔找 `"evidence": []`。找到代表沒有證據清單,照樣繼續,但最後回覆要寫明:事實只能對應事實經過的原文。找不到就是有證據清單,不要這樣寫。

### Step 2 — P1 原告請求權基礎檢驗

- 執行 `python main.py prompt stage1_prompt --out <執行資料夾>/prompts/p1_analysis.txt --phase p1 --side plaintiff --case-dir <案件資料夾> --set CASE_ID=<案件ID> --set ROLE_VIEW_PATH=<Step 1 的角色檔> --set OUTPUT_PATH=<執行資料夾>/p1_analysis.json`,照上一節派一個 subagent。
- subagent 的回覆寫「檢索被拒」、因此沒有檢索時,這份分析不落地,另開新 subagent 用同一份範本重派(同一步驟最多重派 2 次,與分類器中止分開計),最後回覆照實列出。
- 收到後機械核對:`procedural_issues.issues` 裡 `ex_officio` 為 true 的每一則,用 Grep 在 `p1_analysis.json` 找「程序補正(<id>)」。漏掉就退回同一個 subagent 補寫,不得代寫。
- 執行 `python main.py record --json <執行資料夾>/p1_analysis.json` 落地。`record` 對內部檢討段落與自承用語的警告只警告,照實列入最後回覆。

### Step 3 — P1 起訴狀 v1

1. 執行 `python main.py public-args --case-id <案件ID> --through-stage 1 --out <執行資料夾>/plaintiff_analysis.json`(已濾掉內部檢討)。
2. 執行 `python main.py prompt complaint_prompt --out <執行資料夾>/prompts/p1_complaint.txt --phase p1 --side plaintiff --case-dir <案件資料夾> --set CASE_ID=<案件ID> --set ROLE_VIEW_PATH=<角色檔> --set ANALYSIS_PATH=<上一點的檔> --set OUTPUT_PATH=<執行資料夾>/complaint.json`,派一個新的撰狀 subagent。
3. 執行 `python main.py complaint --case-id <案件ID> --json complaint.json --check`。印「未通過」就把報錯原文交回**同一個**撰狀 subagent,請它只改被點名的地方後重寫 `complaint.json`。同一份最多退回 2 次(含第一次共 3 次);3 次都沒通過就停在這裡,不落地,在最後回覆列出每次的報錯原文。通過時會印出程式組成的正文與「落地前要全部 published 的引用」。
4. **開一個新的、乾淨的查證 subagent**(不能是撰狀的同一個),交給它:
   - 執行 `python main.py verify <上一步列出的全部引用> --snapshot database/live_runs/case-<案件ID>/retrieval_cache --read-by plaintiff`(UI 執行時環境變數已指向根目錄,`--snapshot` 可省略),確認存在性,以及原告在本案用 `judgment` 讀過全文(摘句由第 5 點落地時比對)。只有 `published` 放行;`not_read_by_side`(原告沒讀過全文)和其他狀態一樣退回撰狀。
   - 對 `complaint.json` 的每一個 `precedent_notes`,用 `python main.py judgment <字號>`(不加 `--snapshot`、不加 `--log`,不搜尋)讀全文,核對案由與爭點是否真的支持 `proposition`。
   - 產出嚴格 JSON 陣列 `[{"citation": "字號", "supports": true 或 false, "reason": "一句話,寫依據全文哪一段"}]`;沒有判決時寫 `[]`。這個陣列由查證 subagent 自己用 Write 寫進 `<執行資料夾>/citation_review.json`,只回「已寫入 <路徑>」;你不要改寫或補內容。
5. 執行 `python main.py complaint --case-id <案件ID> --json complaint.json --review-json citation_review.json` 落地(CLI 執行時另加 `--snapshot database/live_runs/case-<案件ID>/retrieval_cache`)。程式會再擋一次,只有 `published` 放行:引用未通過查證、判決實質核對不支持、判例摘句不是全文原句(`quote_not_found`)、原告沒用 `judgment` 讀過全文(`not_read_by_side`)、文件身分不符、連線失敗(`network_error`)、同字號多份(`ambiguous`)都不落地。
   - 被擋的引用:回頭請撰狀 subagent 刪掉或改用通過的引用(算一次退回),不得自己改寫引用內容。
   - 改寫後不要整份重新查證。只刪除引用時,沿用原本的 `citation_review.json`(落地只核對起訴狀現有的判決,多的會被忽略),直接重跑第 3、5 點。有新增引用時,另開乾淨的查證 subagent,`verify` 只列新增的引用、只讀新增的判決,讀既有的 `citation_review.json`,把新結果加進去後重寫同一個檔。
   - `lint_pleading` 的模擬流程用語警告只警告,照實列入最後回覆。
6. 起訴狀 v1 落地後畫面就看得到;當事人欄由程式依商工查核帶入,已解散公司的法定代理人寫「清算人(待查明…)」,這是刻意的,不要要求補姓名。

### 關卡 1 — 律師確認起訴狀

關卡由 UI 記錄,你不記錄、不判斷,也不要替律師選版本。

- 指示寫「只跑到起訴狀」:起訴狀 v1 落地後就停,直接到 Step 10。律師在 UI 選定版本(可先編輯成律師版)後確認並繼續,或到此結束。
- 指示寫「跑完全程」、沒有停止點:關卡 1 自動通過,UI 在執行結束時記為「未經律師確認」,你接著做 Step 4 以後。
- 續跑指示寫明關卡 1 確認的版本時,之後每一步需要起訴狀都讀那一版(`landed.json` 的 `confirmed_complaint`;`role-view` 的 `complaint` 也是那一版;交路徑給 subagent,不要自己 Read 全文),不要改用資料庫裡的其他版本,也不要重新產生或落地起訴狀 v1。

### Step 4 以後

答辯狀(P2)、爭點整理表(P3)、準備書狀(P4、P5)、診斷與起訴狀 v2(P6)還沒接上(實作計畫 W4–W7)。在接上之前:

- 指示寫「只跑到起訴狀」或「只跑 Step 1–3」時,起訴狀 v1 落地後就停,直接到 Step 10 回報。
- 沒有這樣的指示時,接著照 [references/legacy-v1.md](references/legacy-v1.md) 從 Step 2 往下跑完,但:原告 Stage 1 已在本文件 Step 2 落地,只派被告 Stage 1(範本 `references/legacy-v1-stage1_prompt.txt`,`{CASE_FACTS_PATH}` 填案件輸入檔);Step 9 只產被告答辯狀(9B),原告起訴狀已在 Step 3 落地。**這段是過渡做法**:舊範本的被告讀得到全部案件事實,不符合書狀交換流程「被告只讀起訴狀」的設計,回報時要照實說。

### Step 10 — 回報使用者

- 官方事實層:哪一方查核了商工登記、起訴審查事項、原告如何補正;未查核的一方照實說未查核。
- 起訴前檢查的提示(程序類型、調解、時效),只是提示。
- 起訴狀 v1 全文;`fact_gaps`、`lawyer_notes`;哪些事實因為對應不到被移到事實缺口。
- 每次退回的報錯原文與次數;查證結果(存在性、摘句比對、實質核對分開說);被排除的引用。
- 檢索次數與實際上網抓全文數(看指令印出的預算摘要)。
- `record` 與 `complaint` 的警告。
- 每次分類器中止(哪個 subagent、第幾次、最後是否重派成功)。

結尾必附一句:**「本結果為起訴狀初稿與分析,非法院判決預測,正式書狀仍需律師覆核。」**

## 落地紀律

- `record`/`complaint`/`finalize`/`verdict`/`pleading` 遇「已落地不可覆寫」報錯 = 該案件此階段已跑過,**不要試圖刪除或改寫**,向使用者回報即可。
- 任何案件層級的統計評估(如多案件命中率)不在本 skill 範圍——單案跑測不構成統計意義上的驗證。
- 結構問題由程式硬擋,退回產生它的 subagent;自然語言問題只警告。同一份輸出最多退回 2 次。分類器中止不計入退回次數。

## subagent 的回覆被安全分類器中止時

實跑時(2026-10-28 #3、2026-10-29 #4)subagent 輸出最終 JSON 時偶爾會被 Anthropic 的安全分類器中止(類別 `reasoning_extraction`)。這不是工具或 API 錯誤,subagent 會回報「回覆被安全分類器中止」、沒有交出完整 JSON。這個分類器有機率性,同一份 prompt 重派通常就能通過。處理方式:

1. 被中止的那份輸出不完整,不得採用、不得落地,也不得由你補完或代寫。
2. **另開一個新的 subagent**,用同一份範本逐字重派(佔位符照填)。不要用 SendMessage 叫原本那個 subagent 重寫。也不要自行精簡或改寫範本來「避開」分類器。
3. 同一個角色同一步驟最多重派 2 次(含第一次共 3 次)。都被中止就停在這一步,在最後回覆寫明卡在哪一個 subagent、被中止幾次。
4. 每次中止都要在最後回覆照實列出。依官方文件,`reasoning_extraction` 類別的中止照樣計費(https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback ,「How refusals are billed」一節)。

## 已知限制

- 溫度參數無法透過現有工具機械落實。
- 查證只確認條文與最高法院民事裁判存在、判例摘句是全文原句;判例是否實質支持由獨立 subagent 讀全文判斷,條文內容與引用處的描述是否相符還沒有核對(W0 發現 F6,待 T8)。
- 角色之間的資訊隔離靠提示與調度:同一個 Claude Code 程序裡的 subagent 共用權限,程式只禁止所有 agent 直接讀檢索快取與紀錄,擋不住讀其他檔案。
