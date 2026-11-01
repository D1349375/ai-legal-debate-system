# 檢索交接：階段三後續

> **交接日期**：2026-11-01（第二個工作階段結束）
> **分支**：`retrieval-optimization`（自 `role-separation-redesign` 分出）
> **這份文件給**：接手檢索後續工作的新工作階段
> **一句話**：底層已完成（快取、快照、`judgment` 指令、斷網處理、法條名稱索引、檢索紀錄與預算、資訊隔離）。接下來先做第四節「現在就能做」的 3 項，其餘要等組長的新框架或引用設計定案。

先讀這幾份，再動手：

1. 本文件。
2. [retrieval-optimization-plan.md](retrieval-optimization-plan.md) 第七節（第 0 項是檢索目標與引用設計的關係）。
3. [citation-needs-redesign.md](citation-needs-redesign.md)：使用者確認的引用設計討論稿。第七節的待確認事項還在等組長，定案前不改角色輸出格式。
4. 組長的《LegalDebate 書狀交換架構改版規格》v0.1：不在 repo，需要時向使用者索取檔案路徑。流程改成 P0～P6，檢索要做成和流程無關的服務接上去；檢索這邊的接法整理在 [retrieval-interface.md](retrieval-interface.md)。
5. [retrieval-evaluation-phase2.md](retrieval-evaluation-phase2.md)：預算值的依據（需要時再讀）。

---

## 一、背景：分工與現況

- **分工**：組長負責新框架（範本、SKILL 流程、資料表、`role_protocol` 驗證、律師確認關卡與續跑）；我們負責檢索（`engine/fjud.py`、`judgment_search.py`、`law_lookup.py`、`retrieval_cache.py`、`search_log.py`、`verify.py` 的檢索與查證部分、`main.py` 的檢索指令、各階段檢索規則的內容）。
- **雙方接點**只有四個：範本裡三個佔位符（`{RETRIEVAL_RULES}`、`{SEARCH_LOG_PATH}`、`{RETRIEVAL_CACHE_DIR}`）、快照與紀錄檔路徑、書狀輸出的 `basis` 清單（給 §255 檢查用）、`verify --snapshot` 的輸入與狀態值。
- **組長的分支**（2026-11-01 查 GitHub）：遠端只有 `main`、`ui-backend-integration`、`main-finals-fixes`、`role-separation-redesign`、`retrieval-optimization`。**沒有新框架的分支或 PR**。`main-finals-fixes` 與 `role-separation-redesign` 最新一筆都只是待修清單文件（`docs/zh/main-finals-fix-list.md`、`docs/zh/role-separation-fix-list.md`）。
- **還沒 push**：遠端 `retrieval-optimization` 停在 `18e19fc`，之後的 commit 都只在本機。使用者沒要求就不要 push；組長要以本分支為基準時才需要。

### 要和組長對齊、尚未有答覆的事

1. 新框架的基準分支：規格寫 main，但 main 比本分支落後 54 個 commit，職責分離與上網檢索都不在 main 上。建議以 `retrieval-optimization` 為基準。
2. 規格 P1 輸入寫「立場檢索詞、法規與判決語料庫」，要改成檢索指令（規則由 `{RETRIEVAL_RULES}` 提供），立場檢索詞改為選用。
3. 規格第 7.2 節的 §255 檢查要「比對 cited_statutes 中請求權基礎類條文」，建議改成書狀明確輸出 `basis` 清單。
4. `main-finals-fix-list.md` 的 M1、M3、M4、M5 在本分支已完成（以該清單的 V2、V3 實測通過），main 不要另外實作，否則併回來時 `verify.py` 大衝突。決賽若用 main 保底，可只移植 M1 的修法（進階搜尋的字號欄位）。
5. 狀態名稱：main 保留 `verification_failed`，本分支用 `network_error`，合併時要選一個（`role-separation-fix-list.md` C6）。

---

## 二、已完成的程式

### commit

| commit | 內容 |
|---|---|
| `18e19fc` | 階段一：`article`、`search-statutes`、`search-judgments`；修正判決查證兩個既有問題 |
| `abb9a0c` | 階段二：評估腳本與結果、評估報告、計畫、組長提案 |
| `a5ae6c7` | 定案「只用網路＋快取」、第一版交接文件 |
| `616edfa` | 引用設計討論稿 |
| `966fcbc` | 快取、`judgment` 指令、查證改讀快取、無法檢索的處理、法條名稱索引、檢索紀錄與預算、UI 查證改讀快取 |
| `2fa1c6b` | 計畫第七節第 0 項、交接進度 |
| `72c312a` | 配合書狀交換架構：快照依角色分開並以案件為單位、禁止 agent 直接讀快取與紀錄、預算認新階段名稱、`--issue`、判決常一起引用的法條 |
| `e7d3ff2` | 修正：字號有哪些文件不能靠長期快取判斷（同日多份文件會被誤當唯一） |

### 模組

| 模組 | 用途 |
|---|---|
| `engine/fjud.py` | 司法院裁判書查詢系統的連線與解析。`advanced_search`（可依字號欄位查）、`fetch_document`、`extract_full_text`；請求間隔 1.5 秒 |
| `engine/law_lookup.py` | 全國法規資料庫。`fetch_article`（空殼頁重查一次、連線失敗重試一次）、`lookup_article`（經快取）、`search_statutes`、`resolve_law`、`known_law_names`、`ALIASES`（簡稱表）、`with_retry` |
| `engine/retrieval_cache.py` | 長期快取與案件快照。`get_judgment`、`judgment_candidates`、`get_article`、`peek_*`、`store_judgment`、`snapshot_dirs`、`snapshot_manifest`、`cache_counts`；`RetrievalUnavailable`、`LiveFetchNotAllowed` |
| `engine/search_log.py` | 檢索紀錄與預算。`SearchLog`、`PHASES`、`phase_of`、`BudgetExceeded` |
| `engine/judgment_search.py` | `search-judgments` 核心；全文經快取取得；`statute_counts` |
| `engine/judgment_text.py` | 判決全文整理（`flatten`、`cited_statutes`、`summarize` 等） |
| `engine/verify.py` | 查證。`STATUTE_CITATION_RE` 改為依名稱索引找最長法規名稱的比對器（介面同正規式）；`verify_statute_citation`、`verify_judgment_citation`、`verify_precedent_note` 都經快取並接受 `snapshot` |
| `server/services.py` | UI 查證：不再讀 `corpus/statutes/*.txt`；過期條文快取或未確認唯一性的判決快取標 `local_cache_only`，不放行 |
| `server/live_run.py` | UI 實跑：環境變數 `LEGAL_DEBATE_RUN_SNAPSHOT` 指向案件快照根目錄；`DISALLOWED_TOOLS` 禁止 Read／Glob／Grep 讀快取、快照與紀錄 |

### 指令（`main.py`）

| 指令 | 說明 |
|---|---|
| `article 民法 184` | 查現行條文；7 天內讀快取，否則上網 |
| `search-statutes --kw 知有損害 [--law 民法]` | 依關鍵字搜條文 |
| `search-judgments --kw 民法第184條 --kw 相當因果關係 [--fetch 3]` | 搜最高法院民事判決；`--fetch` 抓全文並整理主文、實體法條、命中句，最後列出常一起引用的法條 |
| `judgment 111年度台上字第1069號 [--doc-date YYYYMMDD]` | 依字號或 JID 讀全文（去換行版）；同字號多份文件時要求日期 |
| `verify <引用...> [--snapshot <案件快照根目錄>]` | 查證；`record` 也接受 `--snapshot` |

檢索指令共用 `--snapshot <本角色快照資料夾>`、`--log <紀錄檔>`；`search-judgments`、`judgment` 另有 `--issue <爭點id>`。

### 做法上的決定（新工作階段不要推翻，除非使用者要求）

- **來源**：法條與判決只從官網取得、經快取，不擴充本地語料、不退回 `corpus/statutes/*.txt` 的舊版法典。`corpus/judgments/` 的 1,088 筆當唯讀預先內容。
- **快取**：判決以 JID 為鍵長期有效；條文以 pcode＋條號為鍵 7 天有效，過期重抓失敗不用舊版放行；搜尋結果列表不快取。
- **快照**：每個案件一份，依角色分子資料夾：`<根目錄>/plaintiff/`、`<根目錄>/defendant/`。角色的檢索指令只用明示的 `--snapshot`（不讀環境變數，因為環境變數指向雙方共用的根目錄）；查證與調度員以根目錄為 `--snapshot`，讀取涵蓋雙方。UI 實跑的根目錄是 `database/live_runs/case-<案件ID>/retrieval_cache/`，續跑沿用。
- **資訊隔離**：判決內容公開，但讀過哪些判決、搜過哪些詞會透露研究方向，所以快照與紀錄都分角色，且 UI 實跑禁止 agent 直接讀。同一個 Claude Code 程序的角色共用權限，只能全部禁止，角色之間仍靠 prompt 紀律。
- **字號 → JID**：只從預先內容、案件快照或官網確認，不靠長期快取（同字號甚至同一天可有多份，例如 115台上192 有 20260325 的序號 1、2）。同日多份的字號指定日期也是 `ambiguous`（既有規則）。
- **預算**：由指令依紀錄檔計數，超過就拒絕。階段由紀錄檔名判斷（不用設定檔，因為角色改得到）：`p1`／`complaint` 8 次搜尋／10 份全文、`p2`／`scenario`／`answer` 8／10（劇本與答辯狀共用一檔）、`p4`／`brief` 4／5、`p5`／`closing` 2／3、`stage1` 8／10、`stage2`／`stage3` 4／5，看不出階段時 4／5。搜尋只算 `search-judgments`；全文只算實際上網抓的判決，快取已有的、`article`、`search-statutes` 都不計。
- **紀錄檔路徑**：建議 `database/live_runs/case-<案件ID>/search_logs/<side>_<階段>.jsonl`（例如 `plaintiff_p1.jsonl`）。
- **重試**：所有官網連線失敗重試一次；仍失敗且快取沒有時，檢索指令回 `retrieval_unavailable`，查證回 `network_error`，訊息寫明「不代表查無資料」。
- **法條名稱**：名稱索引（`corpus/statutes/law_index.json`，11,804 部）裡的法規都能查證；取「第N條」前方最長的已知法規名；已廢止法規歸 `version_unverified`；索引外的名稱為 `unsupported_law`。

---

## 三、各階段的檢索規則（對應組長規格）

這是第四節第 1 項 `retrieval-rules` 指令要輸出的內容依據。

| 階段 | 角色 | 檢索 | 目標 | 預算 |
|---|---|---|---|---|
| P0 起訴前檢查 | 規則程式 | 不檢索 | — | — |
| P1 起訴狀 | 原告 | 主要檢索 | 起訴狀選定的請求權基礎（先位／備位），以及預想抗辯會打的要件；`internal_analysis` 裡的其他候選不上網搜 | 8／10 |
| P2a 劇本、P2b 答辯狀 | 被告 | 主要檢索 | 先依字號讀起訴狀引用的判決（快取已有不計預算）；再搜起訴狀的請求權基礎與抗辯（清償、抵銷、時效等） | 合計 8／10 |
| P3 爭點整理表 | 法官 | 不搜尋 | 可用 `judgment` 讀雙方已引用的判決 | — |
| P4 準備書狀 | 雙方 | 補充檢索 | 依爭點 id（`--issue`）；優先讀對方書狀引用的判決；有 §255 標記的新請求權基礎才可新搜 | 4／5 |
| P5 言詞辯論意旨狀 | 雙方 | 少量 | 只深化既有爭點，不新增請求權基礎 | 2／3 |
| P6 診斷 | 法官 | 不搜尋 | 同 P3；建議新增的請求權基礎只做存在性查證 | — |
| 獨立查證 | 查證角色 | 不搜尋 | 以案件快照根目錄比對 | — |

檢索步驟（雙軌制，2026-11-01 與使用者討論後定案）：

1. **Top-Down**：先依訴之聲明，按請求權基礎檢查順序列候選：契約 → 類似契約關係（締約上過失、無權代理）→ 無因管理 → 物上請求權 → 不當得利 → 侵權行為。這是為了不漏掉路徑、依邏輯先後檢查，不是「侵權當保底」；數個請求權可以競合。
2. 用 `article` 讀選定請求權基礎的現行條文。
3. **Bottom-Up**：用 `search-judgments` 以「法條＋要件詞」搜（例如 `--kw 民法第184條 --kw 相當因果關係`）。官網沒有相似案件搜尋與相關度排序，不用向量檢索。看「常一起引用的法條」檢查有沒有漏掉補充性法條。
4. 用 `judgment` 讀全文；正式引用規則不變（本輪讀過全文、附摘句與命題）。
5. 遇到 `retrieval_unavailable`：相關內容寫「待確認」，不得用記憶充當查得結果（記憶判例只能放 `precedent_leads`）。

只在這四種情況引用法條：涵攝要件、爭執舉證責任、發動或反擊法定抗辯、回應法官闡明或切換請求權基礎。只有涵攝或抗辯有爭議時才搜判決。

**法律說法要注意**（寫進規則或報告時不要寫錯）：

- 民訴第276條失權效針對未在準備程序提出的攻擊防禦方法（主要是新事實與新證據），法律見解不在此限；限制換請求權基礎的是第255條（基礎事實同一時不需被告同意）。P5「不新增請求權基礎」是系統為了收斂的設計，不能寫成「法律禁止引用新法條」。
- 法官切換法律關係的闡明是民訴第199條之1。
- 民法第197條時效完成的效果是債務人得拒絕給付（第144條），不是請求權消滅；借款返還是第125條 15 年。

**等引用設計定案的部分**：上表「目標」欄寫的是依組長規格推得的版本；若引用設計改成核心／備位與 `disputed` 要件，P1 的目標要改成「核心主張的請求權基礎＋有爭議的要件」。

---

## 四、下一個工作階段要做的事

### 現在就能做（依序）

**1. `python main.py retrieval-rules --phase <階段>`**

- 印出該階段的檢索規則：要不要檢索、目標、步驟、可用指令與參數、預算（讀 `engine/search_log.PHASES`，不要另外寫一份數字）、`retrieval_unavailable` 的處理。內容依第三節。
- 階段接受 `search_log.phase_of` 認得的名稱，加上 `p3`、`p6`、`verify`（印「不搜尋」與可用的 `judgment`／`verify`）。未知階段回錯誤並列出可用名稱。
- 組長的範本只放 `{RETRIEVAL_RULES}`，由調度員用這個指令的輸出填入；之後改規則只改這裡。
- 可加 `--side plaintiff|defendant --case-dir <路徑>`，把該角色的 `--snapshot` 與 `--log` 實際路徑一起印出，讓調度員直接貼。
- 寫測試：每個階段都有輸出、預算數字與 `PHASES` 一致、未知階段報錯。

**2. 介面文件 `docs/zh/retrieval-interface.md`**（給組長與其 agent）——**初版已寫（2026-11-01）**

- 內容：分工、角色可用指令與結束碼、三個佔位符與調度員要做的事、紀錄檔名與預算、快照與資訊隔離、`live_run.py` 要保留的兩處、查證狀態值、各階段規則、要新框架輸出的 `basis`、與 main 待修清單的重疊。
- 做完第 1、3 項後要同步更新：`retrieval-rules` 的實際參數與輸出、新狀態名稱（第七節「計畫中的新狀態」）。

**3. 官網頁面無法解析時回獨立狀態**（`role-separation-fix-list.md` A1 的附帶要求）

- 現在 `retrieval_cache.get_judgment` 對「頁面無法辨認全文」也拋 `RetrievalUnavailable`，查證回 `network_error`，會讓人以為是連線問題。
- 改成獨立狀態（例如 `full_text_unavailable`），訊息寫明「官網頁面無法辨認，不代表引用寫錯」。
- 要同步的地方：`engine/verify.py`、`server/services.py` 的 `STATUSES` 與 `verify_one`、`ui/app.js` 的 `STATUS` 標籤與統計、相關測試。`role_protocol` 的驗證不要改（非 published 照舊拒收）。

做完一項就跑相關測試；全部做完跑完整不連網測試，再請使用者決定是否 commit。

### 要等組長的新範本

4. 範本加入三個佔位符；立場檢索詞改為選用（`engine/stance_rag.py` 保留，檔頭改為選用說明）。
5. SKILL.md 寫明調度員怎麼建立案件快照、各角色子資料夾與紀錄檔，`record`、`verify` 傳案件快照根目錄；刪掉第 8 步「不改引擎加入自動重試」這句過時的說法。
6. Claude Code 實跑驗收（計畫第九節）：用新格式案例跑一次，與 10/31 紀錄比較檢索指令數、全文抓取數、耗時、`quote_not_found` 數（應為 0）、引用判決是否超出本地語料、紀錄是否完整、同一份判決是否只上網抓一次。

現行 `stage1～3` 範本會被新範本取代，先不改。原本的阻礙（`scripts/rerun_role_separation.py` 遇到未填佔位符會報錯，`tests/test_rerun_role_separation.py` 會複製正式範本跑）也隨之消失；若使用者決定仍要改現行範本，要先問怎麼處理這兩個檔案（都在「不要碰」清單）。

### 要等引用設計定案，或屬於使用者正在改的檔案

7. 每輪落地時遇到連線失敗或語料外判決，照常落地、只標「律師待核」（`role-separation-fix-list.md` B4）：要改 `role_protocol` 的驗證。
8. `internal_notes.search_log` 的格式檢查；預算是否依爭議要件數調整。
9. 連線失敗被當成查證結果錄下來（`role-separation-fix-list.md` A7）：程式在 `server/seed.py` 的 `collect_live_checks`，使用者正在改這個檔案（目前在修 A3），不要碰。

### 規格第二期（被告模式）

10. 查證與搜尋擴大到下級審判決（`fjud.advanced_search` 的 `court` 已是參數），並解析上傳起訴狀裡的引用。法條部分名稱索引已涵蓋。

### 不是程式，但要知道

- 階段二評估搜到的判決「是否真的可用」還沒人工抽查（評估報告第六節），建議實跑前請組員抽查。
- 民法有部分條文尚未施行（第 1223 條，2026-08-17 修正、公布六個月後施行），官網單條頁面顯示新條文，查證會當成現行條文放行。尚未處理。

---

## 五、不要碰的檔案

工作區有使用者自己未提交的改動，**不要 commit、不要修改、不要還原**：

- `demo/recorded_cases.json`
- `docs/LegalDebate_簡報素材_設計邏輯.md`
- `docs/zh/role-separation-execution.md`、`docs/zh/role-separation-verification.md`
- `scripts/rerun_role_separation.py`、`server/seed.py`、`tests/test_rerun_role_separation.py`
- `database/legal_debate.db.bak-before-002`
- `docs/live-run-records/role-separation-real-2026-10-31-002-redesign-20261031/`

commit 時一律用 `git add <明確檔名>`，不要用 `git add -A` 或 `git add .`。

---

## 六、測試

- 不連網：`python -m pytest -q -m "not network"`，約 5 分鐘。最近一次（`e7d3ff2`）**492 passed、2 skipped**。
- 兩項 skip 是 Claude Code 權限探針（`tests/test_claude_permissions.py`），要設 `LEGALDEBATE_PROBE_CLAUDE=1` 才跑；它用真的 Claude Code 搭配本機假 API，不用帳號額度，最近一次兩項都通過。
- 連網測試標記為 `network`，會實際打官方網站；改到 `fjud`、`law_lookup`、`verify` 時跑 `python -m pytest -q -m network tests/test_verify.py tests/test_fjud.py tests/test_law_lookup.py tests/test_judgment_search.py tests/test_citation_checks.py`（最近一次 11 項全過）。
- `tests/conftest.py` 把檢索快取改到每個測試的暫存目錄，並清掉快照環境變數；`seed_article` fixture 可放一筆條文快取。
- 手動試指令時請用暫存快取，不要寫進真的 `database/retrieval_cache/`：先設 `LEGAL_DEBATE_RETRIEVAL_CACHE=<暫存資料夾>`。

---

## 七、踩過的坑

### 官方網站

- **FJUD 簡易搜尋是全文搜尋**：拿字號去搜，回的是內文引用該字號的其他判決。查特定字號一定用進階搜尋的字號欄位（`fjud.advanced_search(citation=...)`）。
- **全文在巢狀的 `<div class="htmlcontent">`**：要依 div 層級取完整區塊（`fjud.extract_full_text`）。
- **只勾民事仍混入家事類 `TPSU`**：查證只認 `TPSV`，`search-judgments` 標為「不可引用」。
- **舊裁判的 JID 沒有尾端序號**：如 `TPSV,106,台上,1362,20170906`。
- **同字號多份文件**：111台上1069 有兩份不同日期；115台上192 有兩份同一天（序號 1、2）。
- **沒有相關度排序**；**總筆數不穩定**（相隔幾分鐘差 1～4%）；**請求間隔**至少 1.5 秒。
- **全國法規資料庫條號不存在時回空殼頁**（沒有「查無資料」字樣），存在的條文偶爾也回空殼頁，所以重查一次（`law_lookup.fetch_article`）。
- **已廢止法規的條文用 `text-pre` 排版**。
- **整合查詢只列「哪些法規含這個詞」**，順序不是相關度。

### 程式與工具

- **Claude Code 的 Read 被拒不列在 `permission_denials`**：工具結果回錯誤「File is in a directory that is denied by your permission settings」。Glob、Grep 被拒則會列在 `permission_denials`。
- **用 Bash heredoc 寫含 `\n` 的 Python 改檔腳本會出錯**：`\n` 被轉成真的換行、長內容也會讓 shell 解析失敗。改檔請用 Edit／Write 工具。
- **Windows 主控台預設不是 UTF-8**：印中文設 `PYTHONIOENCODING=utf-8`；`python -I` 會忽略這個變數，改用 `-X utf8`。
- **判決原文約每 30 字換行**：搜尋與比對前一律 `flatten`；查證比對摘句時已忽略所有空白。

---

## 八、使用者的偏好

- **回答用中文**；給組長看的文件用 Markdown，放 `docs/zh/`。
- **commit**：只 commit 使用者指定的範圍，訊息用英文、祈使句、附說明段落，結尾加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。沒被要求就不要 push。
- **之後實跑在 Claude Code**：Codex 沙盒的問題不處理。
- **競賽**：2026-11-07 專題競賽，展示用錄製案例重播（不需網路）。不要為了趕時間略過測試。
- **角色輸出格式**：引用設計第七節定案前，不改 `items`、`citations`、`precedent_notes` 的結構與 `role_protocol` 的驗證。
- **新框架由組長寫**：組長確認前不要自己開始實作新框架，避免兩邊同時改同一批檔案。

---

## 九、新工作階段的建議開場

> 請讀 `docs/zh/retrieval-phase3-handoff.md` 與 `docs/zh/retrieval-interface.md`，在 `retrieval-optimization` 分支上做交接文件第四節「現在就能做」的第 1、3 項：`retrieval-rules` 指令、官網頁面無法解析時的獨立狀態，做完後同步更新介面文件。不要碰第五節列出的使用者既有改動，不要改角色輸出格式與 `role_protocol` 的驗證，回答用中文。
