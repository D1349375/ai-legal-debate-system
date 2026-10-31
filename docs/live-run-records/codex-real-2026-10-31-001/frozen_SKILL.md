---
name: legal-debate
description: >-
  LegalDebate 模擬法庭 orchestrator:跑單一民事案件的完整三角色四階段流程(案件輸入→商工當事人查核與起訴審查→立場驅動檢索→
  Stage1爭點整理→法官訊問→Stage2訊問攻防→Stage3辯論終結→機械死穴彙整→法官爭點強弱評估→
  引用查證→書狀骨架初稿(原告起訴狀、被告答辯狀))。觸發詞:「跑案件模擬法庭」「模擬攻防」「案件辯論」「/legal-debate」。
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
- **官方事實層(2026-10-27 串接)**:當事人是公司或商號、且使用者提供了統一編號時,逐一執行 `python main.py party --ban <統編> --case-id <case_id> --role plaintiff|defendant` 查核商工登記。**統編只能來自使用者**,不得自己猜或用名稱搜尋後自行選定(同名公司很多,選錯就是查錯人)。自然人或使用者沒給統編的一方不查,照實留空。
- 查核完成後進入 Step 1.5。

### Step 1.5 — 起訴審查(官方事實層,Stage 1 之前)
- 實務上法院收狀後先審查當事人能力與法定代理權,有欠缺而可以補正者,審判長定期間命補正,逾期未補正以裁定駁回(民事訴訟法第249條第1項)。最高法院115年度台抗字第105號裁定可見此流程:一審發現原告公司已解散、登記清算人非起訴所列代表人,即裁定限期補正,逾期後駁回;但該駁回裁定經高院廢棄、最高法院維持,理由是法院應依職權調查實際代表權,不得僅憑登記認定——所以本系統只提出命補正事項,不替法院下「應駁回」的結論。本系統在這個時點提出程序事項。
- 執行 `python main.py issues --case-id <case_id>`,把輸出存成程序事項 JSON。這是 `engine/party_issues.py` 依固定規則從登記狀態轉成的命補正事項(法定代理、當事人能力、當事人適格等),**不是 LLM 產出,你也不得自行增刪**。`notes` 裡寫著哪一方未查核或查核未完成——**未查核不等於沒有程序問題**,回報使用者時要照實說。
- 這份 JSON 是雙方共享的公示資料(起訴狀的當事人欄本來就有),在 Step 2 交給雙方;不違反 Stage 1「看不到對造輸出」的盲判定義。這一步不是加開辯論輪次。

### Step 2 — Stage 1 爭點整理(雙方獨立,可平行)
- 對 `plaintiff`、`defendant` 各開一個獨立 subagent(Agent 工具,一般用途即可),prompt **必須逐字套用** `templates/stage1_prompt.txt`,只填充 `{佔位符}`(`{SIDE}`/`{SIDE_LABEL}`/`{CASE_ID}`/`{CASE_FACTS_PATH}`/`{STANCE_TERMS}`/`{STATUTES_DIR}`=`corpus/statutes`/`{JUDGMENTS_DIR}`=`corpus/judgments`/`{PROCEDURAL_ISSUES_PATH}`=Step 1.5 的程序事項 JSON,沒有查核任何一方時仍要給)。
- **隔離鐵律**:兩個 subagent 互相看不到對方的 prompt 或輸出,這是 Stage1 盲判的定義。
- 收到原告 Stage 1 後機械核對:`ex_officio` 為 true 的每一則事項,原告 argument 都要有「程序補正(<id>)」段落(系統以 `engine.party_issues.cured_in` 判斷)。漏掉就退回同一個原告 subagent 補寫,**不得自己代寫補正內容**。這只核對有沒有回應,補正夠不夠由 Step 3 法官判斷。
- 收齊後各自存成暫存 JSON,執行 `python main.py record --json <path>` 落地(`stage=1`)。**兩方都拿到完整 JSON 之後才落地任何一方**(Stage 2、3 同理):先落地一方、另一方之後被安全分類器擋到放棄時,案件會卡在只有一方落地、又不能重跑的狀態(見文末「subagent 的回覆被安全分類器中止時」)。

### Step 3 — 法官生成訊問(獨立 subagent,基於 Stage 1)
- 把雙方 Stage1 完整輸出整理成一份 JSON 給法官 subagent 讀,prompt 套用 `templates/judge_question_prompt.txt`,`{PROCEDURAL_ISSUES_PATH}` 填 Step 1.5 的程序事項 JSON。法官先審查原告 Stage 1 的程序補正,只有補正不足時才追問;追問的 `based_on` 以「官方事實層(<id>):」開頭,UI 以此 id 對應追問與事項。補正足夠就不追問,這是正常結果,不要要求法官每則都問。
- 法官輸出的 `questions` 陣列,每一則各自存成暫存 JSON,執行 `python main.py record --json <path>` 落地(該 JSON 含 `question_text`/`target_side`/`based_on`,`main.py` 會依欄位自動辨識為訊問記錄,不是論證記錄)。每則各下一次指令,不要用 shell 迴圈或 `&&` 串接一次落地多則(UI 無人值守執行時,只有單一 `python main.py ...` 指令會被允許,迴圈會被拒)。
- `uncontested_points` 不落地資料庫(schema 未設對應欄位),但你要記下來,留給 Step 7(訴狀優先順序建議)與 Step 10(回報使用者)用。

### Step 4 — Stage 2 雙方應訊(可平行)
- 給雙方各自:自己的 Stage1 完整輸出 + **對造 Stage1 的結構化摘要**(你自己從對造 Stage1 JSON 萃取 `position` + 最強論點一句話 + `cited_statutes`/`cited_precedents`,不得把對造完整 `argument` 全文丟過去——這是刻意設計,阻擋修辭趨同,逼雙方正面對決論點而非模仿對方語氣)+ 法官本輪全部訊問。
- prompt 套用 `templates/stage2_prompt.txt`。收齊後 `python main.py record --json <path>` 落地(`stage=2`)。

### Step 5 — Stage 3 辯論終結(可平行)
- 給雙方各自:自己的 Stage2 完整輸出 + 對造 Stage2 的結構化摘要(同 Step 4 的萃取方式)。
- prompt 套用 `templates/stage3_prompt.txt`。收齊後 `python main.py record --json <path>` 落地(`stage=3`)。

### Step 6 — finalize(機械死穴彙整 + 分歧統計)
```
python main.py finalize --case-id <case_id>
```
取得 `mechanical_anchor_json`(`weak_points` + `position_drift` + `procedural_issues`),這是 Step 7 法官敘述不得違背的方向錨點。`procedural_issues` 取 finalize 當下最新的商工查核結果;若 Step 1 之後重新查核過,以這裡為準。

### Step 7 — 法官頒布爭點強弱評估(獨立 subagent,受 Step 6 錨點約束)
- prompt 套用 `templates/verdict_prompt.txt`,餵入完整三階段紀錄 + Step 6 的機械錨點 JSON。
- **這裡先不落地** verdict——要等 Step 8 查證通過,`citations_used` 全數 published 才能落地(見下)。

### Step 8 — 引用查證(獨立 subagent,涵蓋判決書引用;獨立 context 結構性強制)
- 收集 Step 2-7 所有輸出裡出現的全部 `cited_statutes` + `cited_precedents` + verdict 的 `citations_used`,去重。程序事項的 `legal_basis` 若被法官或雙方引用,同樣要查證,不因為是規則表帶出來的就免查。
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
  (JSON 含 `verdict_main_text`/`verdict_analysis`/`risk_map`/`mechanical_anchor_json`/`citations_used`)。`record_verdict` 若偵測到未 published 引用會直接拒絕落地(`ValueError`,`main.py` 回傳 exit code 1)——這是機械閘門,不是你的判斷空間,遇到報錯不要試圖繞過。
  `main.py verdict` 另會拒絕把民事訴訟法第249條與最高法院115年度台抗字第105號放在同一個括號裡的評估(並列讀起來像該裁定也支持駁回)。遇到這個報錯,把報錯原文交回同一個法官 subagent,請它只改這處引註的寫法後重新輸出;不要自己改寫評估內容。

### Step 9 — 書狀草擬:原告起訴狀 + 被告答辯狀(骨架版,2026-08-08 決定,不經 `taiwan-legal-pleading` skill 潤飾)
`taiwan-legal-pleading` skill 蒸餾已延後至 Phase 2(語料未到位,見 `noble-dancing-duckling.md`)。本階段書狀初稿改為**骨架版**,共有兩份可產:原告方的**民事起訴狀骨架**(9A)與被告方的**民事答辯狀骨架**(9B)。兩份各自獨立,素材分別只取該方自己的 Stage 3。

**產哪幾份由使用者決定**(2026-10-30 決定,讓使用者控制花費):使用者或 UI 觸發的指示寫明「本次要產生的書狀」時,只產列出的那幾份,沒列的不產,Step 8 也不必為只會用在沒產那份書狀的引用另做查證;沒有指示時兩份都產。沒產的那份之後可用 9C 補產。

**兩份共同的紀律**(9A、9B 都適用):
1. 把該方 Stage3 的 `position`/`argument`/`cited_statutes`/`cited_precedents` 直接套進骨架的對應欄位。**不做語氣潤飾、不做修辭改寫**,這是刻意的,語氣潤飾要等 Phase 2 律師語料到位才做。誠實跟使用者說明這是骨架版,不是最終可用書狀。
2. 只使用 Step 8 已查證為 `published` 的引用,未 published 的引用不得出現在書狀草稿裡。
3. 當事人欄(原 3a):有商工查核結果的一方,名稱、統編、地址照登記填;法定代理人只填查核結果 `legal_representative` 有帶入的人。有 bad 等級程序事項時(例如被告已解散),法定代理人欄寫「清算人(待查明:<程序事項要查的資料>)」,**不得照列原負責人,也不得編造清算人姓名**。答辯狀的答辯人就是被告,這條規則照樣適用在答辯人欄。
4. 案號、股別、受理法院、證物、具狀日期等攻防紀錄裡沒有的資料,一律留「(待填:…)」,不得編造。
5. 撰狀素材可用 `python main.py pleading-source --case-id <case_id> --side plaintiff|defendant` 取得(唯讀,印出該方 Stage 3 原文、對造 Stage 3 的 position 與引用、每條引用目前的查證狀態、商工查核與程序事項)。對造部分只有結構化摘要,不含對造完整論證,同 Step 4 的萃取紀律。

#### 9A — 原告民事起訴狀骨架
1. 用 Read 讀取 `corpus/pleadings/reference/司法院官方民事起訴狀範本_結構參考用.pdf`,取得訴狀欄位結構(案號/當事人欄/訴之聲明/事實及理由/證物名稱/此致/具狀人)。
2. 素材用原告方 Stage 3,依上方共同紀律套進骨架。
3. 落地:
   ```
   python main.py pleading --case-id <case_id> --draft-file <path> --citations <path> --side plaintiff
   ```
   (`--citations` 是一個 JSON 檔,內容是這份書狀引用的 `citation_text` 陣列;`--side` 省略時視同 plaintiff)。`record_pleading` 做 published 查證閘門。

#### 9B — 被告民事答辯狀骨架
**本機沒有官方答辯狀範本檔**:`corpus/pleadings/reference/` 只有司法院的起訴狀範本。不要為此上網找或下載範本。答辯狀的欄位依民事訴訟法的書狀規定整理(已於 2026-10-29 經全國法規資料庫核對條文):第116條第1項(當事人書狀應記載當事人、法定代理人、訴訟事件、應為之聲明或陳述、證據、法院、年月日等)、第266條第2項(被告之答辯狀應記載答辯之事實及理由,及同條第1項第2款、第3款之事項,即證明應證事實所用之證據,以及對他造主張之事實及證據為承認與否之陳述;如有爭執,其理由);欄位排列比照起訴狀範本。在交給使用者的說明裡照實寫明這份結構不是來自官方答辯狀範本。

骨架(由上而下):
1. 標題「民事答辯狀」;案號、股別:「(待填:法院分案後之案號／股別)」。
2. 當事人欄:答辯人(即被告)及其法定代理人、訴訟代理人;被答辯人(即原告)及其法定代理人。依共同紀律第 3 點。
3. 「為<案由>事件,依法提出答辯事:」(案由取案件 `case_type`)。
4. **答辯聲明**(固定格式文字,不是引用,不附條號):
   - 一、原告之訴及假執行之聲請均駁回。(案件 `claims` 沒有假執行聲請時,改為「原告之訴駁回。」)
   - 二、訴訟費用由原告負擔。
   - 三、如受不利判決,願供擔保請准宣告免為假執行。(是否保留由律師決定,骨架照列)
5. **事實及理由**:
   - 一、原告主張要旨:只寫 `opponent_stage3_summary.position` 與案件 `claims` 的原文,不得替原告補寫論證。
   - 二、對原告主張之陳述:就原告主張的事實與證據,逐點寫被告承認或爭執;有爭執者寫理由。素材只取被告方 Stage 3 `argument` 中對應的段落,被告 Stage 3 沒有表示意見的點寫「(被告 Stage 3 未表示意見,待律師補充)」,不得自行代被告表態。
   - 三、被告抗辯:被告方 Stage 3 `position` 與 `argument` 中的抗辯(例如時效、清償、同時履行),附上 published 的引用。
   - 四、程序事項:有與被告相關的程序事項(例如被告已解散而法定代理人待查明)時照實列出;沒有就省略本點。
   - 五、結論:「綜上所述,原告之訴為無理由,請駁回原告之訴。」
6. **證物名稱及件數**:只列被告 Stage 3 論證中明確提到的證據;沒有就寫「(待律師補列)」。
7. 此致「(待填:受理法院)民事庭」;中華民國(待填)年(待填)月(待填)日;具狀人:答辯人(被告)、法定代理人、撰狀人(訴訟代理人),依當事人欄填寫,不明者留待填。
8. 落地:
   ```
   python main.py pleading --case-id <case_id> --draft-file <path> --citations <path> --side defendant
   ```
   查證閘門與 9A 相同。

#### 9C — 只替既有案件補產書狀(不重跑攻防)
已跑完 Step 1–8、但缺其中一份書狀的案件(2026-10-29 之前的案件只產了起訴狀;之後的案件可能只產了使用者選的那份),可以只跑缺的那份(9A 或 9B),不重跑任何攻防。觸發:使用者要求「替 <case_id> 產生答辯狀/起訴狀」,或 UI 以「補產書狀」方式觸發(指示會寫明本次要產生的書狀)。以下對每一份要產的書狀各做一次,`<side>` 為該份書狀的一方(起訴狀 plaintiff、答辯狀 defendant):
1. 執行 `python main.py pleading-source --case-id <case_id> --side <side>`。報錯「尚未完成 stage3」就停止並回報:這個案件還沒有該方 Stage 3,不能只跑 9C。
2. **不要**執行 `case`/`record`/`finalize`/`verdict`,也不要重產沒被要求的書狀;既有紀錄一律不動。
3. 素材中 `status` 為 `published` 的引用可以直接用。非 published 的引用如果要寫進書狀,先照 Step 8 的兩項任務另開乾淨的 subagent 查證(存在性 + 實質相關性);沒通過就不寫進書狀,不得改寫引用濫竽充數,並在回報中列出被排除的引用。
4. 依 9A 或 9B 骨架草擬、落地(`--side <side>`)。
5. 回報使用者:書狀骨架全文、哪些引用因未通過查證被排除、哪些欄位留待填,以及 Step 10 的結尾聲明。

### Step 10 — 回報使用者
逐案回報:
- 官方事實層:哪一方查核了商工登記、起訴審查產生哪些命補正事項、原告 Stage 1 如何補正、法官是否追問、最後是否補正完成;未查核的一方照實說未查核
- 雙方三階段立場摘要(Stage1 初始立場 → Stage3 最終立場,標出立場是否有位移)
- 法官爭點確認(哪些無實質爭議、哪些是真爭點)
- 機械死穴清單(`weak_points`,誰在哪個爭點有明確 falsifier)
- 立場位移統計(`position_drift`)
- 法官的爭點強弱評估與訴狀優先順序建議
- 骨架版書狀初稿(本次產生的那幾份;使用者只選一份或 9C 只補產一份時,照實說明另一份沒有產生)

結尾必附一句:**「本結果為爭點分析與書狀骨架初稿,非法院判決預測,語氣潤飾與正式訴狀撰寫仍需律師覆核。」**

## 落地紀律

- `record`/`finalize`/`verdict`/`pleading` 遇「已落地不可覆寫」報錯 = 該案件此階段已跑過,**不要試圖刪除或改寫**,向使用者回報即可。
- 任何案件層級的統計評估(如多案件命中率)不在本 skill 範圍——單案跑測不構成統計意義上的驗證,不要臨時手算了就宣稱結論。

## subagent 的回覆被安全分類器中止時

實跑時(2026-10-28 #3、2026-10-29 #4)subagent 輸出最終 JSON 時偶爾會被 Anthropic 的安全分類器中止(類別 `reasoning_extraction`)。這不是工具或 API 錯誤,subagent 會回報「回覆被安全分類器中止」、沒有交出完整 JSON。這個分類器有機率性,同一份 prompt 重派通常就能通過(#4 重派一次即成功)。處理方式:

1. 被中止的那份輸出不完整,不得採用、不得落地,也不得由你補完或代寫。
2. **另開一個新的 subagent**,用同一份範本逐字重派(佔位符照填)。不要用 SendMessage 叫原本那個 subagent 重寫:它已被告知不得再產出那段內容。也不要自行精簡或改寫範本來「避開」分類器,那樣會偏離範本、論證品質無從比較(#3 就是改寫後仍失敗)。
3. 同一個角色同一階段最多重派 2 次(含第一次共 3 次)。都被中止就停在這一步:已落地的階段保留;同一階段另一方即使已完成也先不要落地(只落地一方,之後整件重跑時會撞到「已落地不可覆寫」),在最後回覆寫明卡在哪一個 subagent、被中止幾次。
4. 每次中止都要在最後回覆照實列出(哪個 subagent、第幾次、最後是否重派成功)。依官方文件,`reasoning_extraction` 類別的中止(輸出前或串流中途)照樣計費(https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback ,「How refusals are billed」一節)。

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
