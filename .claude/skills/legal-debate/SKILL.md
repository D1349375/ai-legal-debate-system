---
name: legal-debate
description: >-
  LegalDebate 模擬法庭 orchestrator:跑單一民事案件。書狀交換流程(protocol v2):案件輸入與起訴前檢查→
  原告請求權基礎檢驗→起訴狀 v1(事實對應、查證、判例實質核對)→律師確認→模擬答辯狀→爭點整理表→準備書狀→言詞辯論意旨狀→診斷與起訴狀 v2;
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

Step 1–13 依序是:P0 案件輸入、P1 原告分析與起訴狀 v1、關卡 1、P2 被告防禦分析與模擬答辯狀、P3 爭點整理表、P4 準備書狀、P5 言詞辯論意旨狀、P6 診斷與起訴狀 v2、回報。指示有停止點(只跑到起訴狀、模擬答辯狀或爭點整理表)時,跑到該步落地就停,直接到 Step 13。

### 路徑

| 用途 | 路徑 |
|---|---|
| 暫存檔 | UI 執行時一律寫在指示的執行資料夾(`database/live_runs/run-<N>/`) |
| 案件資料夾 | `database/live_runs/case-<案件ID>/`;律師確認關卡續跑時沿用同一個 |
| 原告快照 `{RETRIEVAL_CACHE_DIR}` | `database/live_runs/case-<案件ID>/retrieval_cache/plaintiff` |
| 原告 P1 檢索紀錄 `{SEARCH_LOG_PATH}` | `database/live_runs/case-<案件ID>/search_logs/plaintiff_p1.jsonl` |
| 被告快照 `{RETRIEVAL_CACHE_DIR}` | `database/live_runs/case-<案件ID>/retrieval_cache/defendant` |
| 被告 P2 檢索紀錄 `{SEARCH_LOG_PATH}` | `database/live_runs/case-<案件ID>/search_logs/defendant_p2.jsonl`(防禦分析與答辯狀撰狀共用) |
| 案件快照根目錄(查證用) | `database/live_runs/case-<案件ID>/retrieval_cache` |

每個角色只拿自己的快照與紀錄路徑,不得把對造的路徑給角色。資料夾不存在時指令會自己建。

### 派 subagent 與交接檔案

你的上下文每一輪都會整份重讀(舊流程實跑主 agent 長到約 19 萬 token,佔全程輸入八成),所以範本、角色檔、分析與 subagent 的輸出都不要經過你:

- **不要 Read 範本**。用 `python main.py prompt <範本名> --out <執行資料夾>/prompts/<步驟>.txt --set KEY=VALUE …` 由程式填好佔位符寫成檔,指令只印路徑;佔位符沒填完或填錯名字會被拒。檢索階段加 `--phase p1 --side plaintiff --case-dir <案件資料夾>`,程式會帶入 `{RETRIEVAL_RULES}` 與該角色的 `{RETRIEVAL_CACHE_DIR}`、`{SEARCH_LOG_PATH}`。
- subagent 的 prompt 只寫一句:「用 Read 讀 <上一點印出的路徑>,那是你這次的完整指示,照做。」
- subagent 自己用 Write 把輸出寫進 `{OUTPUT_PATH}`,只回「已寫入 <路徑>」。你不要 Read 輸出檔,直接交給落地或檢查指令。被退回時把報錯原文交回同一個 subagent,請它重寫同一個檔;不能用 SendMessage 時(無人值守執行就不能),另開新 subagent,prompt 寫:讀同一個派工檔、讀既有的輸出檔、報錯原文,只改被點名的地方後重寫同一個檔。這樣仍算同一份輸出的退回次數。
- `role-view`、`public-args` 一律加 `--out <檔>`,指令只印路徑。
- **派工的 description 要寫角色**:被告的 subagent(防禦分析、答辯狀撰狀)description 一定要含「被告」,例如「被告防禦分析」「被告答辯狀撰狀」;事後稽核(`scripts/audit_run.py --agent 被告`)靠它找出被告的 subagent,檢查它們沒有讀到案件輸入檔。其他 subagent(含查證)的 description 不要含「被告」。
- UI 執行時,Read、Grep、Glob 只讀得到本次執行資料夾、本案件資料夾與本 skill 資料夾(舊流程文件 `references/legacy-v1.md` 也讀不到);被拒時不要換路徑重試,照實列入最後回覆。

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
4. **開一個新的、乾淨的查證 subagent**(不能是撰狀的同一個),交給它(派工時把這句寫進指示:用 Bash 工具執行,一個 `verify` 指令列出全部引用,不要用 PowerShell,也不要用迴圈逐筆跑):
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

- 指示寫「只跑到起訴狀」:起訴狀 v1 落地後就停,直接到 Step 13。律師在 UI 選定版本(可先編輯成律師版)後確認並繼續,或到此結束。
- 指示寫「跑完全程」、沒有停止點:關卡 1 自動通過,UI 在執行結束時記為「未經律師確認」,你接著做 Step 4。
- 續跑指示寫明關卡 1 確認的版本時,之後每一步需要起訴狀都讀那一版(`landed.json` 的 `confirmed_complaint`;`role-view` 的 `complaint` 也是那一版;交路徑給 subagent,不要自己 Read 全文),不要改用資料庫裡的其他版本,也不要重新產生或落地起訴狀 v1。

### Step 4 — P2 被告防禦分析

被告只讀被告角色檔:律師確認版起訴狀(還沒確認時是最新系統原稿)、起訴狀用到的證據、被告起訴前說過的話、商工查核與起訴審查事項。不得把案件輸入檔、原告角色檔、原告分析或它們的路徑交給被告的 subagent。

1. 執行 `python main.py role-view --case-id <案件ID> --role defendant --out <執行資料夾>/defendant_view.json`。
2. 執行 `python main.py prompt defense_stage1_prompt --out <執行資料夾>/prompts/p2_defense.txt --phase p2 --side defendant --case-dir <案件資料夾> --set CASE_ID=<案件ID> --set ROLE_VIEW_PATH=<執行資料夾>/defendant_view.json --set OUTPUT_PATH=<執行資料夾>/p2_defense.json`,派一個 subagent(description「被告防禦分析」)。
3. subagent 的回覆寫「檢索被拒」、因此沒有檢索時,這份分析不落地,另開新 subagent 用同一份範本重派(同一步驟最多重派 2 次,與分類器中止分開計),最後回覆照實列出。
4. 執行 `python main.py record --json <執行資料夾>/p2_defense.json` 落地。`record` 對內部檢討段落與自承用語的警告只警告,照實列入最後回覆。

### Step 5 — P2 模擬答辯狀

1. 執行 `python main.py public-args --case-id <案件ID> --stage 1 --side defendant --out <執行資料夾>/defendant_analysis.json`(只有被告的分析,已濾掉內部檢討)。
2. 執行 `python main.py prompt answer_prompt --out <執行資料夾>/prompts/p2_answer.txt --phase p2 --side defendant --case-dir <案件資料夾> --set CASE_ID=<案件ID> --set ROLE_VIEW_PATH=<執行資料夾>/defendant_view.json --set ANALYSIS_PATH=<執行資料夾>/defendant_analysis.json --set OUTPUT_PATH=<執行資料夾>/answer.json`,派一個新的撰狀 subagent(description「被告答辯狀撰狀」)。
3. 執行 `python main.py answer --case-id <案件ID> --json <執行資料夾>/answer.json --check`。印「未通過」就把報錯原文交回**同一個**撰狀 subagent,請它只改被點名的地方後重寫 `answer.json`。同一份最多退回 2 次(含第一次共 3 次);3 次都沒通過就停在這裡,不落地,在最後回覆列出每次的報錯原文。通過時會印出程式組成的正文與「落地前要全部 published 的引用」。
4. **開一個新的、乾淨的查證 subagent**(不能是撰狀的同一個;description 例如「答辯狀引用查證」),交給它(派工時把這句寫進指示:用 Bash 工具執行,一個 `verify` 指令列出全部引用,不要用 PowerShell,也不要用迴圈逐筆跑):
   - 執行 `python main.py verify <上一步列出的全部引用> --snapshot database/live_runs/case-<案件ID>/retrieval_cache --read-by defendant`(UI 執行時 `--snapshot` 可省略),確認存在性,以及被告在本案用 `judgment` 讀過全文。只有 `published` 放行;`not_read_by_side` 和其他狀態一樣退回撰狀。抗辯新加的法條也在清單裡,沒有查過的法條落地時會被拒。
   - 對 `answer.json` 的每一個 `precedent_notes`,用 `python main.py judgment <字號>`(不加 `--snapshot`、不加 `--log`,不搜尋)讀全文,核對案由與爭點是否真的支持 `proposition`。
   - 產出嚴格 JSON 陣列 `[{"citation": "字號", "supports": true 或 false, "reason": "一句話,寫依據全文哪一段"}]`;沒有判決時寫 `[]`。由查證 subagent 自己用 Write 寫進 `<執行資料夾>/answer_citation_review.json`,只回「已寫入 <路徑>」;你不要改寫或補內容。
5. 執行 `python main.py answer --case-id <案件ID> --json <執行資料夾>/answer.json --review-json <執行資料夾>/answer_citation_review.json` 落地(CLI 執行時另加 `--snapshot database/live_runs/case-<案件ID>/retrieval_cache`)。被擋的引用照 Step 3 第 5 點處理:請撰狀 subagent 刪掉或改用通過的引用(算一次退回),只刪除時沿用原本的查證結果,有新增引用時另開乾淨的查證 subagent 只查新增的。
6. 指示寫「只跑到模擬答辯狀」時,落地後就停,直接到 Step 13。

### Step 6 — P3 爭點整理表

法官只讀法官角色檔(起訴狀、答辯狀與逐點表態、證據、程序事項),不讀事實經過,也不讀雙方的分析。

1. 執行 `python main.py role-view --case-id <案件ID> --role judge --out <執行資料夾>/judge_view.json`。
2. 執行 `python main.py prompt issue_sheet_prompt --out <執行資料夾>/prompts/p3_issue_sheet.txt --phase p3 --set CASE_ID=<案件ID> --set ROLE_VIEW_PATH=<執行資料夾>/judge_view.json --set OUTPUT_PATH=<執行資料夾>/issue_sheet.json`,派一個 subagent(description「法官爭點整理」)。
3. 執行 `python main.py issue-sheet --case-id <案件ID> --json <執行資料夾>/issue_sheet.json --check`。印「未通過」就把報錯原文交回同一個法官 subagent,請它只改被點名的地方後重寫。同一份最多退回 2 次;3 次都沒通過就停在這裡,不落地,在最後回覆列出每次的報錯原文。
4. 執行 `python main.py issue-sheet --case-id <案件ID> --json <執行資料夾>/issue_sheet.json` 落地。**不要**跑 `check-judge`(那是舊流程的法官訊問用的)。印出的警告與轉述警告照實列入最後回覆,不退回。
5. 指示寫「只跑到爭點整理表」時,落地後就停,直接到 Step 13。

### Step 7 — P4 準備書狀(雙方)

雙方各做一次以下 1–7 點,`<方>` 是 `plaintiff` 或 `defendant`,`<方名>` 是「原告」或「被告」。兩方互不依賴,可以先後做,也可以同時派。

1. 執行 `python main.py role-view --case-id <案件ID> --role judge --out <執行資料夾>/exchange_view.json`(爭點整理表落地後要重產一次,Step 6 那份還沒有爭點整理表;雙方共用這一份)。
2. 執行 `python main.py role-view --case-id <案件ID> --role <方> --out <執行資料夾>/<方>_view.json`,以及 `python main.py public-args --case-id <案件ID> --stage 1 --side <方> --out <執行資料夾>/<方>_stage1.json`。被告的 subagent 只能拿被告的這兩份與 `exchange_view.json`,不得拿原告的。
3. 執行 `python main.py prompt round2_prompt --out <執行資料夾>/prompts/p4_<方>.txt --phase p4 --side <方> --case-dir <案件資料夾> --set CASE_ID=<案件ID> --set SIDE=<方> --set SIDE_LABEL=<方名> --set OWN_VIEW_PATH=<執行資料夾>/<方>_view.json --set EXCHANGE_VIEW_PATH=<執行資料夾>/exchange_view.json --set OWN_ANALYSIS_PATH=<執行資料夾>/<方>_stage1.json --set OUTPUT_PATH=<執行資料夾>/p4_<方>.json`,派一個 subagent(description「<方名>準備書狀」)。
4. subagent 的回覆寫「檢索被拒」、因此沒有檢索時,照 Step 2 重派。
5. **落地前先查證**(論證落地後不能改,引用沒過書狀就永遠落不了地):開一個新的、乾淨的查證 subagent(description「準備書狀引用查證」,不要含「被告」),指示它:用 Read 讀 `<執行資料夾>/p4_<方>.json`,把 `cited_statutes`、`cited_precedents`、`basis` 全部列進**一個** `python main.py verify <全部引用> --snapshot database/live_runs/case-<案件ID>/retrieval_cache --read-by <方>` 指令(用 Bash 工具,不要用 PowerShell,不要用迴圈逐筆跑;UI 執行時 `--snapshot` 可省略);最終回覆只寫一行:全部 `published` 時寫「全部通過」,否則寫「未通過:」加上每個沒通過的引用與狀態。未通過就把這一行交回同一個準備書狀 subagent,請它刪掉或改用通過的引用、或用 `judgment` 讀過全文後重寫(算一次退回);重寫後只查新增的引用。
6. 執行 `python main.py record --json <執行資料夾>/p4_<方>.json`。被拒絕(例如缺少某個【爭點】段落、`basis` 格式不對)時,論證沒有落地,把報錯原文交回同一個 subagent 重寫(算一次退回);有新增引用時回到第 5 點只查新增的。同一份輸出(查證與落地合計)最多退回 2 次;3 次都沒通過就停在這裡,在最後回覆列出每次的報錯原文。`record` 的警告(第255條、推測字樣、自承用語、內部檢討)只警告,照實列入最後回覆。
7. 執行 `python main.py brief --case-id <案件ID> --side <方> --round 2` 落地準備書狀(正文由程式組成,不派 subagent)。

### Step 8 — P5 言詞辯論意旨狀(雙方)

雙方的準備書狀(Step 7)都落地後才開始。雙方各做一次以下 1–6 點,`<對方>` 是另一方。

1. 執行 `python main.py public-args --case-id <案件ID> --stage 2 --side <對方> --out <執行資料夾>/p5_<對方>_stage2.json`。
2. 執行 `python main.py prompt opponent_summary_prompt --out <執行資料夾>/prompts/p5_summary_<對方>.txt --set CASE_ID=<案件ID> --set OPPONENT=<對方> --set OPPONENT_LABEL=<對方名> --set OPPONENT_ARGS_PATH=<執行資料夾>/p5_<對方>_stage2.json --set OUTPUT_PATH=<執行資料夾>/p5_summary_<對方>.json`,派一個小的摘要 subagent(description「對手摘要」,不要含「被告」)。你不要自己寫摘要,也不要 Read 對方的論證。
3. 執行 `python main.py check-summary --case-id <案件ID> --json <執行資料夾>/p5_summary_<對方>.json`。有警告(最強論點不是原句、含條件或讓步字樣、引用不在清單)時,把警告原文交回同一個摘要 subagent 重寫,最多 2 次;仍有警告就照用,並在最後回覆列出。
4. 執行 `python main.py public-args --case-id <案件ID> --stage 2 --side <方> --out <執行資料夾>/<方>_stage2.json`。
5. 執行 `python main.py prompt round3_prompt --out <執行資料夾>/prompts/p5_<方>.txt --phase p5 --side <方> --case-dir <案件資料夾> --set CASE_ID=<案件ID> --set SIDE=<方> --set SIDE_LABEL=<方名> --set OWN_VIEW_PATH=<執行資料夾>/<方>_view.json --set EXCHANGE_VIEW_PATH=<執行資料夾>/exchange_view.json --set OWN_PREVIOUS_PATH=<執行資料夾>/<方>_stage2.json --set OWN_ANALYSIS_PATH=<執行資料夾>/<方>_stage1.json --set OPPONENT_SUMMARY_PATH=<執行資料夾>/p5_summary_<對方>.json --set OUTPUT_PATH=<執行資料夾>/p5_<方>.json`,派一個 subagent(description「<方名>言詞辯論意旨狀」)。續跑時 Step 7 的檔案不在這次的執行資料夾,先照 Step 7 第 1、2 點重產。
6. 照 Step 7 第 4–6 點處理檢索被拒、查證(讀 `p5_<方>.json`)與 `record`,再執行 `python main.py brief --case-id <案件ID> --side <方> --round 3` 落地言詞辯論意旨狀。

### Step 9 — P6 診斷評估

法官讀法官角色檔(含爭點整理表)、雙方準備書狀與言詞辯論意旨狀的公開論證、讓步條件與程序事項,不讀雙方最初的分析(stage 1)。

1. 執行 `python main.py role-view --case-id <案件ID> --role judge --out <執行資料夾>/judge_view_p6.json`。
2. 執行 `python main.py public-args --case-id <案件ID> --stage 2 --out <執行資料夾>/p6_round2.json` 與 `python main.py public-args --case-id <案件ID> --stage 3 --out <執行資料夾>/p6_round3.json`。
3. 執行 `python main.py finalize --case-id <案件ID> --for-judge > <執行資料夾>/anchor.json`(這是唯一需要輸出導向的指令,導向的檔案要在執行資料夾裡)。
4. 執行 `python main.py prompt diagnosis_prompt --out <執行資料夾>/prompts/p6_diagnosis.txt --phase p6 --set CASE_ID=<案件ID> --set JUDGE_VIEW_PATH=<執行資料夾>/judge_view_p6.json --set BRIEF_ARGS_PATH=<執行資料夾>/p6_round2.json --set CLOSING_ARGS_PATH=<執行資料夾>/p6_round3.json --set ANCHOR_PATH=<執行資料夾>/anchor.json --set OUTPUT_PATH=<執行資料夾>/verdict.json`,派一個 subagent(description「法官診斷」)。這裡先不落地。

### Step 10 — 診斷的機械檢查

執行 `python main.py check-judge --case-id <案件ID> --json <執行資料夾>/verdict.json`。印「未通過」(`risk_map` 新鍵結構、自承用語)就把報錯原文交回同一個法官 subagent,只改被點名的地方後重寫;同一份最多退回 2 次。轉述警告與勝訴機率類字樣的警告不退回,照實列入最後回覆。

### Step 11 — 診斷的引用查證與落地

1. 開一個新的、乾淨的查證 subagent(description「診斷引用查證」),指示它:用 Read 讀 `<執行資料夾>/verdict.json`,把 `citations_used` 全部列進**一個** `python main.py verify <全部引用>` 指令(用 Bash 工具,不要用 PowerShell,不要用迴圈逐筆跑);最終回覆只寫一行「全部通過」或「未通過:」加上沒通過的引用與狀態。未通過就交回法官 subagent 刪掉或改用通過的引用(算一次退回)。
2. 執行 `python main.py verdict --case-id <案件ID> --json <執行資料夾>/verdict.json` 落地。被拒絕(第249條與115台抗105 同括號、自承用語、`risk_map` 新鍵)時把報錯原文交回同一個法官 subagent,只改被點名的地方。

### Step 12 — P6 起訴狀 v2(建議版)

1. 執行 `python main.py role-view --case-id <案件ID> --role plaintiff --out <執行資料夾>/plaintiff_view_p6.json`(診斷落地後才有 `diagnosis`)與 `python main.py public-args --case-id <案件ID> --stage 1 --side plaintiff --out <執行資料夾>/plaintiff_stage1.json`。
2. 執行 `python main.py prompt revision_prompt --out <執行資料夾>/prompts/p6_revision.txt --set CASE_ID=<案件ID> --set ROLE_VIEW_PATH=<執行資料夾>/plaintiff_view_p6.json --set ANALYSIS_PATH=<執行資料夾>/plaintiff_stage1.json --set RETRIEVAL_CACHE_DIR=database/live_runs/case-<案件ID>/retrieval_cache/plaintiff --set OUTPUT_PATH=<執行資料夾>/revision.json`,派一個新的撰狀 subagent(description「原告起訴狀 v2 撰狀」)。
3. 執行 `python main.py revision --case-id <案件ID> --json <執行資料夾>/revision.json --check`。印「未通過」(事實對應不到、寫進被告推測、程序事項缺漏)就把報錯原文交回同一個撰狀 subagent;同一份最多退回 2 次。通過時會印出正文與「落地前要全部 published 的引用」。
4. 開一個新的、乾淨的查證 subagent(description「起訴狀 v2 引用查證」),照 Step 3 第 4 點查證上一點列出的全部引用(`--read-by plaintiff`),但實質核對只做確認版沒有引用過的判決(確認版已核對支持的,程式會沿用),結果寫進 `<執行資料夾>/revision_citation_review.json`;沒有新判決時寫 `[]`。
5. 執行 `python main.py revision --case-id <案件ID> --json <執行資料夾>/revision.json --review-json <執行資料夾>/revision_citation_review.json` 落地(CLI 執行時另加 `--snapshot database/live_runs/case-<案件ID>/retrieval_cache`)。被擋的引用照 Step 3 第 5 點處理。v2 只是建議版,不會取代律師確認的起訴狀。

### Step 13 — 回報使用者

- 官方事實層:哪一方查核了商工登記、起訴審查事項、原告如何補正;未查核的一方照實說未查核。
- 起訴前檢查的提示(程序類型、調解、時效),只是提示。
- 起訴狀 v1 全文;`fact_gaps`、`lawyer_notes`;哪些事實因為對應不到被移到事實缺口。
- 有跑到 P2 時:被告讀的是哪一版起訴狀(律師確認版或系統原稿);逐點表態各幾點(不爭執、否認、爭執形式上真正、待被告本人確認)、哪幾點是推測;抗辯清單;`to_confirm`;`answer` 的警告(例如爭執形式上真正但證據不是文書)。
- 有跑到 P3 時:爭點整理表的爭點數(推測爭點另計)、不爭執事項、闡明與訊問各幾則、補正追問;`issue-sheet` 的警告。
- 有跑到 P4、P5 時:雙方每輪的退回次數與原因(查證未通過、缺少爭點段落)、第255條警告(原告新增請求權基礎)、推測字樣警告、對手摘要的 `check-summary` 警告;準備書狀與言詞辯論意旨狀是否都落地。
- 有跑到 P6 時:各爭點強中弱、`evidence_todo`、`complaint_revisions` 哪些採用、哪些沒採用及理由;起訴狀 v2 是否落地、律師段落有沒有因對不到事實而沒放進 v2;勝訴機率類字樣警告。
- 每次退回的報錯原文與次數;查證結果(存在性、摘句比對、實質核對分開說);被排除的引用。
- 檢索次數與實際上網抓全文數(看指令印出的預算摘要)。
- `record` 與 `complaint` 的警告。
- 轉述待核對警告(`check-judge`、`record`、`verdict`、`issue-sheet` 印出的「轉述警告」,即 `other_side`、`missing`、`unquoted`),照印出的原句列出;這些是程式比對,要由律師核對,不擋落地,也不要因此退回法官。
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
- 角色之間的資訊隔離靠提示與調度:同一個 Claude Code 程序裡的 subagent 共用權限。程式禁止所有 agent 直接讀檢索快取與紀錄;UI 執行 v2 案件時另外只放行本次執行、本案件與本 skill 資料夾的讀取。同一個執行資料夾裡的案件輸入檔與原告角色檔,被告的 subagent 仍然讀得到,只能靠事後稽核(`scripts/audit_run.py`)確認。
