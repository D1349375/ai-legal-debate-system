---
name: legal-debate
description: >-
  LegalDebate 模擬法庭 orchestrator:跑單一民事案件的完整三角色四階段流程(案件輸入→立場驅動檢索→
  Stage1爭點整理→法官訊問→Stage2訊問攻防→Stage3辯論終結→機械死穴彙整→法官爭點強弱評估→
  引用查證→訴狀骨架初稿)。觸發詞:「跑案件模擬法庭」「模擬攻防」「案件辯論」「/legal-debate」。
  三角色:原告代理人、被告代理人、法官。單一模型,單一審判長,僅處理民事通常訴訟程序案件。
  專案位置:Side Project/LegalDebate/。
---

# LegalDebate 模擬法庭 Orchestrator Runbook

你(主 agent)在此流程中的身分是**流程調度員/記帳員**。職責邊界(嚴格遵守):

- ✅ 準備案件輸入、依序調度原告/被告/法官 subagent、彙整結構化摘要、呼叫 CLI 落地、回報使用者
- ❌ **禁止自己判斷案件實質、禁止自己下爭點強弱結論**——你不是第三個律師,也不是法官
- ❌ 禁止修改機械聚合(`engine/aggregate.py`)的結果;法官的敘述只能在錨點方向內補充,不得推翻(見 Step 7)
- ❌ 禁止加開輪次:協議固定 Stage1→法官訊問→Stage2→Stage3→法官最終爭點強弱評估,不得因為「感覺還可以多辯一輪」而自行加開
- ❌ 禁止跳過查證閘門自己判斷引用真偽(見 Step 8)——`record_verdict`/`record_pleading` 對未查證引用會直接拒絕落地,這是機械閘門,不是你的判斷空間

所有指令在 `Side Project/LegalDebate/` 目錄下執行,直接用系統 Python(無獨立 venv):
`python main.py <cmd>`

## 前置檢查

1. **確認案件事實輸入**:是否已存在 `data/cases/<case_id>.json`(欄位:`case_id`/`case_type`/`facts_summary`/`claims`)。若使用者只給白話描述,協助整理成此 JSON 結構,**但事實內容只能來自使用者提供的資訊,不得自己代替使用者編造案情細節**。
2. **明確排除範圍**(非目標,啟動前務必跟使用者說明,避免預期落差):
   - **不模擬調解**:若案件仍在強制調解程序中或調解可能成立,本系統攻防結果僅供策略參考,不代表案件必然進入訴訟。
   - **僅處理通常訴訟程序**,不涵蓋小額(10萬以下)/簡易(50萬以下)訴訟的簡化流程。
   - 民事三角色(原告代理人/被告代理人/法官),單一審判長,不做合議庭;單一模型,不做多廠商模型矩陣(Phase 3 才有)。
3. **溫度設定的已知限制**:規劃文件(1.4.1 節,AgentCourt 借鏡)建議原被告 Stage1-3 用溫度 0.7、法官判決生成用溫度 0.2,但 Claude Code 目前派工 subagent 的機制不提供溫度參數,此建議**無法透過工具呼叫機械落實**。不要在 prompt 文字裡加一句「請用溫度 0.2 回答」這種對 LLM 自己不具約束力的假指令——列為已知限制,如實告知使用者,不假裝已落實。

## 流程(單一案件走完 Step 1-10)

### Step 1 — 案件輸入 + 凍結立場驅動檢索詞
- 確認/建立 `data/cases/<case_id>.json`,執行 `python main.py case --json data/cases/<case_id>.json` 落地案件。
- 依 `engine/stance_rag.py` 的規則(`build_stance_terms(side, case_type)`)取得雙方檢索詞——直接讀該檔案的 `_SIDE_FRAME_TERMS`/`_CASE_TYPE_TERMS` 對照案件的 `case_type` 列出結果即可,不需要额外寫程式呼叫。連同案件事實整理成一份摘要檔,供 Stage1 subagent 讀取。

### Step 2 — Stage 1 爭點整理(雙方獨立,可平行)
- 對 `plaintiff`、`defendant` 各開一個獨立 subagent(Agent 工具,一般用途即可),prompt **必須逐字套用** `templates/stage1_prompt.txt`,只填充 `{佔位符}`(`{SIDE}`/`{SIDE_LABEL}`/`{CASE_ID}`/`{CASE_FACTS_PATH}`/`{STANCE_TERMS}`/`{STATUTES_DIR}`=`corpus/statutes`/`{JUDGMENTS_DIR}`=`corpus/judgments`)。
- **隔離鐵律**:兩個 subagent 互相看不到對方的 prompt 或輸出,這是 Stage1 盲判的定義。
- 收齊後各自存成暫存 JSON,執行 `python main.py record --json <path>` 落地(`stage=1`)。

### Step 3 — 法官生成訊問(獨立 subagent,基於 Stage 1)
- 把雙方 Stage1 完整輸出整理成一份 JSON 給法官 subagent 讀,prompt 套用 `templates/judge_question_prompt.txt`。
- 法官輸出的 `questions` 陣列,每一則各自存成暫存 JSON,執行 `python main.py record --json <path>` 落地(該 JSON 含 `question_text`/`target_side`/`based_on`,`main.py` 會依欄位自動辨識為訊問記錄,不是論證記錄)。
- `uncontested_points` 不落地資料庫(schema 未設對應欄位),但你要記下來,留給 Step 7(訴狀優先順序建議)與 Step 10(回報使用者)用。

### Step 4 — Stage 2 雙方應訊(可平行)
- 給雙方各自:自己的 Stage1 完整輸出 + **對造 Stage1 的結構化摘要**(你自己從對造 Stage1 JSON 萃取 `position` + 最強論點一句話 + `cited_statutes`/`cited_precedents`,不得把對造完整 `reasoning` 全文丟過去——這是刻意設計,阻擋修辭趨同,逼雙方正面對決論點而非模仿對方語氣)+ 法官本輪全部訊問。
- prompt 套用 `templates/stage2_prompt.txt`。收齊後 `python main.py record --json <path>` 落地(`stage=2`)。

### Step 5 — Stage 3 辯論終結(可平行)
- 給雙方各自:自己的 Stage2 完整輸出 + 對造 Stage2 的結構化摘要(同 Step 4 的萃取方式)。
- prompt 套用 `templates/stage3_prompt.txt`。收齊後 `python main.py record --json <path>` 落地(`stage=3`)。

### Step 6 — finalize(機械死穴彙整 + 分歧統計)
```
python main.py finalize --case-id <case_id>
```
取得 `mechanical_anchor_json`(`weak_points` + `position_drift`),這是 Step 7 法官敘述不得違背的方向錨點。

### Step 7 — 法官頒布爭點強弱評估(獨立 subagent,受 Step 6 錨點約束)
- prompt 套用 `templates/verdict_prompt.txt`,餵入完整三階段紀錄 + Step 6 的機械錨點 JSON。
- **這裡先不落地** verdict——要等 Step 8 查證通過,`citations_used` 全數 published 才能落地(見下)。

### Step 8 — 引用查證(獨立 subagent,涵蓋判決書引用;獨立 context 結構性強制)
- 收集 Step 2-7 所有輸出裡出現的全部 `cited_statutes` + `cited_precedents` + verdict 的 `citations_used`,去重。
- **開一個新的、乾淨的 subagent**(不能是剛才寫論證/判決的同一個 context 自己查自己),第一項任務:
  ```
  python main.py verify <citation1> <citation2> ...
  ```
  (位置參數,不是 `--json`;查證通過的引用會自動 upsert 為 `published` 狀態)——這一步只確認引用**存在、文字正確**,是機械化查證,不判斷引用內容是否真的支持論點。
- **2026-08-09 新增第二項任務(實質查核,延伸自 Stage2/3 既有的「對造引用判例查核鐵律」,現在自己的引用也要接受同等審查)**:對於**實際要用進 Step 7 判決書或 Step 9 訴狀**(即會被 `citations_used`/訴狀引用陣列納入)的判例引用,同一個查證 subagent 須用 Read 讀取該判例全文(本地語料庫已有的直接讀;未在本地命中、僅存在候選階段的判例,依現有已知限制暫無自動查詢管道,標記為「無法查證」不得逕自採用,待人工或後續查證管道補上),核對案由/爭點是否真的支持被引用的論點主張,而不只是格式正確、真實存在。核對不通過(案由不符/爭點無關)者,視同查證失敗,不得進入 `published` 狀態,依下方失敗處理流程辦理。**範圍限定**:只對最終會被使用的引用做這層實質核對,不對 Stage1-3 過程中曾經提出但最終未採用的候選引用做全文核對,避免無界擴大查證成本。
- **只有全部引用查證(存在性+實質相關性)通過,才能進行 Step 7 的 verdict 落地與 Step 9 的訴狀草擬**。有任何引用查證失敗,回頭跟原本提出該引用的 subagent 或使用者說明,**不得自己動手改寫引用內容濫竽充數**——引用一旦被編輯,狀態強制重置為 draft,同一套 Phase 2.5 紀律。
- 查證通過後落地 Step 7 的判決:
  ```
  python main.py verdict --case-id <case_id> --json <path>
  ```
  (JSON 含 `verdict_main_text`/`verdict_reasoning`/`risk_map`/`mechanical_anchor_json`/`citations_used`)。`record_verdict` 若偵測到未 published 引用會直接拒絕落地(`ValueError`,`main.py` 回傳 exit code 1)——這是機械閘門,不是你的判斷空間,遇到報錯不要試圖繞過。

### Step 9 — 訴狀草擬(骨架版,2026-08-08 決定,不經 `taiwan-legal-pleading` skill 潤飾)
`taiwan-legal-pleading` skill 蒸餾已延後至 Phase 2(語料未到位,見 `noble-dancing-duckling.md`)。本階段訴狀初稿改為**骨架版**:

1. 用 Read 讀取 `corpus/pleadings/reference/司法院官方民事起訴狀範本_結構參考用.pdf`,取得訴狀欄位結構(案號/當事人欄/訴之聲明/事實及理由/證物名稱/此致/具狀人)。
2. 把 Stage3 的 `position`/`reasoning`/`cited_statutes` 直接套進上述骨架的對應欄位——預設以原告方 Stage3 為主(訴狀站在原告角度撰寫);若使用場景是被告方答辯狀,改用被告方 Stage3,依使用者實際需求判斷。**不做語氣潤飾、不做修辭改寫**,這是刻意的,語氣潤飾要等 Phase 2 律師語料到位才做。誠實跟使用者說明這是骨架版,不是最終可用訴狀。
3. 只使用 Step 8 已查證為 `published` 的引用,未 published 的引用不得出現在訴狀草稿裡。
4. 落地:
   ```
   python main.py pleading --case-id <case_id> --draft-file <path> --citations <path>
   ```
   (`--citations` 是一個 JSON 檔,內容是這份訴狀引用的 `citation_text` 陣列)。`record_pleading` 同樣做 published 查證閘門。

### Step 10 — 回報使用者
逐案回報:
- 雙方三階段立場摘要(Stage1 初始立場 → Stage3 最終立場,標出立場是否有位移)
- 法官爭點確認(哪些無實質爭議、哪些是真爭點)
- 機械死穴清單(`weak_points`,誰在哪個爭點有明確 falsifier)
- 立場位移統計(`position_drift`)
- 法官的爭點強弱評估與訴狀優先順序建議
- 骨架版訴狀初稿

結尾必附一句:**「本結果為爭點分析與訴狀骨架初稿,非法院判決預測,語氣潤飾與正式訴狀撰寫仍需律師覆核。」**

## 落地紀律

- `record`/`finalize`/`verdict`/`pleading` 遇「已落地不可覆寫」報錯 = 該案件此階段已跑過,**不要試圖刪除或改寫**,向使用者回報即可。
- 任何案件層級的統計評估(如多案件命中率)不在本 skill 範圍——單案跑測不構成統計意義上的驗證,不要臨時手算了就宣稱結論。

## 已知限制

- 溫度參數無法透過現有工具機械落實(見前置檢查第 3 點)。
- **✅ 已修正(2026-08-09)——判例查證即時擴及 FJUD,不再受限本地語料庫**:`engine/verify.py` 對 `corpus/judgments` 本地種子語料庫未命中的判例引用,現會自動即時查證司法院裁判書查詢系統 FJUD(`judgment.judicial.gov.tw`,免登入)。機制:先 GET 首頁取得 ASP.NET `__VIEWSTATE`/`__VIEWSTATEGENERATOR`/`__EVENTVALIDATION`,以完整裁判案號字串 POST 觸發搜尋,取得結果頁查詢token後 GET 結果列表(**兩個請求之間需間隔約1.5秒,緊接著發第二個請求實測會被拒絕連線**),解析 `data.aspx` 連結取得 JID,逐欄位比對年度/字別/字號完全一致才採用,避免誤採相近案號。查有結果回傳 `published`(`verified_via: fjud_live`)並附可供律師自行點開核對的官方連結;查無回傳 `not_found`(不再是舊版的 `not_in_phase1_seed_corpus`);連線失敗回傳 `verification_failed`(暫時性錯誤,非查無)。**注意**:此查證僅確認裁判「存在」,不涵蓋裁判全文之實質內容比對(那是上面「自我引用實質查核」項的範疇,兩者是查證的不同層次)。相關測試見 `tests/test_verify.py::TestJudgmentLiveVerification`(3個新增網路整合測試,共32個測試全數通過)。
- 立場驅動檢索(`stance_rag.py`)只做關鍵字組字串,不是語意檢索;`corpus/statutes`/`corpus/judgments` 的 Grep 結果可能因用詞不同而漏掉相關條文/判例,依賴 subagent 自己的法律知識補足,不是萬無一失的檢索機制。
- **✅ 已修正(2026-08-09)——引用來源邏輯**:舊版「本地語料庫Grep有找到就用,查無才動用自己法律知識」的順序已改正,`templates/stage1_prompt.txt` 現行版(請求權基礎檢驗法版)要求 subagent 在步驟一窮舉候選請求權基礎/抗辯的同時,**不論本地有無命中,都先依自己法律知識寫出候選引用**,Grep 結果僅作平行補充來源,挑選標準是「跟構成要件最貼切」而非「本地查得到」。經 5 案 A/B 測試驗證後正式取代舊版(詳見 `Prompt比較測試報告_請求權基礎檢驗法_test-2026-08-09-001.md` 與批次2報告),舊版 prompt 檔已刪除。
- **✅ 已修正(2026-08-09)——自我引用的實質查核**:原本「對造引用判例查核鐵律」只在 Stage2/3 查核對方引用,自己的引用只查存在性不查實質相關性。已於 Step 8 新增第二項查證任務,對**最終進入判決書/訴狀**的引用做案由/爭點是否真的支持論點的實質核對(範圍限定於實際採用的引用,不對中途候選做全量核對,控制成本),詳見 Step 8。
- **✅ 已修正(2026-08-09)——Stage2/3 同步套用請求權基礎檢驗法延伸版**:`stage2_prompt.txt`、`stage3_prompt.txt` 已各自新增四步驟(適應性調整,非 Stage1 原版照搬):Stage2 為「重新檢視己方候選清單(含Stage1備位)→逐則訊問對應打到哪個候選→主路徑受挫評估與備位啟用判斷+內部一致性檢查→整合更新立場」;Stage3 為「盤點兩輪累積候選清單→逐一標記仍站得住/已被打掉/未經檢驗→決定最終扶正哪個候選+內部一致性檢查(收斂,非再開新方向)→整合最終立場」。兩者皆新增「內部一致性檢查」步驟,防止同一方在不同輪次或不同候選路徑間出現自我矛盾主張(如同時主張契約已完全履行又以完工日主張時效抗辯)——這是此次延伸新增的機制,Stage1 原版沒有對應項,因為 Stage1 只提出候選、還沒有跨輪次累積矛盾的風險。既有的「對造引用判例查核鐵律」「五準則」「查詢前先規劃」「引用陣列格式鐵律」皆保留不變,新步驟是疊加,不是取代。
- **✅ 已完成(2026-08-09)——升級後完整 Phase 1.5 端到端驗證**:對 `test-2026-08-09-e2e-001`(取材114年度台上字第1547號)跑完 Step1-10 全流程,詳見 `Phase1_5端到端測試報告_test-2026-08-09-e2e-001(Stage1-3全套scaffold後首測).md`。確認整條鏈路正常運作,並在過程中意外揪出並修正一個嚴重既有 bug(見下一項),觀察到內部一致性檢查機制實際生效(原告主動撤回自己先前引用的可疑判例)。
- **✅ 已修正(2026-08-09)——`JUDGMENT_CITATION_RE` 字別白名單缺口(端到端測試發現,嚴重)**:原正規表示式只認得「台上/台簡抗/台抗」三種字別,本地語料庫實際涵蓋7種(另有台再/台簡上/台簡聲/台聲),其中「台簡上」數量頗多,此前查證一律誤判為 `unparseable`。已改為結構化比對(「台」開頭+1-3個非數字字元),不再逐一列舉,與先前「之N子條文」bug 同源(白名單漏掉真實變體),已補4個回歸測試(`tests/test_verify.py::TestParseCitation::test_judgment_citation_taijianshang` 等)。
- **✅ 已修正(2026-08-09)——citation_text 精確字串比對過嚴**:`database/db.py` 新增 `_citation_key()`(以 `engine.verify.parse_citation()` 解析引用字串為正規化 identity tuple:法規類為 (law_name, article_no),判決類為 (jyear, jcase, jno),忽略項款、「最高法院」前綴等格式差異)與 `_find_citation_row()`(先嘗試精確字串比對,找不到才退而以正規化 key 掃描比對)。`upsert_citation()` 與 `_assert_all_published()` 皆已改用正規化比對,「民法第129條」與「民法第129條第1項第2款」現在會被視為同一條文、共用同一筆查證紀錄。新增 `tests/test_db.py`(9個測試,涵蓋同條文不同項款/不同字別不得混淆/`draft`狀態仍應攔截等情境),`pytest` 共43個測試全數通過。
