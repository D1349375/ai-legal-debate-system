---
name: legal-debate
description: 起訴前民事爭點準備流程；以 represented_side 區分我方代理人與沒有當事人的對造模擬。三輪論證、法官訊問與評估、獨立引用查證、己方書狀骨架、程式回報。
---

# LegalDebate 職責分離調度

主 agent 是調度與記帳者。法律判斷交角色，摘要、角色可見檔、準備清單、錨點與最終回報交程式。禁止自己改寫角色的實質內容、補新事實、刪抗辯或繞過落地驗證。

固定流程：案件→既有起訴審查→Stage1→法官訊問→Stage2→Stage3→機械彙整→評估草稿→獨立引用查證→評估落地→己方書狀骨架→程式回報。不得自行增加辯論輪次。

所有指令從專案根目錄執行 `python main.py ...`。所有暫存輸入、輸出放本次執行目錄；原始案件檔只由調度員讀，不能直接交任何角色。

## Step 1 — 案件輸入與角色可見檔

新案必有 represented_side=plaintiff|defendant，三欄 uncontested_facts、plaintiff_facts、defendant_facts 每行一則；書證寫「〔書證：名稱〕內容」。uncontested_facts 是使用者預期雙方不爭執，不代表法院已確認。對方事實欄是使用者轉述或書證所載，不當成對方親述。

只支援起訴前。claim_amount 為新臺幣整數，非金錢請求留 null；10萬以下小額、50萬以下簡易，僅警示不阻擋；類型例外由律師確認。claims 含「原起訴」「變更聲明」須警示。

```
python main.py case --json <案件檔>
python main.py role-view --case-id <id> --role plaintiff
python main.py role-view --case-id <id> --role defendant
python main.py role-view --case-id <id> --role judge
```

將各輸出原樣存不同角色檔；所有範本的 {CASE_FACTS_PATH} 只填該角色的程式投影檔。source_note、holdout、原始 case.json 不出現在角色輸入。舊資料庫案件自動沿用 facts_summary；舊封存輸入才可明示 --legacy 匯入。

立場檢索詞以 engine.stance_rag.build_stance_terms 取得，不能自行增刪。保持先窮舉候選、再平行檢索的法律分析方式。

## Step 1.5 — 起訴審查（既有規則不變）

僅在使用者提供統編時執行 party；沒有統編不得猜測或自行以名稱選一家公司。自然人與無統編的一方不查，未查不等於無程序問題。

```
python main.py party --ban <統編> --case-id <id> --role plaintiff
python main.py issues --case-id <id>
```

程序事項原樣給雙方，原告對 ex_officio 項以「程序補正(<id>)」回應；清算人不明就寫待查，不編造。解散不等於不得為被告。249條支持逾期未補正裁定駁回，115台抗105支持職權調查實際代表權，不得並列同括號造成錯誤命題。

## Step 2 — Stage 1（雙方獨立）

分別開乾淨角色，逐字使用 templates/stage1_prompt.txt，只填既有佔位符。Stage1 不得互看對造輸出；每一輪收到兩份完整有效 JSON 後才落地任何一方。

items、position_basis、internal_notes、precedent_notes 由 record 強制驗證。代理方有當事人；對造模擬沒有當事人，產 legal/evidence_gap/factual_hypothesis 三種攻擊，假設必為 to_confirm。

判決須本輪讀全文並附文件日期、文種、案由、摘句與命題；記憶候選只進 precedent_leads。資料沒寫的事寫待確認，不可寫成有或沒有。

```
python main.py record --json <角色輸出>
```

拒絕時將精確錯誤交回原角色修正，不能調度員自己補法律內容。

## Step 3 — 法官訊問與爭點

用 role-view --role judge 取得雙方公開 position/argument/items，不含任何 internal_notes。套 templates/judge_question_prompt.txt。整份 questions/prep_items/issues/uncontested_points JSON 加 case_id 後一次 record。

based_on 指 side:item，對造只能 legal 題；需對方事實的問題改為假設 prep_items 給代理方。不得把未知、沉默或條件句寫成自承／自認／不爭執。

```
python main.py record --json <法官批次JSON>
python main.py prep-list --case-id <id> --role <代理方>
```

prep_items 只給代理方與使用者，不進對造輸入、不進書狀。後續 issues 沿用法官 issue_id。

## Step 4 — Stage 2

先重新產各方 role-view、對造 summary；不能主 agent 摘要。

```
python main.py summary --case-id <id> --side plaintiff --stage 1
python main.py summary --case-id <id> --side defendant --stage 1
```

各方只拿己方完整前輪、程式對造摘要、法官問題的角色投影；代理方另外拿 prep-list。套 templates/stage2_prompt.txt。代理方逐筆以 internal_notes.prep_responses=[{id,response}] 回應準備清單，只留內部。

法官若誤述可用 item id 更正。三準則為不重複、開新法律視角、直接回應，不要求新事實、新引用或換字。對造誤收事實題時答「此為事實問題，對造模擬無從回答，轉列準備清單」，相關 item 維持 to_confirm。

我方 update_conditions 只存 internal_notes，falsifier 空字串；對造公開 defeat_conditions 指己方 item。撤回須 fact_ids 或 opponent item_ids 依據；strategy 僅代理方可用。「日期不足」「無本人事實」不是撤回理由。二年、五年時效與民法182條同樣不能因資訊缺口消失。

## Step 5 — Stage 3

套 templates/stage3_prompt.txt，輸入己方完整S2及程式對造S2 summary。保留全部 item id。只收斂 asserted，to_confirm 保留為待當事人確認清單。claim_statement 與 rebuttal 分開儲存；最終 position 不得把未知寫成確定。

## Step 6 — 機械彙整

```
python main.py finalize --case-id <id>
```

新版輸出 defeat_conditions、pending（own_client/opponent/third_party）、status_changes、citation_set_change、procedural_issues。名稱是「準備事項」「主張狀態變化」「引用清單差異」。

法官只讀 role-view judge 的 anchors 投影：defeat_conditions、pending、procedural_issues；status_changes、citation_set_change 只給使用者。不要把完整 finalize 直接交法官。舊協議的 weak_points/position_drift 僅供舊案相容。

## Step 7 — 逐爭點強弱評估草稿

新乾淨法官 context，套 templates/verdict_prompt.txt，輸入程式公開三輪、原先 issues 與程式 reference_grade、法官專用錨點。錨點逐筆以編號回應，可以不同意；條件不是已發生事實。

所有引述附 side:item@S輪次；未知同句保留待確認或若。相互印證／佐證至少列兩個既存不同F編號。grade 不同於 reference_grade 必須理由。產出先存草稿，等實際採用的引用查證後落地。

## Step 8 — 獨立引用查證

引用清單用既有verify的唯讀投影產生，將stdout原樣存本次目錄（範本的{VERIFICATION_INPUT_PATH}），不由LLM重摘：

```
python main.py verify --case-id <id> --candidate-json <評估草稿JSON> --prepare-only
```

投影從DB三輪與評估草稿去重，包含citations、precedent_notes、version_hints、adopted_citations與命題。另開乾淨查證角色，不能讓論證／評估／書狀作者自查。套 templates/verify_prompt.txt，明寫唯一輸出目錄，禁止引擎以外的 HTTP。

```
python main.py verify <引用...> --case-id <id> --run-id <本次查證id>
```

獨立角色完成JSON後，調度員必須用同一既有verify入口接收結果（不是另加專用寫入指令）：

```
python main.py verify <引用...> --case-id <id> --precedent-notes <判例notes.json> --version-hints <歷史版本.json> --review-json <獨立查證結果.json>
```

該指令重新核對機械結果，拒絕把版本/文件失敗改為published；支持性只存本案紀錄。沒有第三層支持的判例不能進正式書狀。

有判例日期或適用舊法標記時，將程式產生的 notes/version_hints 以既有 verify 可選參數傳入，不能拿現行條文當舊法驗證。第一二層覆蓋所有正式判例，第三層只查最終實際採用者，須讀全文並寫支持／不支持的理由。查證輸出與每案紀錄保存，實質判斷不能改共用存在性快取。

**總流程不要求全部候選引用通過。** 未通過者完整列給律師，評估繼續，但實際採用的 citations_used 與書狀引用仍遵守既有 _assert_all_published。version_unverified／unsupported_law 只是待核，不能寫成不存在或 published。尤其108年民法205不能用現行16%版本冒充驗證。連線失敗可由調度員手動重試一次並記錄；不改引擎加入自動重試。

```
python main.py verdict --case-id <id> --json <已完成查證的評估JSON>
```

本輪不新增 verify-gate、record-verification 專用指令、不逐輪解析法條、不新增書狀引用格式檢查；依使用者縮減列【B】。既有實際引用落地檢查照常。

## Step 9 — 己方書狀與對方預演

```
python main.py pleading-source --case-id <id> --side <代理方>
```

素材必須程式產生，不能把完整 Stage3 直接套進起訴狀。9A 只有 claim_statement 與 asserted items；不含 rebuttal/internal_notes/prep_items/to_confirm。

- 代理原告：產民事起訴狀骨架；另由對造 items 與使用者回報提供「對方可能答辯要點（預演用，非書狀）」。
- 代理被告：產「預先準備的答辯狀草稿」；對原告主張之陳述可用己方 rebuttal；另給「對方可能起訴要點（預演用，非書狀）」。
- 舊案無 represented_side 時保留原9A/9B選擇；9C只補產使用者指定且允許的己方書狀，不重跑攻防。

9A 不預先回應抗辯；禁用「被告主張／被告抗辯／被告自承／被告或將／本方／對造」及「Stage／輪次／前輪／法官訊問／訊問攻防」。001舊稿為固定反例，不能為了通過檢查刪字後仍保留相同錯誤內容。

金額明細 claim_breakdown 每筆 name/amount/basis/formula/item；item 用 side:id@S3。basis 或 formula 至少一項。to_confirm 金額只列律師附註，不進訴之聲明。合計與claim_amount不同僅警示、重算程序提示。

骨架使用既有起訴狀結構：當事人、訴之聲明、事實理由、證物、此致與具狀人；缺案號/法院/姓名/證據則待填。被告草稿依民訴116、266條結構，不宣稱有官方答辯狀範本。所有正文實際引用只能 published。

```
python main.py pleading --case-id <id> --side <代理方> --draft-file <正文> --citations <引用字串陣列JSON> --claim-breakdown <明細JSON>
```

## Step 10 — 程式回報

```
python main.py report --case-id <id>
```

**主 agent 原樣轉交，不改寫、不摘要。** 固定順序：按holder分流待辦→對方預測與準備→爭點表與引述原文→我方內部備註→書狀與金額→歷程與律師待核→聲明。每個未知保留待確認，對方每筆標預測，不能出現對造私密備註。

「本結果為爭點分析與書狀骨架初稿，非法院判決預測，語氣潤飾與正式訴狀撰寫仍需律師覆核。」

## 重試與限制

若回覆被分類器中止或JSON無效，不採用不完整輸出、不得調度員補寫；以同範本交新context重派，附原始錯誤，最多2次，保存每次紀錄。仍失敗照實停止該節點並保留可續跑產物，不偽造完成。

模型工具不提供溫度設定，不在prompt假裝可設定。程式能驗結構、參照、狀態、文件與摘句，不能證明自然語言語意完全相符；畫面提供原文供律師核對。完整可暫停狀態機與歷史法條下載為【B】。
