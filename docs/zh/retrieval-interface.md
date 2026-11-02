# 檢索介面說明（給新框架實作）

> **日期**：2026-11-01（2026-11-02 改在 `pleading-exchange` 維護）
> **對象**：實作《LegalDebate 書狀交換架構改版規格》（P0～P6）的組長與其 Claude Code agent
> **分支**：`pleading-exchange`。檢索的修改從 2026-11-02 起都在這條分支，不再開在 `retrieval-optimization`
> **目的**：說清楚檢索這邊負責哪些程式、提供什麼介面，新框架要怎麼接，避免兩邊改到同一批檔案

---

## 一、一句話

法條與判決只從官網（全國法規資料庫、司法院裁判書查詢系統）取得，經快取。檢索做成和流程無關的服務：**新框架只要在範本放三個佔位符、由調度員填入路徑，角色透過 `python main.py` 的檢索指令查資料**，不需要改檢索程式。

---

## 二、分工

| 新框架這邊（組長） | 檢索這邊（我們） |
|---|---|
| 新範本：起訴狀、答辯劇本、答辯狀、爭點整理表、準備書狀、意旨狀、診斷 | `engine/fjud.py`、`engine/law_lookup.py`、`engine/retrieval_cache.py`、`engine/search_log.py`、`engine/judgment_search.py`、`engine/judgment_text.py` |
| SKILL.md 的流程、確認關卡、調度員規則 | `engine/verify.py` 的檢索與查證部分（`parse_citation`、`citation_warning`、`verify_*`） |
| 資料表、`database/db.py`、`engine/role_protocol.py` 的驗證 | `main.py` 的檢索指令：`article`、`search-statutes`、`search-judgments`、`judgment`、`retrieval-rules`，以及 `verify`／`record` 的 `--snapshot` |
| `server/live_run.py` 的關卡暫停與續跑、UI | `server/live_run.py` 的兩處（環境變數 `LEGAL_DEBATE_RUN_SNAPSHOT`、`DISALLOWED_TOOLS` 的檢索規則），見第六節 |
| 起訴前檢查（P0）的規則程式 | 各階段的檢索規則內容（`retrieval-rules` 指令輸出） |

**請不要直接改檢索這邊的檔案**；需要新介面或行為時告訴我們。`server/live_run.py` 雙方都會改，請保留第六節列的兩處。

---

## 三、角色可用的指令

所有指令從專案根目錄執行，UI 實跑的角色本來就允許 `python main.py *`。WebFetch、WebSearch 維持禁用，角色上網只能透過這些指令。

| 指令 | 用途 | 成功 | 失敗 |
|---|---|---|---|
| `python main.py article 民法 184` | 讀現行條文（也接受「民法第191條之2」）；7 天內讀快取，否則上網 | 結束碼 0 | 1：`not_found`、`unrecognized_page`、`retrieval_unavailable`；2：法規名稱或條號格式錯 |
| `python main.py search-statutes --kw 知有損害 [--law 民法]` | 依關鍵字找條文 | 0 | 1：`retrieval_unavailable`；2：參數錯或法規名稱不明 |
| `python main.py search-judgments --kw 民法第184條 --kw 相當因果關係 [--fetch 3] [--title 損害賠償]` | 搜最高法院民事判決（多個 `--kw` 皆須命中）；`--fetch` 抓全文並列出主文、實體法條、命中句，最後列「常一起引用的法條」 | 0 | 1：`retrieval_unavailable`、`budget_exceeded`；2：參數錯 |
| `python main.py judgment 111年度台上字第1069號 [--doc-date YYYYMMDD]` | 依字號或 JID 讀判決全文（去換行版）；正式引用前「讀過全文」靠這個指令。民國85年以前的裁判沒有全文，有 `--log` 時改列援引它的近年判決（見第十三節） | 0 | 1：`not_found`、`retrieval_unavailable`、`full_text_unavailable`、`budget_exceeded`、`excluded`；2：同字號多份文件需指定日期（`ambiguous`）或格式錯 |
| `python main.py retrieval-rules --phase p1 [--side plaintiff --case-dir <案件資料夾>] [--json]` | 印出該階段的檢索規則，給調度員填 `{RETRIEVAL_RULES}`；調度員用，角色不用。見第四節 | 0 | 2：未知階段（訊息列出可用名稱）、角色與階段不符、給 `--case-dir` 沒給 `--side` |

檢索指令共用參數：

- `--snapshot <本角色的快照資料夾>`：見第五節。
- `--log <本角色本階段的紀錄檔>`：記錄每次查詢，並依檔名判斷階段、計算預算。
- `--issue <爭點id>`（`search-judgments`、`judgment`）：記下這次查詢針對哪個爭點，P4、P5 使用。
- `--exclude <字號或 JID>`（`search-judgments`、`judgment`，可重複）：不提供給角色的裁判，用於示範案改編自真實判決時排除來源裁判。同字號的每一份文件都排除（不分日期）；`search-judgments` 從列表拿掉、不抓全文，`judgment` 在查任何來源前就回 `excluded`。值無法解析成字號或 JID 時結束碼 2。
- `--json`：結構化輸出。

失敗訊息一律寫明原因，訊息開頭就是狀態名稱：

- `retrieval_unavailable`：官網連線失敗（已自動重試一次），註明「不代表查無資料」。
- `full_text_unavailable`：連上官網但頁面無法辨認裁判全文（頁面改版或回空頁），註明「不代表引用寫錯或查無資料」。`search-judgments --fetch` 遇到時不中斷，該筆的「全文」欄寫這個狀態，其他筆照常。

角色遇到這兩種時，相關內容寫「待確認」，不得用記憶充當查得結果（記憶中的判決只能放 `precedent_leads`）；沒讀到全文的判決不得正式引用。

---

## 四、範本與調度員要做的事

### 範本的三個佔位符

需要檢索的範本（起訴狀、答辯劇本、答辯狀、準備書狀、言詞辯論意旨狀）放：

| 佔位符 | 填入 | 範例 |
|---|---|---|
| `{RETRIEVAL_RULES}` | `retrieval-rules` 指令的輸出 | （該階段的檢索步驟、預算、可用指令） |
| `{RETRIEVAL_CACHE_DIR}` | 本角色的快照子資料夾 | `database/live_runs/case-<案件ID>/retrieval_cache/plaintiff` |
| `{SEARCH_LOG_PATH}` | 本角色本階段的紀錄檔 | `database/live_runs/case-<案件ID>/search_logs/plaintiff_p1.jsonl` |

範本裡寫：檢索指令一律加 `--snapshot {RETRIEVAL_CACHE_DIR} --log {SEARCH_LOG_PATH}`，規則依 `{RETRIEVAL_RULES}`。

**不要再給**：`{STATUTES_DIR}`、`{JUDGMENTS_DIR}` 或任何「讀本地語料資料夾」的指示。立場檢索詞（`engine/stance_rag.py`）改為選用，不要寫成「不能自行增刪」。規格 P1 的輸入「立場檢索詞、法規與判決語料庫」請改成「檢索指令」。

不檢索的範本（爭點整理表、診斷、獨立查證）不放 `--log`。法官需要看雙方已引用的判決時，用 `python main.py judgment <字號>`（不加 `--snapshot`），不得用 `search-judgments`。

### `retrieval-rules` 指令

調度員組 prompt 時呼叫，把輸出填進 `{RETRIEVAL_RULES}`；規則要改時只改 `engine/retrieval_rules.py`，範本不用動。

```bash
python main.py retrieval-rules --phase p2 --side defendant --case-dir database/live_runs/case-7 --json
```

| 參數 | 說明 |
|---|---|
| `--phase`（必填） | 檢索階段 `p1`、`p2`、`p4`、`p5`，或別名 `complaint`、`scenario`、`answer`、`brief`、`closing`；不檢索的 `p3`、`p6`、`verify`；現行三輪 `stage1`～`stage3`（相容用）。和紀錄檔名認得的名稱相同 |
| `--side` | `plaintiff` 或 `defendant`。`p1` 只能是原告、`p2` 只能是被告，給錯回結束碼 2（避免把對造的路徑給錯角色） |
| `--case-dir` | 案件資料夾。檢索階段要和 `--side` 一起給，輸出會帶入該角色的實際路徑；沒給時規則裡的路徑寫成 `<快照資料夾>`、`<紀錄檔>` |
| `--exclude` | 示範案的來源裁判（字號或 JID，可重複）。規則裡每個 `search-judgments`、`judgment` 指令都會帶 `--exclude <字號>`（角色與法官階段；獨立查證不帶，角色若憑記憶引用了來源裁判，查證仍要能查）。規則不說明排除的原因，免得提示搜尋方向 |
| `--json` | 結構化輸出，欄位見下 |

`--json` 的欄位：

| 欄位 | 內容 | 填哪個佔位符 |
|---|---|---|
| `text` | 規則全文（與不加 `--json` 時印出的相同） | `{RETRIEVAL_RULES}` |
| `snapshot` | `<案件資料夾>/retrieval_cache/<side>`（有給 `--side`、`--case-dir` 的檢索階段才有） | `{RETRIEVAL_CACHE_DIR}` |
| `log` | `<案件資料夾>/search_logs/<side>_<階段代碼>.jsonl`；別名一律換成代碼，所以 `scenario` 和 `answer` 都是 `defendant_p2.jsonl`（劇本與答辯狀共用預算） | `{SEARCH_LOG_PATH}` |
| `case_snapshot` | `<案件資料夾>/retrieval_cache`（有給 `--case-dir` 就有） | `record`、`verify` 的 `--snapshot` |
| `exclude` | 排除的裁判，已統一寫成 `111年度台上字第1069號` 的格式；獨立查證為空陣列 | — |
| `phase`、`label` | 階段代碼與名稱，例如 `p2`、`P2 答辯劇本與答辯狀` | — |
| `searches`、`budget` | 是否檢索；預算 `{"searches": 8, "fetches": 10}`，不檢索的階段為 `null`。數字直接讀 `engine/search_log.PHASES`，和指令實際執行的預算相同 | — |

規則全文的內容：檢索方式、預算、目標、步驟、可用指令與參數（含實際路徑）、什麼時候引用、檢索失敗時（`retrieval_unavailable`、`full_text_unavailable`、`budget_exceeded`、`ambiguous`）怎麼處理、禁止事項。不含大括號，填進範本後再對範本做 `str.format` 也不會出錯。各階段的規則見第八節。

**排除來源裁判的限制**（實跑示範案前要知道）：

1. `--exclude` 是角色照抄規則裡的指令帶上的，角色漏帶時不會排除。指令沒有另一個角色改不到的地方可以放排除清單（角色對 `database/live_runs/**` 有寫入權限，環境變數也能在指令前覆寫），所以實跑後請檢查紀錄檔每筆 `search-judgments` 的 `query.exclude`。
2. 只排除指定字號。同一個紛爭在最高法院的其他裁判（例如先前發回的判決，字號不同）要另外列；之後引用來源裁判的其他判決不會被排除。
3. 來源裁判若在 `corpus/judgments/`（1,088 筆預先內容），UI 實跑的 agent 目前可以用 Read、Grep 直接讀到：`DISALLOWED_TOOLS` 沒有禁止這個資料夾。要不要加禁止規則見第六節。

### 紀錄檔的檔名決定預算

格式 `<side>_<階段>.jsonl`。指令依檔名的階段計數，超過就拒絕：

| 階段名稱（任一） | 對應 | 搜尋次數 | 上網抓全文 |
|---|---|---:|---:|
| `p1`、`complaint` | P1 起訴狀 | 8 | 10 |
| `p2`、`scenario`、`answer` | P2a 劇本＋P2b 答辯狀（**共用一個檔**） | 8 | 10 |
| `p4`、`brief` | P4 準備書狀 | 4 | 5 |
| `p5`、`closing` | P5 言詞辯論意旨狀 | 2 | 3 |
| `stage1`／`stage2`／`stage3` | 現行三輪（相容用） | 8／4／4 | 10／5／5 |
| 看不出階段 | — | 4 | 5 |

搜尋只算 `search-judgments`；全文只算實際上網抓的判決，快照或快取已有的不計，`article`、`search-statutes` 只記錄不計。預算放在檔名而不是設定檔，因為角色對 `database/live_runs/**` 有寫入權限，設定檔改得到。

### 調度員（SKILL.md）要寫的

1. 每個案件建立 `database/live_runs/case-<案件ID>/`，底下 `retrieval_cache/plaintiff/`、`retrieval_cache/defendant/`、`search_logs/`（不存在時指令會自己建，路徑對就好）。**律師確認關卡續跑時沿用同一個案件資料夾**。
2. 給每個角色填它自己的 `{RETRIEVAL_CACHE_DIR}`、`{SEARCH_LOG_PATH}`；**不得把對造的快照或紀錄路徑給角色**。三個佔位符可以一次從 `retrieval-rules --phase <階段> --side <side> --case-dir <案件資料夾> --json` 的 `text`、`snapshot`、`log` 取得。
3. `python main.py record ... --snapshot database/live_runs/case-<案件ID>/retrieval_cache`、`python main.py verify ... --snapshot <同上>`：用案件快照根目錄（查證與判例落地讀雙方讀過的同一版本）。UI 實跑時環境變數已指向根目錄，可省略；Claude Code 直接跑（非 UI）時要明寫。查某一方書狀的引用時，`verify` 加 `--read-by plaintiff` 或 `--read-by defendant`（見第七節 `not_read_by_side`）。
4. SKILL.md 現行第 8 步「連線失敗可由調度員手動重試一次；不改引擎加入自動重試」請刪掉：引擎現在自動重試一次。

---

## 五、快照、快取與資訊隔離

| 位置 | 內容 | 誰讀寫 |
|---|---|---|
| `database/retrieval_cache/` | 長期快取（跨案件）：判決全文以 JID 為鍵長期有效；條文以 pcode＋條號為鍵 7 天有效。不進 git | 檢索指令與查證引擎（Python） |
| `corpus/judgments/` | 1,088 筆最高法院判決，唯讀預先內容，查找時視為快取 | 同上 |
| `database/live_runs/case-<案件ID>/retrieval_cache/<side>/` | 案件快照：該角色用到的每份判決與條文的副本、來源、抓取時間、雜湊；字號對照也存在這裡 | 該角色的檢索指令寫；查證以根目錄讀雙方 |
| `database/live_runs/case-<案件ID>/search_logs/` | 各角色各階段的檢索紀錄（JSON Lines） | 檢索指令寫 |

- **查找順序**：判決是快照 → 長期快取 → 預先內容 → 上網；條文是快照（7 天內）→ 長期快取（7 天內）→ 上網。上網抓到的寫回長期快取與快照。
- **為什麼依角色分開**：判決內容是公開資料，但讀過哪些判決、搜過哪些詞會透露研究方向。規格 P2 要求被告看不到原告的內部分析，所以快照與紀錄都分角色。
- **為什麼以案件為單位**：確認關卡會把一個案件分成多次執行，最後的獨立查證要比對前面讀過的同一份全文；事後重播也不需網路。
- **角色只能透過指令讀**：UI 實跑禁止 agent 用 Read／Glob／Grep 直接讀上面這些資料夾（第六節），指令以 Python 讀檔不受影響。

---

## 六、`server/live_run.py` 請保留的兩處

組長改關卡暫停與續跑時，這兩處請保留（或搬到新位置但行為不變）：

1. **環境變數**：啟動 Claude Code 前 `env[SNAPSHOT_ENV] = os.path.join(self.case_dir(case_id), "retrieval_cache")`。`case_dir` 是 `database/live_runs/case-<案件ID>`。續跑的新執行也要給同一個值。
2. **禁止直接讀**：`DISALLOWED_TOOLS` 裡的 `Read(/database/retrieval_cache/**)`、`Read(/database/live_runs/*/retrieval_cache/**)`、`Read(/database/live_runs/*/search_logs/**)`。已用真的 Claude Code 驗證生效（`tests/test_claude_permissions.py`，設 `LEGALDEBATE_PROBE_CLAUDE=1` 執行）。若改了案件資料夾的位置，這三條規則要跟著改。

`tests/test_live_run.py` 有對應的測試（續跑沿用同一份快照、禁止規則存在）。

**待決定**：實跑示範案時，若來源裁判在 `corpus/judgments/`，可在 `DISALLOWED_TOOLS` 加 `Read(/corpus/judgments/**)`、`Grep(/corpus/judgments/**)`、`Glob(/corpus/judgments/**)`。指令以 Python 讀檔不受影響，所以角色照樣能用 `judgment` 讀預先內容；代價是角色不能再直接瀏覽語料。這是 `live_run.py`，由組長決定是否加。

---

## 七、查證介面

`python main.py verify <引用...> [--case-id X] [--snapshot <案件快照根目錄>] [--read-by plaintiff|defendant] [--precedent-notes ...] [--version-hints ...] [--review-json ...]`，用法與現行相同，多了 `--snapshot` 與 `--read-by`。

`--read-by`（2026-11-02 加）：查某一方書狀的引用時給該方。該方角色在本案沒有用 `judgment` 讀過全文的判決回 `not_read_by_side`，不放行。`judgment` 讀成功時在該方快照記一筆 `reads/<JID>.json`；`search-judgments --fetch` 也會把全文存進快照，但角色只看到主文與命中句，不算讀過。須搭配案件快照根目錄（`--snapshot` 或環境變數），沒有時結束碼 2。不給 `--read-by` 時行為不變（法官、種子資料、UI 查證照舊）。Python 呼叫端：`verify_citations(..., read_by='plaintiff')`、`validate_precedent_notes(..., read_by=...)`。

### 法條解析

- 名稱索引（`corpus/statutes/law_index.json`，11,804 部）裡的法規都能查證，不再只有 11 部。
- 取「第N條」前方最長的已知法規名（「依土地法第34條」→ 土地法；「民法債編施行法第10條之1」不會被切成民法）。
- 簡稱：刑法、勞基法、消保法、個資法、民訴法、刑訴法、公平法、證交法、國賠法、勞退條例、強執法、家事法、公寓大廈條例、消債條例、道交條例。
- `engine.verify.STATUTE_CITATION_RE` 已不是正規式，而是同介面的比對器（`search`、`finditer`，比對結果有 `group(0)`、`start()`、`end()`、`span()`，另有 `law_name`、`article_no`）。用 `group(1)`、`group(2)` 會報錯。

### 狀態值

| 狀態 | 意思 | 放行 |
|---|---|---|
| `published` | 官方比對通過；`verified_via` 註明來源：`law_moj_live`、`fjud_live`、`retrieval_cache`、`run_snapshot`、`local_corpus`，快取另附 `fetched_at` | 是 |
| `needs_explanation` | 判例案由不同但有類推理由，交獨立查證 | 依現行規則 |
| `not_found` | 官方明確查無 | 否 |
| `network_error` | 官網無法連線且無有效快取（已重試一次），**不代表查無** | 否 |
| `full_text_unavailable` | 連上官網但頁面無法辨認條文或裁判全文，未能比對文種與摘句；**不代表查無，也不代表引用寫錯** | 否 |
| `ambiguous` | 同字號多份文件，須以 `doc_date` 指定；同一天多份（如 115台上192）指定日期仍是 ambiguous | 否 |
| `version_unverified` | 歷史版本，或法規已廢止 | 否（律師待核） |
| `unsupported_law` | 名稱索引查無此法規 | 否（律師待核） |
| `unparseable` | 不是可解析的法條或字號 | 否 |
| `not_read_by_side` | 有給 `--read-by`：字號（與摘句）查核通過，但引用方在本案沒有用 `judgment` 讀過全文 | 否 |
| `doc_type_mismatch`、`quote_not_found`、`document_identity_unverified`、`analogy_required`、`invalid_precedent_note`、`invalid_document_date` | 判例文件身分或摘句檢查失敗（既有規則不變） | 否 |

UI 端（`server/services.py`）另有 `local_cache_only`（只有過期條文快取，或判決快取有但官方未確認唯一性）與 `verification_failed`，都不放行。`full_text_unavailable` 在 UI 也照原樣顯示，`live_attempt.outcome` 為 `unrecognized_page`（連得上官網，所以不會觸發批次查證的「網路不通、其餘略過即時查詢」）；案件查證紀錄是這個狀態時，書狀編輯會重新查證。

**`full_text_unavailable` 的由來**（`role-separation-fix-list.md` A1）：以前頁面無法辨認也回 `network_error`，會被誤當成連線問題；更早的版本則落到 `doc_type_mismatch`、`quote_not_found`，讓人以為引用寫錯。`engine/role_protocol.py` 的驗證沒有改：非 `published` 照舊拒收。消費端若有自己的狀態清單，請加上這個值；獨立查證的 `checks[].status` 也接受它（`engine/citation_review.py`）。

**狀態名稱分歧要先決定**：main 的待修清單規定保留 `verification_failed`，本分支引擎用 `network_error`。新框架合併時請選一個，消費端一起對齊。

---

## 八、各階段的檢索規則（`retrieval-rules` 的內容）

下表是摘要，實際文字以 `python main.py retrieval-rules --phase <階段>` 的輸出為準（程式在 `engine/retrieval_rules.py`）。

| 階段 | 角色 | 檢索 | 目標 |
|---|---|---|---|
| P0 | 規則程式 | 不檢索 | 時效提示若要顯示條文，可呼叫 `article` |
| P1 起訴狀 | 原告 | 主要檢索 | 準備在起訴狀主張的請求權基礎（先位／備位），以及預想抗辯會打的要件。不打算主張的候選只讀條文、不搜判決。分析與撰狀共用 `plaintiff_p1.jsonl` 與預算 |
| P2a、P2b | 被告 | 主要檢索 | 先依字號讀起訴狀引用的判決，再搜起訴狀的請求權基礎與抗辯 |
| P3、P6 | 法官 | 不搜尋 | 可用 `judgment` 讀雙方已引用的判決；P6 建議新增的請求權基礎只做存在性查證 |
| P4 準備書狀 | 雙方 | 補充檢索 | 依爭點 id；優先讀對方書狀引用的判決；有 §255 標記的新請求權基礎才可新搜 |
| P5 意旨狀 | 雙方 | 少量 | 只深化既有爭點，不新增請求權基礎 |
| 獨立查證 | 查證角色 | 不搜尋 | 以案件快照根目錄比對 |

檢索步驟：依訴之聲明，按「契約 → 類似契約關係 → 無因管理 → 物上請求權 → 不當得利 → 侵權行為」列候選 → `article` 讀條文 → `search-judgments` 用法條＋要件詞搜 → `judgment` 讀全文 → 正式引用規則不變（本輪讀過全文、附摘句與命題）。只有涵攝要件或抗辯有爭議時才搜判決。

**寫範本時的法律用語提醒**：

- 民訴第276條失權效針對未在準備程序提出的攻擊防禦方法（主要是新事實與新證據），法律見解不在此限；限制換請求權基礎的是第255條。P5「不新增請求權基礎」是系統為了收斂的設計，不要寫成「法律禁止引用新法條」。
- 法官切換法律關係的闡明是第199條之1。
- 民法第197條是侵權行為的 2 年時效，時效完成的效果是得拒絕給付（第144條）；借款返還適用第125條 15 年。

---

## 九、要新框架這邊配合的輸出欄位

- **`basis`（請求權基礎清單）**：起訴狀與準備書狀明確輸出，例如 `"basis": ["民法第478條", "民法第179條"]`。規格第 7.2 節的 §255 檢查請比對前後兩份 `basis`，不要從 `cited_statutes` 猜哪條是請求權基礎（從法條清單判斷並不可靠）。
- **正式引用的判決**照現行 `precedent_notes`（`citation`、`doc_date`、`doc_type`、`case_cause`、`quote`、`proposition`、`analogy_reason`），查證引擎不變。若新框架改成判決掛在要件下（見 `docs/zh/citation-needs-redesign.md`），請先和我們對齊欄位，查證要跟著改。

---

## 十、已知限制與第二期

- 只查最高法院民事判決（JID 前綴 `TPSV`）。被告模式上傳的真實起訴狀常引用地方法院、高等法院判決，目前會顯示無法查證、不會被誤放行；第二期再擴大。
- 民法部分條文尚未施行（第 1223 條）時，官網顯示新條文，查證會當成現行條文放行。
- 官網沒有相關度排序；依日期排序時，舊的重要判決可能在後面，靠法條＋要件詞縮小範圍。

---

## 十一、與 main 決賽待修清單的重疊

`docs/zh/main-finals-fix-list.md`（`main-finals-fixes` 分支）的 M1、M3、M4、M5 在本分支已完成，並以該清單的 V2、V3 實測通過：

| 待修 | 本分支 |
|---|---|
| M1 FJUD 只讀第一頁 | 改用進階搜尋的字號欄位，一次命中、不用翻頁。105台簡上33 → `published`，JID `TPSV,105,台簡上,33,20161026`；105台上99999 → `not_found` |
| M3 法規白名單 | 改用名稱索引，銀行法第29條可查證 |
| M4 舊版條文 | `version_unverified` |
| M5 同字號多份 | `ambiguous`，附 `candidates` |

main 若另外實作，併回來時 `verify.py` 會大衝突。決賽若用 main 保底，建議只移植 M1 的修法（`engine/fjud.py` 的 `advanced_search(citation=...)` 與 `engine/verify.py` 的 `_fjud_search`）。

---

## 十二、搬到新架構分支（`pleading-exchange`）要帶的檔案

**現況（2026-11-02）**：組長在 `7ae2d9d` 以 `e8404f7` 的版本搬入；`retrieval-rules`（`6d39769`）與 `--exclude`（`0fa742c`）之後補進，檢索負責的檔案已與 `retrieval-optimization` 的 `0fa742c` 相同。`6d39769` 裡 `server/services.py`、`ui/app.js` 顯示 `full_text_unavailable` 的部分沒有帶，由組長決定（沒帶時這個狀態仍不放行，只是畫面顯示原始狀態名、即時查詢結果顯示「成功」）。

新架構若從 main 開分支，檢索這邊以 `retrieval-optimization` 的版本整份帶過去（2026-11-01 核對：main 是本分支的祖先，main 上沒有本分支以外的新 commit）。以下檔案之後仍由檢索這邊維護。

**整份複製，main 上沒有、不會衝突**：

- `engine/fjud.py`、`engine/law_lookup.py`、`engine/retrieval_cache.py`、`engine/search_log.py`、`engine/judgment_search.py`、`engine/judgment_text.py`、`engine/retrieval_rules.py`
- `corpus/statutes/law_index.json`、`scripts/build_law_index.py`
- 測試：`tests/test_fjud.py`、`test_law_lookup.py`、`test_retrieval_cache.py`、`test_search_log.py`、`test_judgment_search.py`、`test_judgment_text.py`、`test_retrieval_rules.py`，以及 `tests/fixtures/fjud/`、`tests/fixtures/law/`

**整份取代 main 的版本**：

- `engine/verify.py`：只依賴上面的 `fjud`、`retrieval_cache`、`law_lookup`，不依賴職責分離的程式。main 上的呼叫端（`database/db.py`、`main.py`、`server/app.py`、`server/seed.py`、`server/services.py`）用到的 `parse_citation`、`verify_citations(texts, timeout)`、`JUDGMENTS_DIR`、`STATUTES_DIR`、`STATUTE_PCODES`、兩個字號比對器的 `finditer`／`group(0)`／`start()` 都相容。M1、M3、M4、M5 的修法都在這個檔案，只搬檢索指令不搬它，查證就會退回 main 的舊行為。
- `tests/conftest.py`：要帶它的兩個 fixture（每個測試把檢索快取改到暫存目錄並清掉快照環境變數的 autouse fixture，以及 `seed_article`），否則測試會寫進真的 `database/retrieval_cache/`。

**要合併、不能整份覆蓋**（main 與本分支都改過）：

- `main.py`：`article`、`search-statutes`、`search-judgments`、`judgment`、`retrieval-rules` 五個指令與 `_snapshot`、`_search_log`、`SOURCE_LABEL`、`_source_line`、`_iso`、`_retrieval_options`；`verify`、`record` 的 `--snapshot` 與 `main()` 結尾設定 `SNAPSHOT_ENV` 的那段。`cmd_judgment` 用到的 `verify._document_type` 在新的 `verify.py` 裡。
- `server/live_run.py`：第六節的兩處。
- `server/services.py`：`verify_one` 與 `_live_query` 那一段（改讀檢索快取、不再讀 `corpus/statutes/*.txt`、`full_text_unavailable`）。不搬的話，UI 查證仍用 main 的舊法典快取。
- `ui/app.js`：`STATUS`、`LIVE_OUTCOME` 的新標籤與查證統計。

**不用帶**：`engine/citation_review.py`、`engine/role_protocol.py` 是職責分離的程式，main 上沒有；本分支在 `citation_review.py` 只加了一個允許的狀態值。

## 十三、W2 起訴狀 v1 的接法注意事項（2026-11-02 檢查）

拿《改版規格》5.2、5.9 與計畫 W2 對照本文件與現行程式的結果。只讀文件與程式、跑離線測試，沒有跑 Claude。

### 要在 W2 處理（組長決定）

| # | 問題 | 建議 |
|---|---|---|
| 1 | `stage1_prompt.txt` 不只是換佔位符。第 23–38 行允許把記憶中、未命中的判例列進 `cited_precedents`（只在 argument 註明待查證），與第三節、第八節的引用規則衝突；輸出也沒有 `precedent_notes`、`precedent_leads` | 改寫這段：正式引用的判決須本輪用 `judgment` 讀過全文並附 `precedent_notes`，記憶中的判決只進 `precedent_leads`（規格 5.2 也這樣寫）。可參考 `retrieval-optimization` 的 `stage1_prompt.txt` 第 16 行 |
| 2 | 撰狀 subagent（`complaint_prompt.txt`）能不能檢索，規格沒寫。它輸出的 `precedent_notes.quote` 必須是全文原句 | 建議撰狀不搜尋，只引用分析已讀過、已附 `precedent_notes` 的判決；要重讀時用 `judgment` 加同一個快照與 `plaintiff_p1.jsonl`（快照已有的不計預算）。給它 `{RETRIEVAL_RULES}` 時用同一個 P1 規則 |
| 3 | W2 實跑用商工解散案，來源是最高法院114年度台上字第1987號裁定，該裁定在 `corpus/judgments/`。計畫把排除參數放到 W8，W2 的實跑檢查沒有防污染 | W2 起就用 `retrieval-rules --phase p1 --side plaintiff --case-dir <案件資料夾> --exclude 114年度台上字第1987號`；跑完檢查 `plaintiff_p1.jsonl` 每筆 `search-judgments` 的 `query.exclude`，以及有沒有任何一筆讀到 1987 號 |
| 4 | 「正式引用的判決須讀過全文」原本只寫在規則裡，查證不核對：沒讀過的判決 `verify` 會自己上網抓全文比對摘句，照樣 `published`；摘句也可能取自 `search-judgments` 的命中句（可能是當事人主張，不是法院見解） | 書狀撰狀後的查證加 `--read-by <該書狀的一方>`，例如起訴狀：`verify --precedent-notes <檔> --snapshot <案件快照根目錄> --read-by plaintiff`；`not_read_by_side` 和其他非 `published` 一樣退回撰狀。角色的 `judgment` 一定要帶自己的 `--snapshot`（`{RETRIEVAL_CACHE_DIR}`），否則讀過也不會記錄 |

### SKILL.md 改寫時要一起換的

- 第 47 行仍給 `{STATUTES_DIR}`、`{JUDGMENTS_DIR}`，換成第四節的三個佔位符。
- 加上：建立 `database/live_runs/case-<案件ID>/`、呼叫 `retrieval-rules` 取得規則與路徑、只給每個角色自己的路徑、`verify` 用案件快照根目錄。
- 放行條件寫「只有 `published` 放行」，不要列舉不放行的狀態；規格 5.2 的列舉沒有 `full_text_unavailable`。
- 用 CLI 直接跑 `python main.py case data/cases/test-2026-10-27-gcis-001.json` 時，主 agent 會讀到原檔的 `source_note`（寫明來源裁判字號）。UI 實跑的 `case.json` 由資料庫產生，不含這個欄位。

### 檢索這邊已處理

- **舊判例（民國85年以前）**：官網只有掃描檔，關鍵字搜不到、`judgment` 讀不到全文，但最高法院「意旨參照」最常引的就是它們（2026-11-02 抽 15 則全是）。以判例字號當關鍵字，都搜得到援引它、幾乎逐字重述要旨的近年判決（15 則各 7～54 份）。因此：
  - `retrieval-rules` 的引用規則加一條：要用舊判例的見解時，用 `search-judgments --kw <判例字號>` 找援引它的近年判決，讀全文後引用近年判決；舊判例字號只放 `precedent_leads`。
  - `judgment` 認得沒有「度」的判例寫法（`73年台上字第1173號`）。讀到民國85年以前的裁判時仍回 `full_text_unavailable`（結束碼 1），有 `--log` 時另自動查一次援引它的近年判決並列出前 5 份（計一次搜尋，紀錄 `note: citing_lookup`）；沒有 `--log`（法官、查證）只印提示，不替它們搜尋。
  - `verify` 不變：判例寫法仍是 `unparseable`、不放行，與「舊判例不能正式引用」一致。民國38年以前的「上字」判例（如 `17年上字第1118號`）兩邊都不認得。
- **官網忙碌時不再誤報查無**：2026-11-02 重測時官網忙碌，存在的 52台上694、44台上75、71台上737、70台上311 曾被回成 `not_found`（`verify` 會因此把真的引用判成捏造）。原因是送出查詢後的回應頁、或結果頁本身是忙碌頁，程式讀不到結果連結或列就當成 0 筆。現在只有回應頁明寫「查詢結果 0」（或「查無資料」）才算查無；其他情況拋 `fjud.UnexpectedPage`（屬連線問題），照現行流程重試一次，仍失敗為 `retrieval_unavailable`／`network_error`。
- **「讀過全文才可引用」改由查證核對**：`verify --read-by plaintiff|defendant`，該方沒用 `judgment` 讀過全文的判決回 `not_read_by_side`（第七節）。檢索階段的規則同時告訴角色會核對、`--fetch` 不算讀過；查證階段的規則列出 `--read-by` 用法。W2 要接的只有上表第 4 項。只核對「本案讀過」，不分階段（同一份判決內容不變）。
- `retrieval-rules` 的 P1 目標原本寫「起訴狀選定的請求權基礎」與「`internal_analysis` 的其他候選」，但分析時還沒有起訴狀，也沒有這個欄位。已改成配合分析→撰狀兩步的寫法。
- 交接文件第 6 節與規格 5.9 說 `retrieval-rules`、排除參數尚未提供，已過時：兩者都在 `pleading-exchange`。

### 提案：排除清單改由程式帶入（決賽前做不做由組長決定）

現在排除的字號寫在角色看到的指令裡：字號本身就是提示（「這份判決跟本案有關」），角色漏帶也不會排除。可改成 `server/live_run.py` 啟動前設環境變數（與 `SNAPSHOT_ENV` 同一處），檢索指令自己讀，規則裡不再出現字號。檢索這邊改指令；`live_run.py` 需要組長加一行。

### 已確認一致

- 紀錄檔 `plaintiff_p1.jsonl`、預算 8 次搜尋／10 份全文；P1 給 `--side defendant` 時指令拒絕。
- `verify --precedent-notes <檔> --snapshot <案件快照根目錄>` 與規格相同。
- 檢索指令都是單一 `python main.py` 指令，符合 `ALLOWED_TOOLS`。
- 事實段的 `〔CF1〕` 不影響法條與字號比對（實測「民法第478條〔CF1〕」照樣抓到）。

## 十四、聯絡與更新

- 檢索這邊的進度與未完成事項：`docs/zh/retrieval-phase3-handoff.md`。
- 介面有變動時更新本文件；新框架這邊需要新的檢索介面，請直接提出，不要改上面列為檢索負責的檔案。
