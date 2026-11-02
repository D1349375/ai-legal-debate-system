# 書狀交換改版:接手文件

> 更新於 2026-11-02(W3 檢核通過後)。給下一個接手的 agent 或組員。每完成一項就更新第 2、3 節。
> 決賽 2026-11-07,程式 11/5 晚上凍結。

## 1. 先讀這些

| 順序 | 文件 | 看什麼 |
|---|---|---|
| 1 | 本文件 | 現況與下一步 |
| 2 | [pleading-exchange-plan.md](pleading-exchange-plan.md) | 每一項要改什麼、測試、實跑檢查、停損 |
| 3 | [pleading-exchange-spec.md](pleading-exchange-spec.md) | v0.2 規格 |
| 4 | [iteration-log.md](iteration-log.md) | 做過什麼、為什麼 |
| 5 | [retrieval-interface.md](retrieval-interface.md) | 組員的檢索介面,寫範本前要看 |
| 6 | [main-finals-fix-list.md](main-finals-fix-list.md) | W0 的檢查清單 V30–V46、M12 退回時的分級流程 |

規格與組員文件對基準分支的說法不同時,以本文件為準:新架構在 `pleading-exchange`,不從 `retrieval-optimization` 開。

## 2. 目前狀態

| 分支 | 工作目錄 | commit | 用途 | 遠端 |
|---|---|---|---|---|
| `pleading-exchange` | `.claude/worktrees/pleading-exchange` | `dea9736`(合併組員的 `retrieval-rules` 等);之後 W3 | 新架構主線 | W2、W3 與組員的檢索、`v2-flow-fixes` 都已 push |
| `main-finals-fixes` | `.claude/worktrees/main-finals-fixes` | `cf6f98c` 之後 W0 修正陸續 commit(T1–T3 已完成) | 新架構沒過時的退路;W0 修正 T1–T6 在這裡 | 以 `git log` 為準 |
| `main` | 專案根目錄 | `aeb618e` | 最後保底,沒動 | 已同步 |
| `origin/retrieval-optimization` | 無 | `e8404f7` | 組員的檢索來源 | 組員維護 |

| 項目 | 狀態 | 驗證 |
|---|---|---|
| R0 檢索搬入 | 完成,`7ae2d9d` | 離線 383 項、連網 11 項、CLI 實測、瀏覽器示範案 25/25 |
| W1 案件輸入與起訴前檢查 | 完成,`ca38d03` | 離線 427 項、2 項略過;瀏覽器走過建案與舊案,深淺色都看過 |
| W0 第二批修正實跑 | 完成,在 `main-finals-fixes` 跑(2026-11-02) | 依手冊判準通過;找到 9 項問題,T1–T6 由 Codex 在 `main-finals-fixes` 修,T7 再合併進本分支。見 `git show main-finals-fixes:docs/live-run-records/w0-2026-11-02.md` 與該分支 `docs/zh/w0-findings/README.md` |
| W2 起訴狀 v1 | 完成,`624fe8e` | 離線 451 項、2 項略過(新增 24 項);P1 實跑見 `docs/live-run-records/w2-2026-11-02.md` |
| W3 關卡 1 與續跑 | 已完成,Claude 檢核通過(2026-11-02) | 新增 18 項(`tests/test_gate.py`),離線全套見計畫第 6 節 W3 列;假 Claude 走過瀏覽器流程;W2 的 Claude 案件用資料庫複本編輯、確認、產生續跑檔案。沒有 Claude 實跑 |
| W4–W11 | 未開始 | 無 |

**新流程接上 P0、P1 與關卡 1。** v2 案件走新的 `SKILL.md` Step 1–3:原告分析(新檢索指令)→ 撰狀 subagent 交 JSON → `main.py complaint` 檢查事實對應、由程式組成正文、查證後落地。UI 可選「只產起訴狀(停在關卡 1)」或「跑完全程(關卡 1 自動通過,標未經律師確認)」。律師在「訴狀骨架」分頁選版本(可先編輯成律師版)確認並繼續或到此結束,寫進 `Case.gates_json`,不可覆寫;續跑從被告防禦分析開始,prompt、`landed.json` 的 `confirmed_complaint` 與 `role-view` 的 `complaint` 都指向確認版。被告防禦分析以後暫時借舊流程(`references/legacy-v1.md`),被告仍讀全部案件事實,W4 才改。

## 3. 下一步

### 3.1 W0:已完成

2026-11-02 在 `main-finals-fixes` 跑完,依手冊判準通過(11 分 54 秒、2.89 美元、分類器中止 0)。找到的問題在該分支 `docs/zh/w0-findings/`:T1–T6 由 Codex 修在 `main-finals-fixes`,T7 合併進本分支;T8(條文內容核對)、T9(最強論點選句)只修本分支。**本分支不要自己修 T1–T6**,等 T7 合併,避免衝突。

### 3.2 W2:起訴狀 v1(已完成,`624fe8e`)

做了什麼、和計畫不同的地方、實跑結果:計畫第 6 節 W2 列、[iteration-log.md](iteration-log.md)、`docs/live-run-records/w2-2026-11-02.md`。

- `retrieval-rules` 還沒有,`SKILL.md`「P1 檢索規則」一節是暫代的固定文字,組員做好後改成填指令輸出。
- 實跑沒有走 UI 按鈕:用 `LiveRunManager.start` 同一條程式路徑,只在 prompt 末尾加「只跑到 Step 3」(W3 才有 `stop_after`)。所以 UI 會把這次執行判為「不完整」(缺 Stage 2、3 等),這是預期的。
- W0 的 T1(資料庫環境變數)還沒合併:實跑時不要設 `LEGALDEBATE_DB_URL`,用 worktree 預設資料庫。

### 3.3 W3:關卡 1 與續跑(已完成)

做了什麼、和計畫不同的地方:計畫第 6 節 W3 列、[iteration-log.md](iteration-log.md)。重點:

- `server/live_run.py`:`RUN_STEPS_V2`、`_resume_plan_v2`、`_pipeline_missing_v2` 依 `protocol` 分流;`stop_after=complaint`;v2 有自己的 prompt(`build_prompt_v2`),續跑寫明確認版;舊案續跑提示改指向 `references/legacy-v1.md`(W2 留下的第 2 件)。每次執行另存 `prompt.txt`。
- 關卡 1 自動通過由**後端**在執行結束時記錄(`_auto_gate`),只在「沒有停止點、而且起訴狀之後的階段真的有落地」時記;起訴狀落地後就失敗或取消的執行不記,律師之後仍可確認。主 agent 不記關卡。
- `POST /api/cases/{id}/gates/complaint`:`version_id`、`action`(`continue`、`finish`)。結構規則在 `database/db.py` `record_gate` 硬擋(只寫一次、只能是該案件的起訴狀、律師版要 published);引用再用畫面同一套規則看一次。該案件執行中不能確認。
- v2 案件不選書狀、沒有補產(Step 9C 只給舊流程),API 會拒絕。
- `tests/test_live_run.py` 的 `create()` 改成直接落地舊流程案件(W1 起 UI 建的都是 v2,那些測試測的是舊流程);續跑提示的一個斷言改成 `legacy-v1.md`。

W4 接手要注意:

- 防禦分析的步驟定義在 `RUN_STEPS_V2` 的 `defense`(現在指向 `legacy-v1.md` Step 2)與 `_pipeline_missing_v2`;W4 換成新範本時這兩處、`build_prompt_v2` 的續跑文字(`resume_instructions_v2`)、`SKILL.md`「關卡 1」「Step 4 以後」要一起改。
- 被告角色檔要讀 `database/db.py` `current_complaint`(關卡確認版;沒確認時是最新系統原稿,`confirmed=False`)。確認版是律師版時正文**沒有**【本稿產出說明】(編輯器存檔時就拿掉了);系統原稿則有,給被告前要切掉(那段含 `fact_gaps`、`lawyer_notes`)。
- 律師版的 `structured_json` 是空的(編輯器只存正文)。逐點表態要以確認版正文的〔CF…〕為準,不能用原稿的 `fact_points`(規格第 13 項)。新增段落沒有〔CF…〕時只提示(`new_paragraphs_without_cf`)。
- `pleading_materials` 還沒改,只給舊案補產用。

組員 `retrieval-interface.md` 第十三節(P1 該接、W2 沒接的四件)在 W3 的處理:

| # | 事項 | 狀態 |
|---|---|---|
| 4 | 撰狀後查證加 `--read-by plaintiff`,`not_read_by_side` 退回 | **已接**。`main.py complaint` 落地時以 `read_by="plaintiff"` 比對判例(新增 `--snapshot`,UI 執行時用環境變數),是程式硬擋;`SKILL.md` Step 3 第 4、5 點同步改,放行條件改寫成「只有 `published` 放行」。新增 3 項測試。沒有 Claude 實跑 |
| 2 | 撰狀 subagent 不搜尋,只引用分析讀過的判決 | W2 的 `complaint_prompt.txt` 已寫「只讀分析已列的判決,不另外搜尋」;第 4 項的硬擋補上程式核對。範本沒動 |
| 1 | 正式引用須本輪讀過全文;記憶中的判決只進 `precedent_leads` | **留給下一項**。`stage1_prompt.txt` 已寫「記憶中的判決只能當線索」「`cited_precedents` 只列本輪讀過全文的」,但輸出 JSON 還沒有 `precedent_leads` 欄位,`record` 也不收。加欄位要改範本與 `record`,要 Claude 實跑驗證 |
| 3 | 示範案用 `retrieval-rules --exclude 114年度台上字第1987號` | **留給下一項**。要先把 `SKILL.md` 寫死的「P1 檢索規則」換成 `retrieval-rules --phase p1 --side plaintiff --case-dir … [--exclude …]` 的輸出(組員的輸出提到 `precedent_leads`,和第 1 項一起改)。排除字號由誰帶入未定:組員提案由 `server/live_run.py` 設環境變數,要組員先改指令;在那之前主 agent 不知道哪件是示範案,無法自己加。最晚 W8 示範案實跑前要決定 |
| 另 | SKILL 改寫要一起換的清單 | P1 的 `stage1_prompt.txt` 在 W2 已換成三個檢索佔位符;建立案件資料夾與只給各角色自己的路徑已在 SKILL「路徑」一節;`retrieval-rules` 尚未取代寫死的規則(同第 3 項)。**`stage2_prompt.txt`、`stage3_prompt.txt` 仍用 `{STATUTES_DIR}`、`{JUDGMENTS_DIR}` 與 Grep**,關卡 1 之後的過渡續跑會用到它們,W6 改寫時換 |

注意:`reads/` 讀過紀錄是組員在 W2 實跑之後(`eaa3971`)才加的,W2 兩件案件的快照沒有這個紀錄;若要用那兩件的快照重新落地起訴狀,判決會被擋成 `not_read_by_side`。已落地的不受影響。

### 3.4 之後

W4 答辯狀、W5 爭點表、W6 準備書狀、W7 診斷與 v2、W8 全程實跑、W9 三劇本、W10 全文互看、W11 對外材料。每項的細節在計畫裡。

| 時間 | 判斷 |
|---|---|
| 11/3 晚 | W1–W7 沒完成就不做 W9、W10 |
| 11/4 中午 | W8 主線最晚時間 |
| 11/4 晚 | 依計畫第 5 節決定是否採用。沒過就用 `main-finals-fixes`,新架構講成下一版設計 |
| 11/5 晚 | 程式凍結 |
| 11/6 | 只演練 |

## 4. 常用指令

```bash
python -X utf8 -m pytest -q -m "not network" -p no:cacheprovider
```

```bash
python -X utf8 -m pytest -q -m network -p no:cacheprovider tests/test_verify.py tests/test_fjud.py tests/test_law_lookup.py tests/test_judgment_search.py
```

```bash
python main.py verify "最高法院105年度台簡上字第33號" "最高法院105年度台上字第99999號"
```

預期:離線約 4–7 分鐘,目前 531 項通過、2 項略過(W3);連網 11 項通過;第三條前者 `published`、後者 `not_found`。

手動試用時要用暫存資料與快取,不要寫進真的資料庫:

| 環境變數 | 用途 |
|---|---|
| `LEGALDEBATE_DB_URL` | 暫存資料庫,例如 `sqlite:///<暫存資料夾>/check.db` |
| `LEGAL_DEBATE_RETRIEVAL_CACHE` | 暫存檢索快取 |

瀏覽器驗證:預覽工具讀主目錄的設定,worktree 要另開埠啟動再用網址連(我們用過 8123)。瀏覽器會快取 `app.js`,看不到新畫面時先強制重新載入。

## 5. 不能違反的事

- **誠實**:錄製內容要標示,查證失敗照實顯示,單案結果不講成統計。參賽資料不實會被取消資格。
- **不用中國機構開發的模型、API 或 MCP。**
- **事實不能編**:模型不得補寫案情、清算人姓名或證據。被告的推測只能標 `hypothetical`。
- **不代替模型或律師**:不手改模型 JSON 後說是模型產出,編排者不代寫被退回的內容。
- **公開 repo**:不 commit `database/legal_debate.db`、本機絕對路徑、語料全文、個資。`送件/` 不進 git。
- **不要 push、不要併 `main`**,除非使用者明確要求。後續項目 commit 前先問使用者。
- **不要併 `retrieval-optimization` 或 `role-separation-redesign`**。那兩條有 662 個紀錄檔、含本機路徑,路徑長度也會讓 Windows checkout 失敗。
- **組員負責的檔案不直接改**:`retrieval-interface.md` 第二節列的檢索模組、`verify.py` 查證部分與檢索指令。要新介面就提出來。
- **`server/live_run.py` 保留兩處**:`SNAPSHOT_ENV` 環境變數、`DISALLOWED_TOOLS` 的三條規則。
- **輸出欄位**:不用 `reasoning`、`thinking`、`trace`、`analysis`、`internal`、`scratch` 命名,見規格第 8 節。
- **檢查規則**:結構可以硬擋,自然語言只警告。同一份輸出最多退回 2 次。
- 回覆使用者用繁體中文。

## 6. 等別人的事

| 等誰 | 事項 | 現況 |
|---|---|---|
| 使用者 | 把分支 push 給組員 | 未 push,組員拿不到 |
| 使用者 | 把基準分支的決定告訴組員 | 不確定是否已傳 |
| 組員 | `retrieval-rules` 指令 | 尚未實作 |
| 組員 | `search-judgments` 排除來源裁判的參數 | 還沒提出。沒有時用檢索紀錄稽核 |
| 組員 | 本機未推的修正 | 對方交接文件提到有未提交的改動 |
| 組員 | 更新介面文件的基準分支,之後改在 `pleading-exchange` 維護檢索 | 還沒通知 |
| 組員與使用者 | 引用設計第七節 | 建議決賽前只採 `basis` |
| 律師 | 規格第 10 節的待確認項目 | 沒有律師看過 |

## 7. 已知陷阱

| 地方 | 問題 |
|---|---|
| `server/services.py` `get_case_detail` | `pleadings[side]` 取最後一筆系統版。有 v2 或準備書狀後要依書狀類型過濾 |
| `server/live_run.py` `resume_plan` | 舊流程把任一書狀當成 Step 9 完成;W3 已依 `protocol` 分流,v2 走 `_resume_plan_v2`。新增步驟時兩邊都要看 |
| `server/seed.py` 匯出 | 匯出不帶 `id`,匯入後重新編號。`Case.gates_json` 的 `version_id` 和律師版的 `parent_id` 一樣靠編號對應;原資料庫的書狀編號有缺號時會對錯。W8 的 X10(乾淨 clone 重播)要確認 |
| W2 的兩件實跑案件 | 執行紀錄是 W3 之前跑的,`stop_after` 為空,狀態仍是「不完整」;關卡 1 現在可以確認。不要在 worktree 資料庫上試確認,用複本 |
| `server/services.py` `_is_system` | 只認 `None`、`system`,新增 `system_revision` 時要處理 |
| `server/seed.py` `_TABLES` | 新資料表要加入,否則匯出示範資料會遺失 |
| `main.py check-judge` | 目前以 `questions` 判斷輸入類型,W5 要改 |
| `database/db.py` `pleading_materials` | 只給舊案補產書狀用 |
| 被告隔離 | 只靠提示與調度,程式擋不住 `case.json`。要用 `scripts/audit_run.py`(W4 新增)稽核,對外也要照實講 |
| 來源裁判 | 示範案的原判決查得到,可能被模型搜到,拿來講命中前要先查紀錄 |
| P4、P5 對手摘要 | 沿用舊 Step 4 從 `public-args` 摘對造 stage 1。v2 原告的 stage 1 是 P1 分析,公開段落仍有事實經過與沒列進起訴狀的證據;被告在 P4 讀到就破了 P2 的隔離。規格 5.6 已改成摘對造書狀,W6 照做 |
| P6 法官讀 `public-args` | 同上,原告分析等於間接給了事實經過,和 5.5「法官不讀 `facts_summary`」不一致。規格 5.7 已改成只給 stage 2、3,W7 照做 |
| 主 agent 上下文 | 舊流程 run-4 主 agent 112 輪,上下文從 3.1 萬 token 長到 19.3 萬,每輪都重讀,約佔全程輸入 token 八成(子 agent 每個最多約 5 萬)。不是單一大檔,而是每派一個 subagent 固定多約 1 萬:回覆 JSON 進來一次、主 agent 再 Write 成檔一次;另外第一次 Read 範本約 1 萬、`finalize` 約 8 千、自行 Read `main.py` 原始碼約 8 千、範本 PDF 約 1 萬。v2 的 subagent 比舊流程多(P1、P2 各拆成分析與撰狀,另有 v2 改寫與多次查證)。P1 已改成交接檔案(`SKILL.md`「派 subagent 與交接檔案」):`main.py prompt` 填好範本寫成檔、subagent 自己讀;範本用 `{OUTPUT_PATH}` 讓 subagent 自己寫輸出、只回路徑;`role-view`、`public-args` 加 `--out`。W4 起的新範本照同一套寫 |
| `demo/recorded_live_checks.json` | `checks` 是空的,斷網示範「查無字號」可能沒有錄製結果,W8 要確認 |
| 離線測試偶發失敗 | `tests/test_live_run.py` 的 `test_pleading_run_lands_only_the_chosen_document` 曾失敗一次,原因未查明 |
| 舊 worktree | `.claude/worktrees/ui-live-run-0f7cc8` 的資料庫有實跑 #1–#4,處理前不要清理 |

## 8. 決賽材料還沒做

這些不在 git,放在專案根目錄的 `送件/決賽/`,接手前先讀 `決賽前統整_2026-10-31.md`。

- 投影片仍有已查明不成立的說法,例如「1 筆捏造字號攔截」。
- 問卷結果本機還沒有,附件 3 承諾的「回饋→修正」還沒兌現。
- 新架構定案後,簡報、講稿、擬答要照計畫 W11 改。沒定案前不要動。
