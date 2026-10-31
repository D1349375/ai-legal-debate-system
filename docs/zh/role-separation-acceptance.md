# 職責分離改版：實作前固定驗收標準

制定日期：2026-10-31。依據：[role-separation-redesign-plan.md](role-separation-redesign-plan.md)。

本文件由獨立驗證 agent 先於產品實作制定；驗證 agent 只修改驗收文件與測試，產品實作由其他 agent 負責。範圍為計畫三層全部【A】項目；完整狀態機、歷史法條版本下載等【B】項目不列為本次完成條件。使用者最初要求001、002都重跑，後續已明確縮為**僅完整重跑002；001保留固定反例測試**，以後續指示為準。

**範圍修訂（使用者後續明確指示，由主 agent 傳達）**：`verify-gate` CLI、自動連線重試、`record-verification` 專用指令、每輪法條 `parse_citation`、新增書狀引用型態檢查五項移至【B】，不以其缺漏判本次失敗。下表保留原驗收設計供未來使用，其中 Q08/Q09 的新增閘門指令、Q10、Q11 的專用指令、Q12 的每輪解析、P03 的新增型態檢查均為延期；既有書狀引用 published 檢查仍須正常。歷史205條 `version_unverified`、未通過查證如實列「律師待核」、P2禁詞與001固定反例、182條／五年時效保留、輸入與調度紀錄仍列本次必要條件。這是授權範圍變更，不是驗證通過後降低標準。

每項以實際輸入／輸出、資料庫內容、CLI 退出碼、HTTP 回應或可操作的 UI 驗收。程式能確認的行為不能只以閱讀 prompt 或實作者自述代替。拒絕案例必須確認沒有寫入非法資料；成功案例必須確認輸出資料可被後續階段使用。

## 驗收矩陣

| ID | 計畫 | 驗收輸入或動作 | 必須結果 | 方法 |
|---|---|---|---|---|
| C01 | 1 | 新案省略／非法 `represented_side` | 拒絕；原告／被告兩種合法值可建案 | CLI／API |
| C02 | 1 | 三欄事實各含多行，一行有 `〔書證：email〕` | 每則有唯一穩定 F 編號；書證與陳述可區分、書證名稱保留 | CLI／單元 |
| C03 | 1 | 代理原告且填 `defendant_facts` | 明示為使用者轉述／書證所載的對方說法，不能標為被告親述 | CLI |
| C04 | 1 | 三角色 `role-view`，原案有 `source_note` 與 holdout 字號 | 均不含 `source_note` 與其內容；明示誰有當事人、所有案件為起訴前 | CLI／洩漏哨兵 |
| C05 | 1 | 舊案只有 `facts_summary` | 可產生角色檔；原文放代理方欄，來源為陳述；不要求手動改資料庫 | 相容性 |
| C06 | 1 | 金額空白、100000、100001、500000、500001 | 分別為待確認、小額、簡易、簡易、通常；警示不阻擋；案件類型簡易例外不自行推定 | 單元／API |
| C07 | 1 | claims 含「原起訴」「變更聲明」 | 起訴前限制有可見警示；不新增與既定設計矛盾的程序階段欄 | CLI／API |
| C08 | 1,8 | 程序金額門檻上線前查證 | 保存由既有查證引擎核對現行民訴 427、436 之 8 的證據 | 引擎實查紀錄 |
| R01 | 2 | items 缺必要結構、重複 id、非法 kind/status/state | `record` 拒絕且 DB 不落地 | CLI 對抗 |
| R02 | 2 | 要件 source 指不存在 F 編號；推論缺根據 | 拒絕；合法 F 編號與附根據 inference 可落地 | CLI 對抗 |
| R03 | 2 | `position_basis` 引不存在／to_confirm／含 unknown 要件 item | 拒絕；明確 asserted 且要件已確定的合法引用可落地 | CLI 對抗 |
| R04 | 2 | 過長 position／argument | 依明定上限拒絕、回傳可修正原因；argument 上限 8000 字或文件明定等價寬鬆值 | 邊界值 |
| R05 | 2 | 對造 factual_hypothesis 被寫成 asserted | 拒絕；合法假設保留 to_confirm、需求與 holder | CLI 對抗 |
| R06 | 2–5 | 我方／對造內部備註各放不同哨兵 | 己方後續可見自己的備註；對造與法官不可見；我方使用者回報可見我方備註 | 跨角色洩漏 |
| R07 | 2,8 | 引用判決缺 precedent_notes／原文／日期等必要資訊 | 拒絕；記憶候選只進 precedent_leads、不能成為正式引用 | CLI 對抗 |
| J01 | 3 | `based_on` 指不存在／錯方 item | 拒絕；合法 `side:item` 加說明可落地 | CLI 對抗 |
| J02 | 3 | 對造收到 factual 題；我方收到 factual 題 | 前者拒絕；後者允許且列入 own_client 待辦 | CLI／彙整 |
| J03 | 3 | prep item 缺 true 假設標記、affects 不存在、holder 非法 | 拒絕；合法 prep item 僅進我方準備資料與使用者回報 | CLI 對抗／洩漏 |
| J04 | 3 | 「自承／自認／坦承」指向 to_confirm 或法律推論 | 拒絕；不得把一方沉默當雙方不爭執 | 固定反例／對抗 |
| J05 | 3 | `uncontested_points` 僅一方 asserted／兩方內容不一致 | 拒絕；雙方 asserted 且同內容事實才可列不爭執 | CLI 對抗 |
| J06 | 3,7 | 法官 issues 的 item 參照、疑似事實題標 legal | issue 參照存在；「有無證據／是否持有／為何」標人工複查 | CLI |
| T01 | 4,5 | 後一輪遺漏前輪任一 item | 拒絕，不可用刪除取代撤回 | CLI 對抗 |
| T02 | 4,5 | asserted/to_confirm → withdrawn 缺理由／理由為資料不足 | 拒絕；二年、五年時效與 182 條皆用同規則 | 固定 real-002 反例／對抗 |
| T03 | 4,5 | 對造以 strategy 撤回；我方有說明以 strategy 撤回 | 前者拒絕；後者允許 | CLI 對抗 |
| T04 | 4,5 | record_negates 缺真實 F；opponent_defeats 缺真實對方 item | 拒絕；合法參照與理由可撤回並保留變化 | CLI 對抗 |
| T05 | 4,5 | 待確認資料無新增支持卻變 asserted | 拒絕；未知不能被改成沒有／自認；原始限定語保留 | CLI 對抗 |
| T06 | 4,5 | 我方 update_conditions、對造 defeat_conditions | 我方 falsifier 為空且不公開 update_conditions；對造公開條件指自己 item 並進準備清單 | DB／洩漏 |
| T07 | 4 | 對造收到誤標事實題 | 固定轉列準備清單回應，相關 item to_confirm；我方 prep_responses 僅內部可見 | 輸出／模板審查 |
| T08 | 4,5 | `summary` 包含 to_confirm 與 unknown 要件 | 保留原文限定語，含 id/label/kind/status/unconfirmed_facts/公開條件/引用，不含 internal_notes/prep_items | CLI／洩漏 |
| T09 | 5,9 | Stage3 claim_statement 與 rebuttal 各放不同哨兵 | 兩者獨立儲存；9A 只拿 claim_statement 與 asserted items | CLI／洩漏 |
| A01 | 6 | 新協議彙整 | 有 defeat_conditions/pending/status_changes/citation_set_change；不再拿 falsifier 當 weak_points | 純函數／CLI |
| A02 | 6 | own_client/opponent/third_party 各一需求、法官事實題與 prep | 三類穩定分流、保留來源與 item/問題 id；不以語意臆測改類 | 純函數 |
| A03 | 6 | 同判決字號只差判決／裁定或項款格式 | 正規化後 citation_set_change 為 0 | 純函數 |
| A04 | 6 | item 跨三輪狀態變化與撤回理由 | status_changes 列正確輪次、前後狀態與理由 | 純函數 |
| A05 | 6,7 | 法官錨點投影／舊協議案例 | 法官僅見 defeat_conditions/pending/procedural_issues；不見歷程與內部備註；舊版輸出仍可使用 | CLI／相容性 |
| V01 | 7 | 評估引用錯方、錯輪、不存在 item | 拒絕；合法 `side:id@S<n>` 成功並可取回原文 | CLI 對抗 |
| V02 | 7 | 敘述狀態改變但 status_changes 無變化 | 拒絕；須附兩輪有效參照及實際變化 | CLI 對抗 |
| V03 | 7 | 含 to_confirm item 的句子沒有「待確認／若」 | 拒絕；有合法限定語可通過 | CLI 對抗 |
| V04 | 7 | 錨點回應缺一筆，或將條件寫成已發生 | 覆蓋檢查拒絕缺漏；所有條件均保留條件性 | CLI 對抗／人工實質 |
| V05 | 7 | 「相互印證／佐證」同句只引用 0/1 個 F、兩個 item 或不存在 F | 拒絕；至少兩個不同且存在 F 才可通過機械檢查 | CLI 對抗 |
| V06 | 7 | 高／中／低三組事實與狀態 | 程式依計畫算 reference_grade；法官改級無 grade_reason 拒絕；issues 沿用法官 issue_id | 單元／CLI |
| Q01 | 8 | 114 台上 1945 未給日期／指定 20260513 | 前者 ambiguous 並列所有候選；後者取實體判決 | 語料庫固定回歸 |
| Q02 | 8 | 銀行法29、民法債編施行法、民訴施行法、未知法律 | 前三者可解析；未知法律 unsupported_law 而非 unparseable | 單元 |
| Q03 | 8 | 本案／另案／多次 run 的查證 | 每案每次紀錄獨立，必有 case_id/run_id/時間/來源/理由；不覆寫他案實質支持判斷 | DB |
| Q04 | 8 | doc_type 與全文不符；quote 非全文子字串 | 所有 Stage1–3 與評估正式判例在落地前拒絕 | 語料庫對抗 |
| Q05 | 8 | case_cause 不同，無／有 analogy_reason | 無理由拒絕；有理由標需說明，交獨立查證角色第三層判斷 | 語料庫對抗 |
| Q06 | 8 | 115 台上 447 醫療駁回裁定作車禍判決 | 文件身分及摘句檢查阻擋，不能 published | 固定反例 |
| Q07 | 8 | `108年民法第205條`、修正前、item 指舊法 | 一律 version_unverified，查到現行條文也不能 published | 單元／CLI |
| Q08 | 8 | gate 含 unsupported_law/version_unverified | 評估可發布且列律師待核；書狀採用這些引用則拒絕 | CLI／DB 對抗 |
| Q09 | 8 | gate 含 not_found/ambiguous/network_error 或未查證 | 非0退出且列原因；verdict/pleading 共用閘門，不能繞過 | CLI／DB 對抗 |
| Q10 | 8 | SSL／timeout 先失敗後成功、持續失敗 | 自動重試2–3次；持續失敗 network_error；查無 not_found | 受控網路故障 |
| Q11 | 8 | `record-verification` 寫查證結構化輸出 | 檢查格式、合法狀態與理由，僅寫本案紀錄；所有失敗狀態也保存 | CLI／DB |
| Q12 | 8 | record 遇不支援法規 | 當場標記並告知角色、不拒絕主張；最後採用引用需獨立第三層查證 | CLI／調度實查 |
| P01 | 9 | pleading-source 含內部備註／反駁／prep／to_confirm 哨兵 | 9A 素材不含任何哨兵；僅 claim_statement 與 asserted items | CLI／洩漏 |
| P02 | 9 | 起訴狀含計畫列出任一禁詞，含大小寫 Stage | 拒絕且未寫入 DB；固定 real-001 舊起訴狀被拒絕 | 參數化對抗／固定反例 |
| P03【B，新增檢查延期】 | 9 | citations 是物件陣列或含非本案 published 引用 | 未來拒絕並說明字串陣列格式；本次只保持既有 published 檢查正常 | DB／CLI |
| P04 | 9 | breakdown 引不存在 F／item；缺 basis 且缺 formula | 拒絕；合法明細合計與 claim_amount 不同則警示不阻擋 | 邊界／DB |
| P05 | 9 | breakdown 指 to_confirm 金額 | 該筆金額不進聲明合計，列律師附註；明細合計重算程序警示 | DB／CLI |
| P06 | 9 | 新原告／被告案，舊案、9C補產 | 新案只可產代理方正式骨架，對造為預演要點並標非書狀；被告標起訴前準備草稿；舊案相容 | CLI／API |
| O01 | 10 | report 同案重複輸出 | 由程式固定次序：待辦→對方預測→爭點表→我方內部備註→書狀/明細→歷程→聲明 | CLI／快照 |
| O02 | 10 | report 含兩方 private 哨兵、數個 to_confirm | 只出我方 private；每個未知標待確認，每筆對方項標預測，包含律師待核查證與程序問題 | 洩漏／CLI |
| U01 | 1 | UI 建案 | 代理方必填、三欄事實及範例、金額及送出前程序警示；案件頁三欄與書證標記 | UI 操作／API |
| U02 | 6,10 | 新版與舊版總覽 | 新版與 report 使用同結構、待辦與預測置頂、新名稱；舊版協議正常顯示 | UI／API |
| U03 | 7 | 爭點表及引用 | 有等級／理由／準備欄，引用能看到實際輪次原文；不只顯示 id | UI 操作 |
| U04 | 9 | 切換代理方書狀選項及補產 | 原告不顯示正式被告答辯狀選項；被告只選己方草稿，對方用預演名稱 | UI／API |
| W01 | 跨步驟 | 實際各節點輸入與範本、SKILL.md | 角色檔／摘要／查證清單／回報由程式產生；三準則、判決全文、角色區分、限定語完整；禁止直接讀原 case.json | 靜態＋重跑輸入審計 |
| W02 | 跨步驟 | 全套既有離線測試及新增驗收 | 全通過；網路測試分列真實結果，不把跳過當通過；測試不得破壞使用者基準檔與既有 DB | pytest |

## 同案重跑的完成條件與固定指標

依使用者後續指示，對 **002至少完整執行一次**新流程；001僅執行舊起訴狀固定反例，不列完整模型重跑完成條件。保存002獨立目錄、輸入轉換、凍結範本與雜湊、模型與 reasoning effort、每次呼叫與重試、節點退出碼、查證結果、書狀、程式回報、評估指標。模型使用計畫既定 `gpt-6-astra`／`ultra`；每次呼叫禁巢狀 agent。必須保存環境預檢；查證輸出限制本次目錄，只透過既有查證引擎連線。不得只啟動背景工作便宣告重跑完成。

輸入做計畫最小轉換並保留原始檔：代理原告、原 facts_summary 原樣放 plaintiff_facts、claims「原起訴」改「起訴」、002 非金錢請求 claim_amount 留空。001 若原資料可確定金額仍須明記轉換與來源，不自行推導 holdout 事實。

| 固定指標 | 計算與判準 |
|---|---|
| M1 | 002被告最終二年時效、五年時效、民法182條三項逐筆列 id/status；資料不足應保留 to_confirm，不得 withdrawn 或消失。合法事實／法律擊破撤回須另列理由與參照，不能把所有撤回自動記為成功。 |
| M2 | Step8是否通過及非通過原因；歷史205必為 version_unverified，不能 published。評估可放行與書狀可引用分開記。 |
| M3 | 書狀實際產出及落地成功；P2禁詞檢查觸發次數包括重試；001舊起訴狀固定回歸必須被擋。002無舊書狀，不能聲稱P2前後改善比例。 |
| M4 | 「自承／自認／不爭執」語句總數、有效item/輪次參照數、比例；零分母標不適用。可機械追溯不等於語意正確，另列人工抽核。 |
| M5 | 待確認清單存在且按holder分流；與隔離的holdout真實抗辯對照列涵蓋類別與數量，不能在角色輸入使用holdout。 |
| M6 | 按案、角色、輪次列輸出中文字數／總字元數，明列計算口徑，不以字數單獨推斷品質。 |

## 固定限制

- 程式可檢查結構、編號、輪次、狀態、原文子字串及近似限定詞，無法證明自然語言描述與原文語意完全相符，也無法判斷題型標記是否實質正確。
- 事實編號不同不必然代表來源獨立；兩個F編號只是同源自證的最低防線，仍需人工核對來源。
- 第三層支持性判斷必須由獨立查證 context 執行；產品實作單元測試不能取代該步。
- 單案少次重跑、輸入schema與範本改版，僅能比較上述固定指標方向，不能作統計結論。
- 網路、模型額度、授權、工具不可用等阻礙須照實記錄；不得偽造查證或以stub產物當真實重跑完成。

## 驗證證據

初始狀態：標準已固定，以下所有項目尚待執行驗證。測試命令、退出碼、失敗修復與逐項結論記於 [role-separation-verification.md](role-separation-verification.md)。
