# 階段三交接：把上網檢索接進辯論流程

> **交接日期**：2026-11-01
> **分支**：`retrieval-optimization`（自 `role-separation-redesign` 分出）
> **前一個工作階段完成**：階段一（檢索工具）、階段二（評估）
> **這份文件給**：接手實作階段三的新工作階段

先讀這三份，再動手：

1. [retrieval-optimization-plan.md](retrieval-optimization-plan.md)：完整計畫，階段三在第七節，順序在第十節。
2. [retrieval-evaluation-phase2.md](retrieval-evaluation-phase2.md)：評估數據與定案的預設值。
3. 本文件：已完成的程式、要改的地方、踩過的坑、使用者的偏好。

---

## 一、目前狀態

### 已 commit

| commit | 內容 |
|---|---|
| `18e19fc` | 階段一：`article`、`search-statutes`、`search-judgments` 三個指令；修正判決查證兩個既有問題 |
| `abb9a0c` | 階段二：評估腳本與結果、評估報告、計畫、組長提案 |
| `a5ae6c7` | 定案「只用網路＋快取」、本交接文件 |
| `616edfa` | 引用設計討論稿 `citation-needs-redesign.md` |
| `966fcbc` | 階段三步驟 1、2、4（程式與測試） |
| `2fa1c6b` | 計畫第七節第 0 項、本文件的進度 |
| （下一筆） | 配合組長《書狀交換架構改版規格》的檢索調整，見下方「配合書狀交換架構」 |

### 階段三進度（2026-11-01 第二個工作階段）

| 步驟 | 狀態 | 程式 |
|---|---|---|
| 1 快取、`judgment`、查證改讀快取、無法檢索 | 完成 | `engine/retrieval_cache.py`（新）、`engine/verify.py`、`engine/law_lookup.py`、`engine/judgment_search.py`、`main.py`、`server/services.py`、`server/app.py`、`server/live_run.py`（UI 實跑以環境變數 `LEGAL_DEBATE_RUN_SNAPSHOT` 指定快照）、`ui/app.js`、`.gitignore` |
| 2 檢索紀錄、指令層預算 | 完成（`internal_notes.search_log` 的格式檢查未做，見下） | `engine/search_log.py`（新）、`main.py` |
| 3 prompt 與 SKILL | **未做**，見下 | — |
| 4 法條查證改用名稱索引 | 完成 | `engine/verify.py`（`STATUTE_CITATION_RE` 改為依索引找最長法規名稱的比對器，介面同正規式）、`engine/law_lookup.py`（`ALIASES` 簡稱表） |
| 5 實跑驗收 | 斷網測試以假連線完成（`tests/test_retrieval_cache.py`）；Claude Code 實跑未做 | — |

做法上的決定：

- **快照與預算怎麼傳**：指令加 `--snapshot <資料夾>`、`--log <檔案>`；`record`、`verify` 也接受 `--snapshot`。預算的階段由紀錄檔名判斷，不用另一個設定檔（角色改得到）。快照與階段名稱的最新規則見下方「配合書狀交換架構」。
- **預算計數**：搜尋次數只算 `search-judgments`；全文份數只算實際上網抓的判決，`article`、`search-statutes` 只記錄不計入。
- **字號 → JID**：快照內記錄（同一案件不重查）；不做長期快取（計畫「搜尋結果不做長期快取」）。長期快取的全文不能用來確認字號有哪些文件：同字號甚至同一天可以有多份（115台上192 有 20260325 的序號 1、2 兩份），快取只有其中一份時會被誤當成唯一，所以不在預先內容也不在快照時一律上網查字號。這種同日多份的字號，指定日期也仍是 `ambiguous`（既有規則）。
- **UI 的 `local_cache_only`**：改指「只有過期條文快取」或「判決快取有、但官方未確認唯一性」，仍不放行。
- **自動重試**：所有官網連線失敗重試一次（含 `search-statutes`、`search-judgments` 的搜尋本身）。

尚待決定或等引用設計定案的部分見文末「階段三未完成事項」。

### 配合書狀交換架構（組長《LegalDebate 書狀交換架構改版規格》v0.1）

組長可能依該規格把流程改成 P0～P6（起訴狀 → 答辯狀 → 爭點整理表 → 準備書狀 → 言詞辯論意旨狀 → 診斷）。檢索做成和流程無關的服務，配合規格做了以下調整：

| 調整 | 原因 | 程式 |
|---|---|---|
| **快照依角色分開**：`<快照根目錄>/plaintiff/`、`<快照根目錄>/defendant/`；查證與調度員以根目錄為 `--snapshot`，讀取時涵蓋雙方，新讀的記在根目錄 | 判決內容公開，但讀過哪些判決會透露研究方向；規格 P2 明定被告看不到原告的內部分析 | `engine/retrieval_cache.py`（`snapshot_dirs`） |
| **檢索指令只用明示的 `--snapshot`**，不讀環境變數 | 環境變數指向根目錄；角色漏給參數時若退回根目錄，對造就看得到 | `main.py`（`_snapshot`） |
| **快照以案件為單位**：UI 實跑的環境變數改為 `database/live_runs/case-<案件ID>/retrieval_cache/`，續跑沿用 | 規格的律師確認關卡會把一個案件分成多次執行；最後的查證要比對前面讀過的全文 | `server/live_run.py`（`case_dir`） |
| **禁止 Read／Glob／Grep 直接讀**長期快取、案件快照與檢索紀錄 | 同一個 Claude Code 程序的角色共用權限，只能全部禁止；指令以 Python 讀檔不受影響。已用真的 Claude Code 驗證（`tests/test_claude_permissions.py`，需設 `LEGALDEBATE_PROBE_CLAUDE=1`）。注意：Read 被拒時 CLI 不列在 `permission_denials`，而是工具結果回錯誤 | `server/live_run.py`（`DISALLOWED_TOOLS`） |
| **預算認規格的階段名稱**：`p1`／`complaint` 8／10、`p2`／`scenario`／`answer` 8／10（劇本與答辯狀共用一檔）、`p4`／`brief` 4／5、`p5`／`closing` 2／3；`stage1～3` 保留；看不出階段時 4／5 | 規格把三輪改成 P1～P5；P5 只收斂既有爭點 | `engine/search_log.py` |
| **檢索紀錄記爭點**：`search-judgments`、`judgment` 加選填 `--issue <爭點id>` | 規格 P4 以爭點 id 組織攻防 | `main.py`、`engine/search_log.py` |
| **判決常一起引用的法條**：抓回全文後列出出現在兩份以上判決的實體法條 | 原告寫起訴狀時檢查有沒有漏掉該一起主張的補充性法條 | `engine/judgment_search.py`（`statute_counts`）、`main.py` |

紀錄檔建議放 `database/live_runs/case-<案件ID>/search_logs/<side>_<階段>.jsonl`（例如 `plaintiff_p1.jsonl`）；指令與佔位符要等新範本出來後由 SKILL.md 寫明。

### 不要碰的檔案

工作區有使用者自己未提交的改動，與本工作無關，**不要 commit、不要修改、不要還原**：

- `demo/recorded_cases.json`
- `docs/LegalDebate_簡報素材_設計邏輯.md`
- `docs/zh/role-separation-execution.md`、`docs/zh/role-separation-verification.md`
- `scripts/rerun_role_separation.py`、`server/seed.py`、`tests/test_rerun_role_separation.py`
- `database/legal_debate.db.bak-before-002`
- `docs/live-run-records/role-separation-real-2026-10-31-002-redesign-20261031/`
- `docs/zh/citation-needs-redesign.md`（使用者確認的引用設計討論稿，已於 `616edfa` commit；階段三的檢索目標依此文件決定，見計畫第七節第 0 項）

commit 時一律用 `git add <明確檔名>`，不要用 `git add -A` 或 `git add .`。

### 測試

- 全部：`python -m pytest -q`，約 5 分鐘，交接時 **451 passed、1 skipped**（skip 是需手動啟用的 Claude 權限探針）。階段三步驟 1、2、4 完成後不連網 **479 passed、1 skipped**；改動相關的連網測試 11 項全過。配合書狀交換架構調整後不連網 **491 passed、2 skipped**（兩項 skip 都是 Claude Code 權限探針，設 `LEGALDEBATE_PROBE_CLAUDE=1` 實跑皆通過）。
- `tests/conftest.py` 把檢索快取改到每個測試的暫存目錄；測試不會讀寫 `database/retrieval_cache/`。
- 不連網：`python -m pytest -q -m "not network"`。
- 連網測試標記為 `network`（見 `pytest.ini`），會實際打官方網站。

---

## 二、已完成的程式（階段一、二）

| 模組 | 用途 | 主要函式 |
|---|---|---|
| `engine/fjud.py` | FJUD 連線與解析，查證與檢索共用 | `Session`（請求間隔 1.5 秒）、`advanced_search`、`fetch_document`、`extract_full_text`、`parse_result_page`、`SORT_DATE`／`SORT_SIZE` |
| `engine/judgment_text.py` | 判決全文整理，上網與本地共用 | `flatten`、`disposition`、`is_procedural`、`cited_statutes`、`matched_sentences`、`summarize`、`law_names` |
| `engine/judgment_search.py` | `search-judgments` 的核心 | `search_judgments`（上限 5 頁、10 份全文；只抓 `TPSV` 判決；`--save-dir` 存檔） |
| `engine/law_lookup.py` | 法條依條號查與關鍵字搜 | `lookup_article`、`search_statutes`、`resolve_law`、`load_law_index` |
| `engine/verify.py` | 查證；FJUD 部分改呼叫 `engine/fjud.py` | `_fjud_search(jyear, jcase, jno)`、`_fetch_judgment_text` |
| `scripts/build_law_index.py` | 從法務部開放資料建 `corpus/statutes/law_index.json`（11,804 部，只有名稱與 pcode） | — |
| `scripts/evaluate_retrieval.py` | 階段二評估 | — |

CLI 都在 `main.py`：`article`、`search-judgments`、`search-statutes`。

---

## 三、階段三要做的事（照這個順序）

完整規格見計畫第七節。以下是實作要點與程式位置。

### 步驟 1：快取、讀全文指令、查證改讀快取、無法檢索的處理（計畫第七節第 3、5、6 項）

**長期快取** `database/retrieval_cache/`：

- 先在 `.gitignore` 加入 `database/retrieval_cache/`（目前只忽略 `*.db` 與 `database/live_runs/`）。
- 判決以 JID 為鍵，長期有效；查找順序是長期快取 → `corpus/judgments/`（唯讀預先內容）→ 上網，上網抓到的寫回長期快取。
- 條文以 pcode＋條號為鍵，7 天有效，過期重抓；記錄官方異動日期。
- 搜尋結果列表不做長期快取。
- 每筆記錄來源網址與抓取時間。

**每次實跑快照** `{RETRIEVAL_CACHE_DIR}`（新佔位符，路徑在本次實跑資料夾內）：

- 記錄用到的每份判決與條文：來源（預先內容／長期快取／上網）、抓取時間、內容雜湊，並存副本。
- 角色與查證都讀這份快照。

**新指令** `python main.py judgment <裁判字號或 JID> [--doc-date YYYYMMDD]`：

- 經快取取得全文，印去換行版（`judgment_text.flatten`）。
- 同字號多份文件時要求 `--doc-date`，規則照 `verify_judgment_citation` 的 `ambiguous`。
- 角色正式引用前「讀過全文」靠這個指令；Stage 2、3 讀對方引用的判決也用它。

**查證改讀快取**：

- `engine/verify.py` 的 `verify_judgment_citation` 現在先查 `JUDGMENTS_DIR`（本地）再上網，改成先查快取（含預先內容）再上網、抓到寫回。
- `verify_statute_citation` 在快取有效期內可用快取放行（註明 `verified_via` 與抓取日期），過期重抓失敗回 `network_error`，不用過期版本放行。
- `search-judgments --fetch`、`article` 抓到的內容也寫進快取。

**無法檢索**：

- 重試一次仍失敗、且快取沒有時，回 `retrieval_unavailable`，訊息寫明「不代表查無資料」。
- **不退回本地 5 部法規**（`corpus/statutes/*.txt` 版本過時）。

**UI 端也有本地退路，要一起改**（`server/services.py`）：

- `_STATUTE_FILES`、`_load_statute_cache`、`_local_statute`：法條查證失敗時讀本地法規，狀態 `local_cache_only`。改讀長期快取。
- `_local_judgment` 與 `verify_one` 內判決部分（約第 952 行）：直接列 `JUDGMENTS_DIR`。改用同一套快取查找。
- `server/app.py` 第 169～170 行顯示本地語料筆數，可改顯示快取筆數，或保留但標明用途。

### 步驟 2：檢索紀錄、各階段規則、查詢預算（計畫第七節第 2、7、8 項）

- 三個檢索指令與 `judgment` 加 `--log <檔案>`，每次查詢的條件、命中數、抓了哪些全文自動附加；路徑由調度員給（新佔位符 `{SEARCH_LOG_PATH}`），**每個角色每輪一個檔**，對造讀不到。
- 預算（階段二定案）：Stage 1 搜尋 8 次、全文 10 份；Stage 2、3 各 4 次、5 份；讀快取裡已有的不計入。由指令依 log 計數，超過就拒絕並說明原因。
  - 待決定：預算值怎麼傳給指令。若用檔案（例如 log 旁的 budget 設定），注意 UI 實跑的角色對 `database/live_runs/**` 有 Edit 權限（`server/live_run.py` 的 `ALLOWED_TOOLS`），理論上改得到；可接受就照做，否則改由指令依 log 檔名判斷階段。
- `internal_notes.search_log` 選填，`engine/role_protocol.py` 只檢查格式、不強制。
- 各階段規則：Stage 1 主搜；Stage 2、3 補充檢索、優先讀對方引用的判決；法官、評估、書狀不搜尋；獨立查證不搜尋、只核對。

### 步驟 3：改 prompt 與 SKILL（計畫第七節第 1 項）

- 檔案：`.claude/skills/legal-debate/templates/stage1_prompt.txt`、`stage2_prompt.txt`、`stage3_prompt.txt`、`.claude/skills/legal-debate/SKILL.md`。
- 刪除 `{STATUTES_DIR}`、`{JUDGMENTS_DIR}` 佔位符與「讀 {JUDGMENTS_DIR}」類指示；加入 `{SEARCH_LOG_PATH}`、`{RETRIEVAL_CACHE_DIR}`，並在 SKILL.md 寫明調度員如何建立與填入。
- 立場檢索詞改為選用（SKILL.md 第 29 行「不能自行增刪」要改）；`engine/stance_rag.py` 保留，檔頭改為選用說明。
- 檢索步驟寫成五步以內：列候選 → `article` 讀條文 → `search-judgments` 用法條＋要件詞搜 → `judgment` 讀全文 → 正式引用規則不變。
- 遇到 `retrieval_unavailable`：相關內容寫「待確認」，不得用記憶充當查得結果。
- 改完後跑 `tests/test_role_protocol.py`、`tests/test_role_separation_acceptance.py` 等與模板相關的測試；`.pytest-tmp/`、`_tmp/` 裡有舊版模板副本，以 repo 正本為準。

### 步驟 4（可與 1～3 並行）：法條查證改用名稱索引（計畫第七節第 4 項）

- `engine/verify.py` 的 `parse_citation`、`citation_warning`、`verify_statute_citation` 目前只認 `STATUTE_PCODES` 的 11 部。
- 名稱切割用「索引中最長的法規名稱」（可參考 `judgment_text._longest_name` 的做法），避免把「依土地法第34條」切成「依土地法」。
- 簡稱對照表：消保法、個資法、民訴法等。
- 廢止法規歸為既有的 `version_unverified`，不新增狀態。
- `server/services.py` 的 `extract_citations`、`verify_one`（`law not in STATUTE_PCODES` 那段）要一起改。
- `tests/test_pleading_versions.py` 有「土地法第34條之1 → unsupported_law」的預期，要改。

### 步驟 5：實跑驗收（計畫第九節）

用 Claude Code 實跑一個錄製案例，與 2026-10-31 的紀錄比較，並做斷網測試（以假連線模擬）。

---

## 四、踩過的坑（官方網站的實際行為）

### FJUD

- **簡易搜尋是全文搜尋**：拿字號去搜，回的是內文引用這個字號的其他法院判決。查特定字號一定要用進階搜尋的 `jud_year`／`jud_case`／`jud_no`（`fjud.advanced_search(citation=...)`）。
- **全文在巢狀的 `<div class="htmlcontent">` 裡**：要依 div 層級取完整區塊（`fjud.extract_full_text`），不能用非貪婪正規表達式。
- **只勾民事仍會混入家事類 `TPSU`**：查證引擎只認 `TPSV`，`search-judgments` 標為「不可引用」。
- **舊裁判的 JID 沒有尾端序號**：如 `TPSV,106,台上,1362,20170906`。
- **沒有相關度排序**：預設依日期新到舊；`SORT_SIZE` 依篇幅大到小。
- **總筆數不穩定**：同一查詢相隔幾分鐘可能差 1～4%。
- **請求間隔**：連續請求太快會被拒，`fjud.Session` 已保證至少 1.5 秒。
- **同字號多份文件**：例如 111 台上 1069 有兩份，沒給日期時查證回 `ambiguous`（既有規則，正確）。

### 全國法規資料庫

- **條號不存在時回空殼頁**：沒有「查無資料」字樣，只是沒有 `law-reg-content` 區塊；偶爾存在的條文也會回空殼頁，所以 `lookup_article` 會重查一次。注意：`verify_statute_citation` 還沒有這個重查，空殼頁會被當成 `not_found`（步驟 4 一併處理）。
- **已廢止法規的條文用 `text-pre` 排版**，不是 `law-article`。
- **整合查詢只列「哪些法規含這個詞」**，順序不是相關度；要看條文得再對個別法規做條文檢索。
- **民法有「部分條文尚未生效」**（第 1223 條 2026-08-17 修正、公布六個月後施行）：官網單條頁面顯示的是新條文，查證會當成現行條文放行。尚未處理，可列為後續。

### 判決文字

- 判決原文約每 30 字換行，詞組跨行會搜不到；一律先 `flatten`。
- 法條寫法：並列條文省略法規名（「民法第28條、第184條」）、中文數字條號（「第一百八十四條」，約 2015 年以前）、括號定義簡稱（「公平交易法（下稱修正前公平法）」）、「同法第N條」。`judgment_text.cited_statutes` 都已處理。
- 查證比對摘句時已忽略所有空白，從去換行版複製的摘句可直接通過。

### 環境

- Windows 主控台預設不是 UTF-8；印中文要設 `PYTHONIOENCODING=utf-8`。`python -I` 會忽略這個環境變數，改用 `-X utf8`。

---

## 五、使用者的偏好與決定

- **方向**：法條與判決只用網路＋快取，不擴充本地語料、不退回本地舊資料。
- **之後實跑在 Claude Code**：Codex 沙盒的問題（如找不到 `rg`）不處理；`scripts/rerun_role_separation.py` 不用跟著改。
- **文件**：中文；給組長看的文件用 Markdown，放在 `docs/zh/`。
- **commit**：只 commit 使用者指定的範圍，訊息用英文、祈使句、附說明段落，結尾加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。沒被要求就不要 push。
- **競賽**：2026-11-07 專題競賽，展示建議用錄製案例重播（不需網路）。階段三能否在競賽前完成要和使用者確認，不要為了趕時間略過測試。
- **待人工確認**：階段二評估裡「搜到的判決是否真的可用」尚未人工抽查（見評估報告第六節）。

---

## 六、新工作階段的建議開場

> 請讀 `docs/zh/retrieval-phase3-handoff.md`、`docs/zh/retrieval-optimization-plan.md` 第七節與 `docs/zh/retrieval-evaluation-phase2.md`，在 `retrieval-optimization` 分支上從步驟 1（快取、`judgment` 指令、查證改讀快取、無法檢索的處理）開始實作階段三。不要碰交接文件列出的使用者既有改動。

---

## 七、階段三未完成事項（2026-11-01 第二個工作階段結束時）

### 配合書狀交換架構的後續（依序）

1. `python main.py retrieval-rules --phase <階段>`：印出各階段的檢索步驟、預算與可用指令，組長的新範本只放 `{RETRIEVAL_RULES}`，內容由檢索這邊維護。
2. 介面文件 `docs/zh/retrieval-interface.md`：可用指令、三個佔位符（`{RETRIEVAL_RULES}`、`{SEARCH_LOG_PATH}`、`{RETRIEVAL_CACHE_DIR}`）、各階段規則與預算、紀錄檔命名、快照路徑、查證狀態值。
3. 組長的新範本出來後：範本加入佔位符、SKILL.md 寫明調度員怎麼建立快照與紀錄檔；之後以 v2 案例實跑驗收。現行 stage1～3 範本會被取代，先不改；下方「重跑腳本」的阻礙也隨之消失。
4. 規格第二期（被告模式）：查證與搜尋擴大到下級審判決，並解析上傳起訴狀裡的引用。

要和組長對齊：新框架的基準分支（規格寫 main，但 main 比本分支落後 54 個 commit）、P1 輸入改成檢索指令、§255 檢查改用書狀明確輸出的 `basis` 清單。

### 等引用設計（[citation-needs-redesign.md](citation-needs-redesign.md)）第七節定案

- **步驟 3 中「依什麼挑檢索目標」的寫法**：要寫成「核心主張的請求權基礎＋有爭議的要件」，需要核心／備位、`disputed` 等概念先定案；現行輸出格式沒有這些欄位。
- **`internal_notes.search_log` 的格式檢查**：屬於 `engine/role_protocol.py` 的驗證，定案前不改。
- **預算值是否依爭議要件數調整**：目前沿用階段二的固定值（Stage 1 搜尋 8、全文 10；Stage 2、3 各 4、5）。
- **步驟 5 Claude Code 實跑驗收**：以新格式實跑，與 10/31 紀錄比較才有意義。

### 步驟 3 的另一個阻礙：重跑腳本

`scripts/rerun_role_separation.py` 填範本時遇到未填的佔位符會直接報錯（「未填範本欄位」），`tests/test_rerun_role_separation.py` 也會複製正式範本跑一次。範本加入 `{SEARCH_LOG_PATH}`、`{RETRIEVAL_CACHE_DIR}` 後兩者都會失敗；這兩個檔案在「不要碰」清單上，需使用者決定：讓腳本補這兩個值、測試改用固定範本，或接受 Codex 重跑路徑失效。只刪除 `{STATUTES_DIR}`、`{JUDGMENTS_DIR}` 不會造成失敗（多給的值會被忽略）。

### 步驟 3 不受引用設計影響、可直接做的部分

- 刪除 `{STATUTES_DIR}`、`{JUDGMENTS_DIR}` 與「讀 {JUDGMENTS_DIR}」類指示，改寫成 `article`／`search-judgments`／`judgment` 指令。
- SKILL.md 寫明調度員如何建立快照資料夾與每個角色每輪的紀錄檔（例如 `<執行目錄>/retrieval_cache/`、`<執行目錄>/search_logs/plaintiff_stage1.jsonl`），並在 `record`、`verify` 傳 `--snapshot`。
- 立場檢索詞改為選用（SKILL.md「不能自行增刪」一句），`engine/stance_rag.py` 檔頭改為選用說明。
- 遇到 `retrieval_unavailable` 寫「待確認」，不以記憶充當查得結果。
- SKILL.md 第 8 步「連線失敗可由調度員手動重試一次並記錄；不改引擎加入自動重試」已與程式不符：查證引擎現在會自動重試一次，要一併改。
