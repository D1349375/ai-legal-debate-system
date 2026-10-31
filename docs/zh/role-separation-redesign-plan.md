# 修改實作計畫：職責分離與「待當事人確認」狀態

> 撰寫：2026-10-31。分支：`role-separation-redesign`（自 `ui-backend-integration` @ aeb618e 分出）。
> 這份是實作用（改哪些檔、怎麼驗證）。給組員看的白話版是 [改動點](redesign-change-points.md)。兩份同步更新；各步驟標「已定案」的是已討論完的。
> 依據：08-08 三案逐步標註（61 筆，3 案）、gcis 四次實跑、Codex 跑 real-2026-10-31-001／002 的紀錄與評估（含 Step 8 重試）。
> 注意：61 筆的逐筆清單不在 repo 內（Codex 評估與 `docs/live-run-records/` 都找不到），簡報引用這個數字前要補上出處。
> 每一步寫：**現在的問題（證據）→ 改什麼 → 改哪些檔 → 怎麼驗證**。標 **【A】** 的在決賽報告前做，標 **【B】** 的報告後做。

---

## 0. 核心判斷

兩個根因，所有步驟都是在處理這兩件事：

1. **流程寫在 prose 裡，由 LLM 照著演。** 調度、摘要、檔名、規則遵守都靠主 agent 讀 `SKILL.md` 自己決定，所以有隨機性，紀錄也無法重現。
2. **資料模型沒有「缺資訊」的位置。** 使用者只代理一方，對造 agent 本來就不會有當事人事實；但流程把對造當成「有當事人、有立場的律師」，於是缺資訊在每一階段被轉成某種立場：
   - 08-08：轉成「自承」（P1）。
   - Codex real-002：轉成「撤回時效抗辯」，而真實法院正是以時效駁回。

**設計原則**：職責分離要由程式強制，不靠 prompt 拜託。每一步盡量把規則從 prose 搬進 schema 與 `main.py` 的驗證；LLM 只在節點內做判斷。

**角色定義（新）**：案件多一個欄位 `represented_side`（使用者代理哪一方）。

| 角色 | 有無當事人 | 職責 | 不得做的事 |
|---|---|---|---|
| 我方代理人（represented_side） | 有（使用者） | 依我方事實主張、回應訊問 | 未經當事人授權承認事實或接受金額 |
| 對造模擬（紅隊） | **沒有** | 找出對方最可能的攻擊：①用我方事實打 ②證據缺口 ③需對方事實的假設抗辯 | 因「沒有證據」撤回假設抗辯；把假設寫成已發生 |
| 法官 | — | 整理爭點、訊問、評估強弱 | 讀內部備註；把沉默當不爭執；把假設寫成自承 |
| 調度（主 agent → 之後改為程式） | — | 依序派工、落地 | 自己寫摘要、自己判斷實質 |
| 查證 | — | 存在性＋文件身分＋實質支持 | 與寫論證的 context 共用 |

---

## Step 1 — 案件輸入

**問題**
- 只有單一 `facts_summary`（`database/schema.py:11`），不分誰的說法；被告 agent 讀的是原告版本卻不知道。
- 沒有「使用者代理哪一方」與「目前在哪個程序階段」：real-001／002 的 claims 寫「原起訴聲明」，角色因而反覆要求起訴狀、送達證書。
- 角色會讀整份 `case.json`，含 `source_note`（真實法院與字號，洩漏起訴年度）。Codex 紀錄重試後 001 有 13 次、002 有 12 次命中。

**已定案（2026-10-31 討論）**：三欄事實＋標來源；只支援起訴前；金額與程序別只警示不阻擋；UI 建案表單這週一起改。

**改什麼【A】**
1. `Case` 新增可為空欄位（`database/db.py:42` 已有自動 `ADD COLUMN`，舊案不受影響）：
   - `represented_side`：`plaintiff` | `defendant`，新案必填。
   - `uncontested_facts`、`plaintiff_facts`、`defendant_facts`：三欄事實，依當事人命名，不用「我方／對方」，切換代理方時不會混淆。
     - 每行一則事實。行首可加「〔書證：名稱〕」，程式解析為 `source=書證`；沒加的是 `source=陳述`。
     - 使用者代理原告時，`defendant_facts` 是**原告轉述或書證所載的對方說法**（例如警詢筆錄一句、對方 email），`role-view` 會照此標示，不寫成被告自己的陳述。
     - `uncontested_facts` 標示為「預期雙方不爭執（多為書證）」，由使用者判斷。
     - 舊案只有 `facts_summary` 時，整份放進代理方那一欄，標 `source=陳述`。
   - `claim_amount`：請求金額（整數，新臺幣）；非金錢請求（例如比特幣）留空。
2. **只支援起訴前**：不設程序階段欄位，所有輸入一律視為起訴前。建案時檢查 `claims`，含「原起訴」「變更聲明」等字樣就警示。
3. **金額與程序別警示（#12 前半）**：依 `claim_amount` 判斷小額、簡易或通常程序，不是通常程序時警示並請使用者確認，不阻擋。`claim_amount` 空白時標「金額未定，程序別待確認」。門檻條文（民事訴訟法第427條、第436條之8）先用查證引擎核對現行版本再寫進程式；第427條第2項依案件類型適用簡易程序的情形，只列入警示文字，不自動判斷。
4. 新增唯讀指令 `python main.py role-view --case-id <id> --role plaintiff|defendant|judge`：用程式產出**角色可見的案件檔**，不含 `source_note`。開頭寫明：
   - 你方是否有當事人（`represented_side`）。
   - 每一欄是誰的說法，哪幾則是書證。
   所有範本的 `{CASE_FACTS_PATH}` 改指向這個檔，不再直接讀 `case.json`。
5. **UI 建案表單**（第三層，見「執行順序」；`ui/app.js:1218`、`server/app.py:57`）：
   - 代理方選擇（必填）。
   - 三個事實欄位，附說明與「〔書證：〕」寫法範例。
   - 請求金額欄位；送出前顯示程序別警示。
   - 案件頁顯示三欄事實與書證標記。

**檔案**：`database/schema.py`、`database/db.py`、`main.py`、`server/app.py`、`ui/app.js`、`data/cases/*.json`（新案）
**驗證**：`role-view` 輸出不含 `source_note`；書證前綴解析正確；舊案能正常產出；程序別警示的邊界值（10 萬、50 萬）；`tests/test_create_case.py`、`tests/test_server.py` 補測試。

## Step 1.5 — 起訴審查

不動。商工規則已是確定性程式，是現在架構中職責分離做得最好的一段，簡報可以當正面範例。

## Step 2 — Stage 1 爭點整理

**問題**
- `stage1_prompt.txt:3` 要求把所有分析寫進「寫給法官看」的 argument；`:14` 要求預想對方反駁。結果自我弱點直接進到法官手上（P1 的種子）。
- 主張是自由文字，後續階段只能靠 LLM 重讀、重摘，限定語（「卷內未載」「若」）在壓縮時掉了。
- `stage1:27` 允許憑記憶引用判例、不必讀全文（P4）。
- 涵攝沒有區分「卷內事實」與「我方推論」（P5）。

**已定案（2026-10-31 討論）**：
- 內部備註給己方後續輪次與使用者看，法官與對造看不到。
- 判決必須讀過全文才能引用，法條可依法律知識提出。
- 要件標「已該當」時必須指到事實編號。
- 長度：錯在混在一起、壓得太兇，不是寫太多，所以用結構解決，不用字數。position 限一兩句；argument 只設寬鬆上限，目的是控制花費，不是提升品質。

**改什麼【A】**
1. 輸出 schema 新增兩欄（DB 存在新欄位 `structured_json`）：
   - `items`：每個請求權基礎／抗辯一筆
     ```json
     {"id": "D3", "label": "侵權二年時效", "kind": "legal|evidence_gap|factual_hypothesis",
      "status": "asserted|to_confirm|withdrawn",
      "elements": [{"element": "知悉損害及賠償義務人", "state": "met|unmet|unknown", "source": "record|inference"}],
      "needs_from_client": ["原告何時知悉被告身分", "有無催告紀錄"],
      "citations": ["民法第197條"]}
     ```
   - `elements[].source` 改為：卷內事實寫事實編號（`F3`，由 `role-view` 替每則事實編號），推論寫 `inference` 並附一句根據。
   - `internal_notes`：策略備註與自我弱點。
     - 代理方的備註：給己方 Stage 2、3 參考，也放進給使用者的回報（這是律師最需要的自我弱點清單）。
     - 對造模擬的備註：只給它自己的後續輪次。
     - **程式保證不給法官與對造**：法官與對造的輸入都由程式投影產生，不含這一欄。
   - `position_basis`：position 依據的 item id 清單。
2. 範本加入角色段落，依 `represented_side` 二選一：
   - 代理方：主張以己方事實為限；要件資訊不足時寫進 `needs_from_client`（要我方當事人補的資料）。
   - 對造模擬（定位：預測對方律師可能怎麼打）：產出三類。
     - `legal`：用代理方自己的事實打。例：001 用原告的 email「零件短少，正在盤點」主張那就是瑕疵通知；002 用警詢「我以為前車要起步」主張與有過失。
     - `evidence_gap`：代理方的證據缺口。
     - `factual_hypothesis`：需要對方自己的事實，一律 `to_confirm`，寫成「若對方能提出 X」，`needs_from_client` 寫對方需要提出什麼。
3. 三輪範本都加通則：「資料沒寫的事寫『待確認』，不能寫成有，也不能寫成沒有。」
4. 判例引用：必須在本輪 Read 過全文，並在 item 寫一句案由，才能放進 `cited_precedents`。憑記憶想到的判例放 `precedent_leads`（檢索線索），不得引用。法條可依法律知識提出，交給查證引擎。保留 08-09 A/B 測試「先窮舉候選」的好處。
5. 長度與確定性：
   - `position` 限一兩句（約 100 字）。
   - `position_basis` 中的 item 若狀態是 `to_confirm`，或含 `state=unknown` 的要件，`record` 拒絕落地：論證裡待確認的事，立場裡不能寫成確定。
   - `argument` 設寬鬆上限（例如 8,000 字）當花費安全網，超過退回重寫。

**檔案**：`templates/stage1_prompt.txt`、`database/schema.py`、`main.py cmd_record`、`main.py role-view`（事實編號）
**驗證**：`record` 檢查 `items` 結構、id 唯一、enum 合法、事實編號存在、`position_basis` 狀態，不合格拒絕落地（規則進程式）。
**限制**：程式只能檢查 `position_basis` 指到的 item 狀態，無法確認 position 文字本身沒有把未提及的事講成確定；這部分仍靠範本規則與法官評估時的出處核對（Step 7）。

## Step 3 — 法官訊問

**問題**
- `judge_question_prompt.txt:16`：「其中一方未爭執」就列為無爭議。盲判下對造不可能回應，沉默被當不爭執。
- `:20`：`based_on` 回溯到 Stage 1 的「某一句」，條件句和內部弱點因此被標成「自承」。
- 法官讀雙方 Stage 1 全文，含自我弱點分析。

**已定案（2026-10-31 討論）**：
- 代理方可以收到事實題；答「待確認」不能被改寫成「沒有」或「承認」。
- 原本要問對造的事實題，由法官改寫成給代理方的準備清單；每筆標為假設，不回傳給對造、不進起訴狀。
- 代理方在 Stage 2 回應準備清單，回應寫進內部備註，不寫進論證。
- 共同原則：「可能」「待確認」這類限定，一路上都不能弄丟。

**改什麼【A】**
1. 法官的輸入改為程式投影：雙方 `position`、`argument`、`items`，**不含 `internal_notes`**。
2. `based_on` 改為 item id（例如 `defendant:D3`）加一句說明；`record` 驗證 id 存在。
3. 每則訊問加 `question_type`：`legal` | `factual`。
   - 給對造模擬方：只能是 `legal`（例如「這封 email 算不算通知」「與有過失由誰舉證」）。`record` 遇到對造模擬方收到 `factual` 就拒絕。
   - 給代理方：`legal`、`factual` 都可以。`factual` 題同時列入給使用者的「請當事人補的資料」清單。
4. 法官新增輸出 `prep_items`（給代理方的準備清單），每筆：
   ```json
   {"id": "J-PREP-1", "hypothesis": "對方可能提出行車紀錄器影片",
    "affects": "plaintiff:P2", "prepare": "確認我方車輛當時是否完全靜止；調閱路口監視器",
    "holder": "opponent", "is_hypothesis": true}
   ```
   - `is_hypothesis` 固定為 true，`affects` 必須是存在的 item id。
   - 存在獨立欄位，**程式保證不進對造的任何輸入，也不進書狀素材**（`summary`、`role-view`、`pleading-source` 都不讀這一欄）。
5. 規則改寫：
   - 「不爭執」只能是雙方都 `asserted` 且內容一致的事實；一方沒提不算。Stage 1 雙方本來看不到彼此，不得寫「未回應」。
   - 不得在 `question_text`、`uncontested_points` 用「自承／自認／坦承」，除非引用的 item 是該方 `asserted` 的事實陳述。由 `record` 做關鍵字檢查，命中但對應 item 不符就拒絕。
   - 代理方答「待確認」的事實，後續任何階段不得寫成「沒有」「無」或「承認」：該 item 狀態維持 `to_confirm`，由 Step 4、5 的狀態轉移檢查守住。

6. 連帶修改（Step 7 定案）：法官輸出加 `issues`（`issue_id`、label、相關 item id），取代 `uncontested_points` 以外的自由文字爭點整理；Step 7 的逐爭點表格沿用這些 `issue_id`。

**檔案**：`templates/judge_question_prompt.txt`、`database/schema.py`（`court_questions` 加 `question_type`；新欄位或新表存 `prep_items`、`issues`）、`main.py`
**驗證**：
- 用 08-08 test-002 的法官訊問 1（把被告條件句標成「自承」）當反例，應被擋下。
- 對造模擬方收到 `factual` 題應被擋下。
- `summary`、`pleading-source` 的輸出不含 `prep_items`。
**限制**：題型由 LLM 自己標，標錯時程式抓不到；用兩層防線補：對造模擬方收到事實題時固定回答「此為事實問題，對造模擬無從回答，轉列準備清單」並記為 `to_confirm`（Step 4）；可疑關鍵字（「有無證據」「是否持有」「為何」）標記給人工複查。

## Step 4 — Stage 2 訊問攻防

**問題**
- `stage2_prompt.txt:40`：「`based_on` 對應到的主張你必須認，不得說這不是我方主張」——法官誤述時無法更正。
- `:41`：falsifier 定義為「會讓你讓步的條件」且必填。對造模擬沒有當事人，這等於要它預寫認輸條件（P3）。
- 對造摘要由主 agent 自己寫（`SKILL.md:58`），沒有範本、沒存檔，限定語會掉，欄位名每次不同。

**已定案（2026-10-31 討論，Step 4、5 共用）**：
- 讓步條件改問「什麼證據出現會改變我對此爭點的評估」。我方寫的進內部備註，只給使用者看；對方 agent 寫的是「若代理方提出 X，此抗辯失效」，可公開，也放進準備清單。
- 撤回只能附依據：卷內事實排除（事實編號）或對方法律論點打掉（對方 item id）。「資料不足」永遠不是理由。策略性撤回只開放給代理方，對造模擬方不行。
- 五準則只留「不重複、開新視角、直接回應」。「開新視角」限新的法律角度，不得補新的事實。
- 機械彙整的程式要跟著改（接 Step 6）。

**改什麼【A】**
1. `:40` 改為：「法官若誤述你方主張，指出並以 item id 更正；不得否認你方確實提出的內容。」
2. falsifier 重新定義，依角色分開：
   - **代理方**：`update_conditions`（什麼證據出現會改變我方對此爭點的評估），寫進 `internal_notes.update_conditions`。本質是自我弱點，**不進 DB `falsifier` 欄、不進對造摘要、不進法官輸入**，只進給使用者的回報。
   - **對造模擬方**：`defeat_conditions`（「若代理方能提出 X，此抗辯失效」），每筆指到自己的 item id。寫進 DB `falsifier` 欄（公開），並由程式併入給代理方的準備清單。
   - `falsifier` 欄位名維持，語意變更寫進 `database/schema.py` 註解；代理方該欄為空。
3. 代理人角色規則：
   - 代理方：不得未經當事人授權承認事實、接受金額。
   - 對造模擬方：沒有當事人，不做策略取捨；站得住的抗辯一律保留。
4. 撤回規則（`record` 比對前一階段 items 強制執行）：
   ```json
   {"status": "withdrawn",
    "withdraw_reason": {"type": "record_negates", "fact_ids": ["F3"]}}
   ```
   - `type` 只能是：`record_negates`（附存在的事實編號）、`opponent_defeats`（附存在的對方 item id）、`strategy`（附說明，**只限代理方**）。
   - 任何 item 從 `asserted`／`to_confirm` 變 `withdrawn`，缺 `withdraw_reason` 或類型不合就拒絕落地。
   - 「資料不足」不是可選類型；資料不足的 item 維持 `to_confirm`。
   - item 不得在後續階段消失：前一階段有的 id，這一階段必須出現（狀態可變）。
5. 五準則改為三條：不重複前論、開新的法律角度（不得補新的事實細節）、直接回應法官與對方最新論點。刪除「盡量帶新依據」與「變化表達方式」：前者逼模型湊新判決（P4、引用位移失真），後者讓限定語在改寫時掉（002「資料沒提到」→「現無」）。Stage 2 第 25–30 行、Stage 3 第 21 行同步改。
6. 由第 3 項帶入（已定案）：
   - 代理方逐筆回應法官的 `prep_items`，寫進 `internal_notes.prep_responses`（例如「若對方影片顯示我方車輛有移動，改主張移動幅度極小、不構成過失」），不寫進 `argument`。
   - 對造模擬方若仍收到事實題，固定回答「此為事實問題，對造模擬無從回答，轉列準備清單」，該題對應的 item 記為 `to_confirm`。
7. 對造摘要改用程式產生：`python main.py summary --case-id <id> --side <s> --stage <n>`，固定格式，從落地 JSON 機械取出：
   - `position`
   - 各 item 的 id、label、kind、status
   - `unconfirmed_facts`（尚未確認的事實）：所有 `to_confirm` item 與 `state=unknown` 的要件，原文保留「若」「待確認」
   - 公開的 `defeat_conditions`（只有對造模擬方有）
   - 引用
   不含 `internal_notes`、`prep_items`。不再由 LLM 寫，也就不會濾掉限定語。

**檔案**：`templates/stage2_prompt.txt`、`main.py`（`summary`、`record` 狀態轉移檢查）、`database/schema.py`（`falsifier` 註解）、`SKILL.md` Step 4
**驗證**：
- 用 Codex real-002 被告 Stage 3 當反例：時效 item 以「日期資料不足」撤回，應被擋下。
- 同案第二個反例：被告 Stage 1 完整提出民法第182條第1項（善意受領、利益已不存在），Stage 2、3 以「無本人事實」退出；`d_s3` 最終 position 寫「不以尚未證成的二年、五年時效或其他減免候選請求駁回」。這兩項（第182條、五年時效）也應維持 `to_confirm`。真實被告正是提出了善意且利益已不存在的抗辯。
- 對造模擬方用 `strategy` 撤回，應被擋下。
- item 在後續階段消失，應被擋下。
- `summary` 輸出不含 `internal_notes`、`prep_items`，且保留 `unconfirmed_facts`。

## Step 5 — Stage 3 辯論終結

**問題**
- `stage3_prompt.txt:7`、`:21`：要求收斂、不開新方向；`:33`：「不是為了辯論效果誇大的版本」。三者疊加，對造模擬把沒證據的抗辯全收掉。Codex real-002 的被告 position：「本輪不以尚未證成的二年、五年時效…請求駁回」。
- `:31`：必須正面回應對造最強論點，所以 Stage 3 本質是反駁文；但 9A 起訴狀拿它當素材（P2）。

**已定案**：同 Step 4（讓步條件、撤回規則、三準則都適用）。

**改什麼【A】**
1. 收斂只適用 `asserted` 項目；`to_confirm` 項目保留到最後，在最終輸出列為「待當事人確認清單」。
2. `:33` 改為：「最終立場要反映卷內事實；未知的事實標為待確認，不視為不成立。」
3. 輸出分兩欄：`claim_statement`（我方主張本身，不回應對造）與 `rebuttal`（對造論點的回應）。9A 只用前者。
4. 同 Step 4 的狀態轉移檢查與程式摘要。

**檔案**：`templates/stage3_prompt.txt`、`main.py`
**驗證**：用 Codex real-002 的被告 Stage 3 當反例：時效 item 若從 `to_confirm` 變 `withdrawn` 而理由只是「日期不足」，應被擋下；第182條、五年時效兩項同樣適用（見 Step 4）。

## Step 6 — 機械彙整

**問題**
- `engine/aggregate.py:13-33` 把 falsifier 原樣抄成 `weak_points`，法官又不得反向解讀（`verdict_prompt.txt:12`），讓步條件被固定成「弱點」。
- `position_drift` 是引用集合的 Jaccard 距離，法官卻讀成「立場拉鋸」。

**已定案（2026-10-31 討論）**：
- 拿掉 `weak_points`，改整理成「代理方要準備的證據」與「待確認清單」。
- 「立場位移」全面改名為「引用清單差異」，先統一引用寫法再算，只給使用者與畫面，不交給法官；回報與 UI 的名稱一起改。另算「主張狀態變化」當真正的立場指標，同樣不交給法官。
- 對法官的約束改為「每一筆都要回應，但不規定方向」；法官提到待確認項目時必須照寫「待確認」（實作在 Step 7）。
- 待確認清單分三種：問我方當事人、對方可能有、需向第三方或法院調閱。

**改什麼【A】**
1. 錨點改為以下幾塊，全部由程式從各階段 items 取出，不做語意判斷：
   - `defeat_conditions`：對造模擬方的「若代理方提出 X，此抗辯失效」，每筆附對方 item id，標為「代理方要準備的證據」。不稱為任何一方的弱點。
   - `pending`：待確認清單，依 `holder` 分三類：
     - `own_client`：問我方當事人（來源：代理方 `needs_from_client`、法官給代理方的 `factual` 題）。
     - `opponent`：對方可能有（來源：對造模擬方 `factual_hypothesis`、法官 `prep_items`）。
     - `third_party`：需向第三方或法院調閱，例如路口監視器、警方事故分析（律師通常在書狀聲請調查證據）。
   - `status_changes`：每個 item 從 Stage 1 到 Stage 3 的狀態變化（例如 `asserted → withdrawn`、`to_confirm → asserted`），附階段與 `withdraw_reason`。給使用者與 UI，**不交給法官**。
   - `citation_set_change`：即原 `position_drift`，改名。計算前先用 `engine.verify.parse_citation` 正規化（「判決」「裁定」、項款寫法不同不算差異）。給使用者與 UI，**不交給法官**。
2. 法官的錨點輸入由程式投影，只含 `defeat_conditions`、`pending`、`procedural_issues`。
3. 連帶修改：Step 2 的 `needs_from_client`、Step 3 的 `prep_items` 每筆加 `holder`（`own_client` | `opponent` | `third_party`）。
4. 全面改名：`SKILL.md` Step 6、Step 10 與 `ui/app.js` 中的「立場位移」「死穴」「弱點」字樣改為新名稱。舊案件（舊 `protocol_version`）仍輸出 `weak_points`、`position_drift`，UI 依版本顯示，不會壞（UI 有 11 處引用）。

**檔案**：`engine/aggregate.py`、`tests/test_aggregate.py`、`main.py cmd_finalize`、`SKILL.md`、`ui/app.js`
**驗證**：純函數，補單元測試：
- 代理方的 `update_conditions` 不出現在錨點。
- 同一判決只差「判決／裁定」寫法時，`citation_set_change` 為 0。
- `status_changes` 正確列出撤回與理由。
- `pending` 三類分流正確。

## Step 7 — 法官爭點強弱評估

**問題**
- 錨點約束寫成「不得推翻」，加上 falsifier＝弱點，法官被迫把讓步條件當結論。
- 沒有要求檢驗推理鏈，也沒有核對「自承」是否真的存在（P5）。
- 產出對使用者不夠直接：使用者是原告律師時，他最需要的是「對方最可能怎麼打、我要先準備什麼」。

**已定案（2026-10-31 討論）**：
- 引述任何一方都附 item id 與輪次；描述立場改變要並排兩個輪次，並對照「主張狀態變化」。編號對了描述仍可能錯，所以畫面自動帶出原文給使用者比對。
- 「互相印證」必須列兩個不同的**案件事實編號（F 開頭）**，不接受主張編號，才擋得住同源自證。
- 輸出改為逐爭點表格加簡短結論。高／中／低依主張狀態定義，程式先算參考等級；法官可給不同等級，但要寫理由。
- 沿用 Step 6：每一筆錨點都要回應，不規定方向；提到待確認項目必須照寫「待確認」。

**改什麼【A】**
1. 錨點約束改為：「錨點每一筆都要以編號回應並說明看法，但不必同意；`defeat_conditions` 是條件，不是已發生的事實。」法官輸入不含 `status_changes`、`citation_set_change`、任何 `internal_notes`。
2. 引述格式 `defendant:D3@S3`（方:item id@輪次）。`cmd_verdict` 檢查：
   - 每個引述的 item 在該輪次確實存在。
   - 寫成立場改變（`D3@S1 → D3@S3`）時，`status_changes` 必須有對應變化；紀錄顯示沒變就拒絕。
   - 出現「自承／自認／坦承」時，指到的 item 必須是該方 `asserted` 的事實陳述（同 Step 3）。
   - 含 `to_confirm` item 編號的句子必須出現「待確認」或「若」等限定詞（近似檢查）。
   - 錨點每一筆的編號都出現過（覆蓋檢查）。
3. 出現「相互印證／佐證」時，同一句必須列至少兩個不同的事實編號（`F` 開頭），且都存在；只列 item id 不算。
4. 輸出改為：
   ```json
   {"issues": [{"issue_id": "I1", "label": "被告是否有過失",
                "own_items": ["plaintiff:P2@S3"], "opponent_items": ["defendant:D2@S3"],
                "reference_grade": "中", "grade": "中", "grade_reason": null,
                "basis": ["F2", "F5"], "inference": "…（無則 null）",
                "to_prepare": ["pending:opponent:3"]}],
    "summary": "幾句話：書狀要先寫哪幾個爭點",
    "anchor_responses": [{"ref": "defendant:D2", "comment": "…"}],
    "citations_used": []}
   ```
   - `risk_map` 不再由法官自由列，改由 `issues` 加上 Step 6 的三類 `pending` 組成。
   - `issue_id` 沿用 Step 3 法官整理的爭點（連帶修改：法官訊問輸出加 `issues`，每個爭點列出相關 item id）。
5. `reference_grade` 由程式依代理方在該爭點的 items 算出，法官看得到：
   - **高**：每個要件 `state=met` 且有事實編號，對方在該爭點沒有仍為 `asserted` 的項目。
   - **中**：有要件 `unknown`、有 item 為 `to_confirm`，或對方仍有 `asserted` 的項目。
   - **低**：有要件 `unmet`、有 item 被 `opponent_defeats` 撤回，或關鍵要件只有推論支持。
   - `grade` 與 `reference_grade` 不同時，`grade_reason` 必填，否則拒絕落地。
6. UI 爭點評估分頁改成表格；所有 `X:ID@S` 引述旁自動顯示該項原文（【B】若時間不足，簡報用截圖示意即可）。

**檔案**：`templates/verdict_prompt.txt`、`templates/judge_question_prompt.txt`（`issues`）、`engine/aggregate.py`（`reference_grade`）、`main.py cmd_verdict`、`database/schema.py`（`verdicts` 存結構化 JSON）、`ui/app.js`
**驗證**：
- 08-08 test-002 的評估（把原告論點說成被告承認、同源印證）當反例，應被擋下。
- 001「被告原本主張全額不付」：附的編號存在但描述不符，程式擋不下，畫面帶出原文可以看出來——這一項寫進限制。
- `reference_grade` 的三個等級各有單元測試。
**限制**：程式只能檢查編號、輪次、狀態與事實編號是否存在，不能檢查法官的描述與原文是否一致；這部分靠畫面帶出原文讓使用者比對。

## Step 8 — 引用查證

**問題**（已親自核對程式）
- `engine/verify.py:183-185`：用字號前綴找檔，取 `os.listdir` 第一個。語料庫有 19 個字號對應多份文件；114 台上 1945 會取到承受訴訟裁定，而不是被引用的實體判決。`published` 實際上只代表「有這個字號開頭的檔案」。
- `engine/verify.py:58`：法規白名單 8 部。Stage 1 可引任何法，銀行法、民法債編施行法到 Step 8 必然 `unparseable`，閘門必然失敗。不支援歷史條文版本（民法第 205 條 108 年版）。
- `database/schema.py:58-66`：`citation_verifications` 以 `citation_text` 為唯一鍵，沒有 `case_id`，`verifier_run_id` 全空；是全域快取，無法知道哪一案、哪一次驗過。
- Step 8 沒有範本檔，只有 `SKILL.md:75-83` 的 prose；Codex 兩案都卡在這一步。
- 以下是 Codex 重試紀錄補出的問題（2026-10-31 補充）：
  - **歷史版本被誤標通過**：002 雙方引用 108 年版民法第205條（20%、超額無請求權），引擎查到現行條文（16%、超過約定無效）就標 `published`，等於驗錯版本也算過。最後是查證角色手動降為 draft，閘門因此擋下。
  - **`main.py verify` 一律回傳 0**（`main.py:98-106`），而且只把 `published` 寫進 DB；`unparseable`、連線失敗都不留紀錄。閘門到底過了沒，只能靠 prose 判斷。
  - **暫時性連線失敗沒有自動重試**：001 民法第130條、002 民事訴訟法第195條都碰到 SSL EOF，回 `verification_failed`，都是角色手動重試才過。
  - **查證角色直接寫共用快取**：002 call12 透過 `get_session`／`upsert_citation` 把 205 改成 draft、清空 `verified_at`，也改了 1945 的來源 metadata。快取沒有 `case_id`，一案的判斷就連帶改到 001 的共用狀態。
  - **法規解析要到 Step 8 才做**：民法債編施行法從原告 Stage 1 一路傳過六份論證和評估，到 Step 8 才發現無法解析。

**已定案（2026-10-31 討論）**：內容比對分三層，前兩層（案由與文件類型、原文摘句）由程式做；案由不同不自動擋，標「需說明」並要求寫類推理由；前兩層涵蓋所有判例引用，第三層只做最後採用的。

**補充（2026-10-31，依 Codex 重試紀錄）**：歷史版本查詢仍放【B】，但【A】先讓「驗不了」有自己的狀態，不再標成通過。閘門規則：`unsupported_law`、`version_unverified` 不擋評估發布，但不得進書狀，並在回報列為「律師待核」。這樣 real-002 重跑才走得到 Step 9。

**改什麼**
1. **【A】** 文件身分：回傳所有同字號候選；多於一份時要求呼叫端指定日期，或回傳 `ambiguous` 不得 `published`。
2. **【A】** 法規白名單：補入實跑出現過的法規（銀行法、民法債編施行法、民事訴訟法施行法等）。不在白名單的法規回傳 `unsupported_law`，與 `unparseable` 分開，報告中照實列出，不視為不存在。
3. **【A】** 新表 `case_citation_checks(case_id, citation_text, status, source_file, checked_at, verifier_run_id, support_note)`：每案、每次查證各一列。全域表保留當快取。
4. **【A】** 新增 `templates/verify_prompt.txt`：把 `SKILL.md:75-83` 搬成範本，輸出結構化 JSON（每條引用：存在性、文件身分、是否支持該命題、理由）。
5. **【A】** 判例內容比對分三層（已定案）：
   - **第一層：案由與文件類型（程式）**。比對引用者寫的案由與文件類型，和該檔 `_source.json` 的 `jtitle` 及全文首行（「判決」或「裁定」）。文件類型不符直接擋下。
   - **第二層：原文摘句（程式）**。每則判例引用附一段原文摘句，程式檢查是全文的子字串；找不到直接擋下。
   - **第三層：是否真的支持論點（獨立查證 agent）**。依 `verify_prompt.txt` 判斷並寫理由。
   - 連帶修改 Step 2：判例引用從「寫一句案由」改成結構化的 `precedent_notes`：
     ```json
     {"citation": "最高法院114年度台上字第1945號", "doc_date": "20260513",
      "doc_type": "判決", "case_cause": "確認本票債權不存在",
      "quote": "<全文中的一段原文>", "proposition": "受詐欺之契約於撤銷前仍屬有效",
      "analogy_reason": null}
     ```
     `doc_date` 同時解決同字號多文件的問題（第 1 點）。
6. **【A】** 案由不同不自動擋（已定案）：標「需說明」，`analogy_reason` 必填，交第三層判斷。理由：Codex 評估裡有多則不同案由的合理有限類推（例如引商譽損害判決說明民事訴訟法第222條第2項的酌定標準）。只有文件類型不符、原文摘句找不到才直接擋。
7. **【A】** 查證範圍（已定案）：
   - 第一、二層：Stage 1–3 與評估中的**所有**判例引用都做，因為 Stage 2、3 新增的引用會進到對方摘要。在 `record` 落地時就做，不等 Step 8。
   - 第三層：只對最後進到評估或書狀的引用做，控制成本。
8. **【A】** 歷史版本狀態：引用文字含過去年度或「修正前」（例如「108年民法第205條」），或角色在 item 註明適用舊法時，回傳 `version_unverified`，不得 `published`。適用上述閘門規則。
9. **【A】** 閘門由程式判斷：新增 `python main.py verify-gate --case-id <id>`，依 `case_citation_checks` 判斷能否放行，未通過時回傳非 0 並列出原因。`cmd_verdict`、`record_pleading` 落地前都呼叫同一個判斷；書狀的 `citations_used` 只能是該案 `published` 的引用。
10. **【A】** 暫時性錯誤自動重試：連線類錯誤（SSL、逾時）自動重試 2–3 次；仍失敗回傳 `network_error`，和查無（`not_found`）分開，報告照實列出。
11. **【A】** 查證結果只能透過固定指令寫入：新增 `python main.py record-verification --case-id <id> --json <file>`，讀 `verify_prompt.txt` 的結構化輸出，寫進 `case_citation_checks`。全域快取只存「存在與否」；版本、文件身分、是否支持命題等判斷只寫進每案紀錄，不改全域快取。查證角色不得直接呼叫 `upsert_citation`。
12. **【A】** 法規在落地時就檢查：`record` 落地 Stage 1–3 時，也對法條跑 `parse_citation`。`unsupported_law` 當場標記並回給角色（不拒絕落地），讓它知道這條到 Step 8 會列為律師待核。
13. **【B】** 歷史條文版本查詢（查官方舊法全文）。

**檔案**：`engine/verify.py`、`database/schema.py`、`database/db.py`、`main.py`、`tests/test_verify.py`、`tests/test_db.py`
**驗證**：回歸測試：
- 114 台上 1945 未指定日期回傳 `ambiguous`；指定 `20260513` 取到實體判決。
- 銀行法第 29 條可解析；不在白名單的法規回傳 `unsupported_law`，不是 `unparseable`。
- `doc_type` 寫「判決」但檔案是裁定，被擋下。
- 摘句不在全文中，被擋下。
- 案由不同且 `analogy_reason` 為空，被擋下；有填則標「需說明」。
- 用 08-08 test-002 的 115 台上 447（醫療糾紛上訴駁回裁定，被當車禍依據）當反例。
- 「108年民法第205條」回傳 `version_unverified`，不是 `published`。
- 閘門：有 `unsupported_law`／`version_unverified` 時，`verify-gate` 允許評估發布；書狀引用含這類條文時拒絕落地。有 `not_found`、`ambiguous` 或 `network_error` 時回傳非 0。
- 模擬 SSL 錯誤：先重試，仍失敗時回 `network_error`。
- A 案的查證判斷不改 B 案看到的狀態（每案紀錄互相獨立）。

## Step 9 — 書狀骨架

**問題**
- 9A 起訴狀用原告 Stage 3（`SKILL.md:105`），Stage 3 是反駁文，起訴狀因而出現被告答辯後才有的內容（P2）。08-08 test-002 起訴狀更把原告 Stage 1 的推論壓成「被告自承因低頭操作手機分心」。
- Codex real-001 換了模型、用真實案件，P2 照樣出現在原告起訴狀：「（二）正面回應對造最強論點。對造要求先確定各項請求的事實……」。同一段來源還有「亦承認對造已不再以概括免責……」「Stage 2要求補明的原起訴……」。用的字是「對造」和模擬流程用語，不是「被告主張」。
- `SKILL.md` 9 的共同紀律第 1 點要求把 Stage 3「直接套進、不潤飾」（凍結版第 97 行），反駁內容因而原封不動進了起訴狀。
- 001 原告 writer 回傳的 `citations` 是 35 個 `{citation_text, status}` 物件，不是字串陣列，由調度員事後轉換；`record_pleading` 沒檢查格式。
- 使用者代理原告時，產出被告答辯狀沒有實際用途：被告是模擬的，答辯狀只是假設。

**已定案（2026-10-31 討論）**：
- 骨架版起訴狀不預先回應可預見的抗辯；預想與應對留在內部備註與準備清單，由律師決定要不要寫。
- 起訴狀附請求金額明細表；程式加總比對請求金額；待確認項目的金額不進訴之聲明，改列律師附註。
- 代理原告時不產答辯狀，改產「對方可能答辯要點（預演用，非書狀）」；代理被告時產「預先準備的答辯狀草稿」。

**改什麼【A】**
1. 9A 素材：原告 Stage 3 的 `claim_statement` 與狀態為 `asserted` 的 items。`pleading-source` 只輸出這些，**不輸出** `rebuttal`、`internal_notes`、`prep_items`、`to_confirm` items。
2. 不預先回應抗辯：`record_pleading` 檢查起訴狀，出現以下字樣就拒絕落地：
   - 對方說法：「被告主張／被告抗辯／被告自承／被告或將／本方／對造」。
   - 模擬流程用語：「Stage／輪次／前輪／法官訊問／訊問攻防」。
   - 同時改 `SKILL.md` 共同紀律第 1 點：素材依第 1 項由程式取出，不再寫「把 Stage 3 直接套進」。
3. 請求金額明細（新增 `claim_breakdown`）：
   ```json
   [{"name": "車輛維修費", "amount": 120000, "basis": ["F4"], "formula": null,
     "item": "plaintiff:P1@S3"}]
   ```
   - `item` 必須是 `asserted`；對應 item 為 `to_confirm` 的那筆，不進訴之聲明，改列書狀末尾的「律師附註：待確認後再決定是否請求」。
   - 程式加總 `amount`，與案件 `claim_amount` 不符時警示（不阻擋）；`basis` 的事實編號必須存在，`formula` 與 `basis` 至少一項。
   - 這是 Step 1 程序別警示的後半：明細加總後重算程序別，與 Step 1 結果不同時再警示一次。
4. 產出依 `represented_side`：
   - 代理原告：9A 起訴狀骨架；另產「對方可能答辯要點（預演用，非書狀）」，內容來自對造模擬方的 items、`defeat_conditions`、`prep_items` 與 `pending.opponent`，不套書狀格式。
   - 代理被告：9B「預先準備的答辯狀草稿」（只支援起訴前，標題標明）；另產「對方可能起訴要點（預演用，非書狀）」。9B 的「對原告主張之陳述」素材是被告 Stage 3 的 `rebuttal`，這在答辯狀是正當用途。
   - UI 的書狀選擇改為依代理方顯示可選項目。
5. 9C 補產規則同上；舊案件（無 `represented_side`）維持現行 9A／9B 行為。
6. `record_pleading` 檢查 `citations` 必須是字串陣列，且每筆都能在該案 `case_citation_checks` 找到 `published` 紀錄（同 Step 8 第 9 點）；格式不對就拒絕並說明正確格式，不靠調度員轉換。

**檔案**：`SKILL.md` Step 9、`main.py cmd_pleading_source`、`database/db.py record_pleading`、`database/schema.py`（`pleading_drafts` 存 `claim_breakdown`）、`ui/app.js`
**驗證**：
- 用 08-08 test-002 起訴狀（第一段即寫「被告主張…」）與 003 起訴狀（留著「本方」）當反例，應被擋下。
- 用 Codex real-001 的原告起訴狀（`docs/live-run-records/codex-real-2026-10-31-001/pleading_draft_plaintiff.txt`）當固定測試案例，應被擋下。這是換模型、真實案件後唯一實際發生的 P2，而 real-002 原本沒產生書狀，沒有前後可比，所以 P2 的修正效果用這個測試證明，不靠重跑。
- `citations` 傳物件陣列時被拒絕。
- 明細加總不符時有警示；`to_confirm` 的金額出現在律師附註而非訴之聲明。
- 代理原告時不會產生 9B 格式的答辯狀。

## Step 10 — 回報

**問題**：回報由主 agent 自己寫成文字，又多一層 LLM 轉述，前面守住的「待確認」可能在最後一步被改寫；順序是強弱評估在前，但律師開庭前最需要的是待辦與準備事項。

**已定案（2026-10-31 討論）**：回報由程式從資料庫組出，主 agent 原樣轉交；順序依律師的下一步排；UI 總覽分頁用同一個結構。

**改什麼【A】**
1. 新增 `python main.py report --case-id <id>`：固定範本，從 DB 組出回報。主 agent 只原樣轉交，不改寫、不摘要（`SKILL.md` Step 10 改寫為這一句）。這是「調度改由程式控制」的第一步。
2. 回報順序：
   1. 待辦，依 `pending.holder` 分三類：問當事人／對方可能有／向第三方或法院調閱。
   2. 對方可能怎麼打 × 我要準備什麼：對造模擬方 items、`defeat_conditions`、`prep_items`，每筆標「預測，非對方實際主張」。
   3. 逐爭點強弱表（Step 7 `issues`），引述處附原文。
   4. 我方弱點：代理方 `internal_notes`（含 `update_conditions`、`prep_responses`）。只出現在給使用者的回報。
   5. 書狀骨架、金額明細與律師附註。
   6. 過程紀錄：`status_changes`、`citation_set_change`、引用查證結果（含「需說明」「不支援」）、起訴審查的程序事項。
   7. 結尾聲明照舊：「本結果為爭點分析與書狀骨架初稿，非法院判決預測，語氣潤飾與正式訴狀撰寫仍需律師覆核。」
3. UI：「總覽」分頁改成與回報相同順序，第 1、2 塊置頂；其他分頁只改名（去掉「死穴」「立場位移」「弱點」）。

**檔案**：`main.py`（`report`）、`SKILL.md` Step 10、`ui/app.js`、`server/app.py`（總覽 API 回傳同一結構）
**驗證**：`report` 輸出中每個 `to_confirm` item 都保留「待確認」字樣；對方相關段落每筆都有「預測」標示；不含對造模擬方的 `internal_notes`。

---

## 跨步驟：調度從 prose 改成程式

**已定案（2026-10-31 討論）**：報告前只做一半——規則搬進 `record` 等驗證，摘要、角色可見檔、查證清單、回報都由程式產生（已涵蓋在上面各步）。完整的狀態機留到報告後【B】。重跑時沿用 Codex 已寫好的 `docs/live-run-records/codex-real-2026-10-31-001/run_control.py` 調度。

報告後【B】：
- `engine/pipeline.py`：固定的狀態機（或 LangGraph），每個節點：版本化範本 → 呼叫模型 → pydantic 驗證 → 落地輸入、輸出、範本雜湊。
- 調度員不再是 LLM；摘要、角色可見檔、查證清單都由程式產生。
- 可續跑、可在「待當事人確認」處暫停，讓律師補資料後繼續（human-in-the-loop）。
- 檢驗網頁（`court_review.html` 的作法）變成系統內建的除錯檢視。

---

## 驗證計畫：同案重跑

**做法**
- 對象：real-2026-10-31-002（有具體失敗可對照：時效抗辯被撤、Step 8 失敗、沒有書狀）。
- 用 Codex、同一模型與 reasoning effort（gpt-6-astra／ultra），沿用 `docs/live-run-records/codex-real-2026-10-31-001/run_control.py` 等腳本。
- 基準是 Codex 那次凍結的範本與輸出；新流程至少跑 1 次，時間允許跑 2 次。Codex 每案牆鐘約 3.5 小時（含等待與授權）。
- 輸入只做最小轉換：`represented_side=plaintiff`；原 `facts_summary` 原樣放進 `plaintiff_facts`；`claims` 拿掉「原起訴」的「原」；`claim_amount` 留空（請求是比特幣）。輸入格式本身也變了，這點要列為對照的限制。
- 調度環境（`run_control.py`）：
  - 每次呼叫都開 `disable_nested_agents`。早期 Step 8 有巢狀 agent 活動，而 `features.multi_agent=false` 單獨用不夠。
  - `verify_prompt.txt` 寫死輸出目錄，並禁止既有引擎以外的 HTTP。001 有兩次引擎外的 urllib 探測，也有 5 份產物寫錯到 `database/` 底下。
  - 沿用 Codex 的環境預檢，避開 Stage 1 首次環境失敗（兩案各 2 次）。

**指標（跑之前固定，跑完不改）**
1. 被告最終輸出中，時效（二年、五年）與第182條項目的 status：`to_confirm` 為好，`withdrawn` 為差。
2. Step 8 是否通過；不通過時，原因是否為已知且照實列出。第205條應為 `version_unverified`，不應標 `published`。
3. 書狀是否產出；起訴狀觸發字樣檢查的次數（P2）。real-002 原本沒有書狀，所以 P2 只看「產出了且通過檢查」，改善的證據改用 Step 9 的 001 固定測試。
4. 所有「自承／自認／不爭執」語句能追到 item id 的比例。
5. 「待當事人確認清單」是否產出；與 holdout 真實抗辯對照，涵蓋幾類。
6. 各角色輸出字數（可讀性）。

**限制**：單案、每邊一到兩次，只能說方向，不能說統計結論；範本改版後新舊輸出格式不同，比較只看上面的指標。

---

## 執行順序（決賽前，報告日在 11/7 之後）

**已定案（2026-10-31 討論）**：分三層，每層做完都可單獨合併；UI 放第三層（取代 Step 1「UI 這週一起改」的決定）。全部估約 7.5–8.5 天，不含重跑與評估（依 Codex 重試紀錄補了 Step 8 第 8–12 點，多半天）。

| 層 | 工作 | 對應步驟 | 估時 |
|---|---|---|---|
| **第一層：重跑最低需求** | ① 查證修正：文件身分、白名單、每案紀錄、第一二層比對、`verify_prompt.txt`、`version_unverified`、`verify-gate`、自動重試、`record-verification`、落地時檢查法規 | Step 8 | 1.5 天 |
| | ② 案件欄位、`role-view`（事實編號、去 `source_note`）、程序別警示；**不含 UI** | Step 1 | 半天 |
| | ③ items、`internal_notes`、`precedent_notes`、狀態轉移與撤回檢查、程式摘要、三準則 | Step 2、4、5 | 1.5 天 |
| | ④ 法官 `question_type`、`prep_items`、`issues`、「自承」檢查 | Step 3 | 半天 |
| | ⑤ 錨點改寫（`defeat_conditions`、`pending`、`status_changes`、`citation_set_change`） | Step 6 | 半天 |
| | ⑥ 評估只改約束、覆蓋檢查、「待確認」字眼檢查；表格留第二層 | Step 7 一部分 | 半天 |
| | ⑦ 9A 素材與字樣檢查（含「對造」與流程用語）、引用格式檢查、001 起訴狀固定測試、依代理方決定產出 | Step 9 一部分 | 半天 |
| | ⑧ `SKILL.md` 改寫；pytest 全過；real-002 輸入轉換與調度設定；重跑並依指標評估 | 驗證計畫 | 半天＋重跑 |
| **第二層** | 逐爭點表格與參考等級；金額明細；`report` 指令 | Step 7、9、10 | 1.5–2 天 |
| **第三層** | UI：建案表單、總覽、評估表格、改名、引述帶出原文、書狀選項 | Step 1、6、7、9、10 | 1.5 天 |

- 第一層 ① 本身就有價值，就算後面來不及也能先合併。
- 第一層 ③ 是核心：Step 4、5 的撤回檢查擋住 real-002 的時效問題，是前後對照圖的主角。
- 重跑在背景執行，同時做簡報。
- 簡報不依賴重跑結果：重跑成功是加分的一張對照圖；沒跑完就以本計畫當「修正架構」那一張的內容；畫面用設計示意圖代替。
