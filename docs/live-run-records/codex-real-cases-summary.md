# 真實案件基準實跑總報告（001、002；重試後初稿）

模型設定：**gpt-6-astra**；reasoning effort：**ultra**。以上為每個角色程序明確送出的CLI設定，未取得可獨立核實服務端模型修訂版的metadata。日期：2026-10-31。

**001已完成查證、評估發布及兩份書狀，確認一項P2流程錯誤；002仍停在Step8，沒有發布評估或產生書狀。** 本次補足原始查證及全文讀取證據，確認002另有法名解析、文件身分及歷史版本三類流程問題。原攻防、評估及範本未改寫，003未啟動。

逐案完整報告：[001 eval](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/eval.md)、[002 eval](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-002/eval.md)。兩案舊中斷版均保留於retry_step8/before_retry；001快照也保存本總報告舊版，新證據不回填舊次執行。

## 來源、選案與輸入

| 案件 | 來源判決 | 輸入摘要及條件 |
|---|---|---|
| 001 | [新北地院113年度訴字第3504號，2026-10-28，減少價金等](https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=PCDV,113%2c%e8%a8%b4%2c3504%2c20261028%2c1) | 原告主張113/3/19買屋、5/21交付、翌日發現漏水等；採原起訴974,000元及送達翌日5%利息。通常第一審、民法為主、超過50萬元，實質答辯、不爭執事項及分項爭點俱有，一部勝敗。 |
| 002 | [士林地院115年度重訴字第242號，2026-10-28，損害賠償](https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=SLDV%2c115%2c%e9%87%8d%e8%a8%b4%2c242%2c20261028%2c1&ot=in) | 原告主張108/6/25經LINE招攬、7/11交10BTC、十日後應得15BTC，後未給付；採原始15BTC及備位換價聲明。通常第一審重訴、民法為主、超過50萬元，有實質答辯、不爭執事項與爭點；使用者同意由交通案放寬為一般侵權。全部敗訴符合「最好一部勝敗」的偏好性條件。 |

兩份全文均由使用者貼上並提供專屬FJUD連結，未獨立成功抓取官網全文；來源紀錄保留user_pasted_full_judgment、retrieved_at=null。到庭只有實質攻防、代理及言詞辯論記載等間接支持，沒有直接出席筆錄；001爭點採法院分項判斷，沒有獨立爭點標題。不能聲稱選案條件已全部獨立核實。

輸入匿名並標明原告主張，只保留起訴前可用資料及原始聲明。001排除後來674,314元、200萬元減價、法院鑑定及6,000元結果；002排除後來10BTC／34,066,792元、刑偵自承、報案／起訴日、JM及法院結論。刪除理由、gold與判決全文仍在repo外。自然人未提供統編，商工查核跳過，issues照常執行並保留未查核限制。

建檔檢查未在corpus命中來源判決、真實當事人及法官。2026-08-01之後的裁判只能降低模型事前見過的可能，沒有訓練截點證據。兩份輸入仍有「原起訴」字樣，沒有結構化phase／基準日；角色詢問原訴或送達文件是階段歧義與補證現象，未直接算成捏造。

## 步驟完成及重試結果

| 步驟 | 001 | 002 |
|---|---|---|
| Step1–1.5 | case、檢索詞及issues完成；未做商工查核 | 同左 |
| Stage1–3 | 六份論證、14則法官訊問 | 六份論證、13則法官訊問 |
| Step6 | 錨點未改；引用集合位移原告0.4231／被告0.4510 | 錨點未改；原告0.5443／被告0.5814 |
| Step7 | 原評估JSON原生CLI發布成功，DB 1筆 | 評估JSON完整，未發布，DB 0筆 |
| Step8 | 採第3次，有73字串及5全文的執行證據，通過 | 第2次有111字串及13字號／15全文的證據，仍未通過 |
| Step9 | 原、被告書狀各1份，原生CLI皆exit0，DB 2筆 | 未產生兩份書狀，P2=N/A |
| Step10／事後評估 | eval及標註完成 | 停止回報、eval及標註完成 |

001第一次Step8因環境／工具問題停止，沒有最後回覆；第二次自報通過但缺完整原始工具／子程序證據，未採用。第三次初始73筆中72 published、民法130暫時SSL失敗，同引用重試後73字串全部published，歸一為60法條、5裁判；5全文核對亦通過。查證後才發布既有評估、取得原生pleading-source、另開兩個新程序撰狀並存檔。見[001查證稽核](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/calls/13_citation_verify_attempt3/retry_execution_audit.json)。

002第一次缺整批原始回傳的限制仍保留。本次111筆初始結果為107 published、3 unparseable、民訴195一筆SSL失敗；同入口重試195後，最新機械狀態為108 published、3 unparseable。正規化106身分並納入版本核對，最終102通過、4 draft：

- 民法債編施行法第10條之1、銀行法第29條、第29條之1：解析器不支援，不代表法條不存在。
- 民法第205條：現行文字存在，但不足以核實108年舊版；角色辨識後保守降draft，沒有發布候選試算。

所以002沒有執行verdict或pleading，沒有刪引用或改法名求通過。verify命令exit0不代表全數通過；未呼叫verdict也不能說資料庫已實際拒收它。詳[002查證索引](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-002/citation_verification.md)。

最終共享引用表123 published、4 draft不能當任一案獨有數目。205也是001中途候選，後來降draft；001發布當時65身分均通過，已發布評估與兩書狀實際引用不含205，未因此撤銷。DB狀態、raw結果、全文支持及發布結果分列，見[最終唯讀快照](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/retry_step8/final_database_snapshot.json)。

## P1–P5及新增流程證據

| 模式 | 001 | 002 |
|---|---|---|
| P1 虛構自承／自認 | 未確認錯誤 | 未確認錯誤 |
| P2 起訴狀混入後續反駁 | **重現1項，首次在Step9原告起訴狀** | N/A，未生成書狀 |
| P3 近乎認輸／評估矛盾 | 未確認錯誤 | 未確認錯誤 |
| P4 真判決支持無關命題 | 5全文未確認誤用 | 13字號／15全文未確認誤用 |
| P5 把推論當已證事實 | 未確認錯誤 | 未確認錯誤 |

001起訴狀58字原文：「（二）正面回應對造最強論點。對造要求先確定各項請求的事實、法律路徑、表示範圍及可核算金額，再駁回經調查仍未證明部分。」精確源自p_s3.argument，經pleading-source進稿。Stage3要求回應對造，在模擬辯論中合理；Step9要求原文套入起訴狀且不潤飾，才首次在起訴前情境中造成時序錯誤。writer、收集稿與DB是同一步驟的保存副本，不重複計數。答辯狀可回應原告，未因出現「對造」就判另一P2。

002確認三類查證流程問題：

1. **解析涵蓋不足。** 候選可提出施行法及銀行法，但既有法名白名單無法處理，不能滿足全部凍結引用查證通過的要求。
2. **同字號多文件誤配。** raw第61、108項對114台上1945取到3月4日承受訴訟裁定，支持撤銷前契約有效命題的是5月13日實體判決。獨立全文核對識別並修正來源metadata，沒有改引用文字。第一次同型錯配仍只保留推論，新證據不回填舊次。
3. **歷史法規版本不足。** 原生查證把現行205條16%文字標為published，未證108年舊版；角色保守降draft攔下。這是版本涵蓋缺口，未證明模型杜撰舊法或已發布錯誤結論。

[001標註](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/eval_annotations.json)為1筆／1條鏈；[002標註](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-002/eval_annotations.json)為5個出現位置／3條鏈，其中1筆只是舊attempt推論。合計6個位置均分類「流程有誤」，不是6種獨立法律幻覺。舊checker不自動探索新Step8報告／JSON的三種來源，另按source_file／JSON pointer精確核對全部20–120字引文；沒有冒稱舊工具全支援。

指定自認語句多屬否定、他案記載或對造確有的法律限縮；不同案型的有限類推保留適用限制，不能只看案由就判P4。條件falsifier不等於無條件認輸，法官也未把引用集合位移當勝率。日期、利息試算及補證方案有限定；未確認其他錯誤不等於證明零幻覺。

## 與標準答案及舊案對照

001預見知情／揭露、現況條款、交付時瑕疵、必要修復、施工新因及殘存價差。200萬元減價、完整現況表、特定管線與後來鑑定是被刪或對造才有的資訊，未猜到不扣應知事實。14問涵蓋減價、賠償、不完全給付及舉證；真實判6,000元、其餘駁回，模擬重點是分項補證，未估出該數額，不寫預測命中。

002預見侵權二年時效、中斷、善意受益／利益消滅、錢包控制、第三人及換價。未猜報案／起訴日、JM、被告自己投資及紐約條款，不當成捏造或應知遺漏。法院有後來卷證而認詐欺，卻採時效及投資契約未撤銷等理由全部駁回；模擬缺日期及證據，保留待證並提示契約效力問題。資訊及審理範圍不同，不能直接算法律推理錯誤，逐項對照見eval。

舊案比較依交接文件及[歷史比較資料](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/historical_comparison_notes.json)。P2在真實單方輸入、標「原告主張」及換模型後仍可沿現行Stage3→Step9規則追溯，支持該流程機制的風險。P1等未確認重現，不能單獨歸因標記或模型改善：案情、證據、模型、範本版本同時不同，沒有同案受控對照。repo未找到「61個已人工確認錯誤」的逐筆清單／計數規則，不直接拿61作可核實基準線或錯誤率分母。

## 機械檢查及時間

| 項目 | 001 | 002 |
|---|---:|---:|
| 頂層程序嘗試／streams | 15／15 | 12／12 |
| 可解析事件／JSONL解析錯誤 | 713／0 | 574／0 |
| 統一needle／其中gold特徵 | 12／6 | 14／8 |
| 真名、法官、holdout、gold特徵命中 | 0 | 0 |
| 案號命中，均source_note | 13 | 12 |
| 啟發式網路候選事件 | 26 | 4 |
| Stage1初次環境失敗未採用 | 2，各重派1次成功 | 同左 |
| Step8嘗試 | 3，採第3次 | 2，仍未通過 |
| 有usage回報的頂層呼叫 | 12／15 | 10／12 |
| 首次啟動至最後結束 | 200.13分鐘 | 212.39分鐘 |
| 任一角色活動區間聯集 | 69.60分鐘 | 60.35分鐘 |

兩案全部法律角色08:31:48 UTC結束後才重新讀取holdout評分。特徵另已確認不在凍結輸入與corpus；命中呼叫／行號見各machine_checks。未命中只涵蓋保存事件與指定字串，不能排除所有語意污染或未記錄活動；候選、重播及保存副本不當新增錯誤。

時間含工具等待；牆鐘另含準備與使用者授權，並行區間不能直接相加當延遲。未觀察到安全分類器中止證據。CLI回報001 input 8,769,760（cached 7,982,208）、output 140,740；002 input 11,816,523（cached 10,992,384）、output 150,347。cached是input子集，缺usage的中止呼叫及無獨立回報子程序不能完整計費；沒有實際美元費用。見[001統計](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/run_statistics.json)、[002統計](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-002/run_statistics.json)。

## 派工、環境偏差與完整性限制

[最終完整性聚合](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/retry_step8/final_integrity_audit.json)通過：27個prompt雜湊、94個工作目錄輸入、34個絕對路徑綁定、30個來源保護對照、20次txt精確填值、5次Step8及2次Step9原文任務、16份核心輸出的80個角色原欄位、2份機械錨點及4份原始查證陣列均一致。這些完整性檢查不替代法律或書狀用途正確性。

五種既有txt範本逐字填值，唯一前綴為指定環境說明；Step8／9無專用txt，擷取SKILL原文並附輸入輸出／環境綁定。001查證重試法律prompt原文不變；002本次新增官方引擎範圍及產物目錄等環境綁定，整份prompt與前次非逐byte相同，法律任務及六份凍結輸入仍一致。Step9落地由調度員負責，writer未收到該CLI段中的陣列schema註記；原告35物件僅同序抽取citation_text，被告33字串原樣保存，內容未改，兩份原生書狀閘門通過。

27個頂層角色均fresh codex exec、ephemeral、不resume，保存實際prompt、事件、參數及可取得的最後回覆。早期Step8有原生子代理活動：001 call11共21個collab事件、call12共10個，002 call11共16個；事件數不是子角色數，缺獨立子prompt／trace時不能宣稱所有參與者符合完整新程序紀錄。三次均未採作通過證據。最新001 call13、兩writer及002 call12明確關閉agents，未見nested活動；僅features.multi_agent=false不足以保證。六組更早環境probe只有stdout／stderr的缺口仍保留。

使用者允許Step8既有引擎查法務部／司法院，一般網搜保持關閉。**001兩次引擎外urllib官方探針（call11、call13各一次）超出only-engine範圍，屬執行偏差。** started／completed及程式內URL可重複觸發regex，26／4不是請求次數。MXC保留loopback，無逐封包證據，不宣稱全部流量絕對只限官方兩網域。

為建立／刪除SQLite sidecar，環境允許測試DB父目錄建立新檔，現存來源與正式DB另受保護；這確實容許任意未來檔名。001 call13將5份產物誤寫database子目錄，已逐byte一致搬回run目錄，保存[搬移證據](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/calls/13_citation_verify_attempt3/artifact_relocation.json)，全部角色結束後只刪自行建立的空父目錄。早期journal、遙測及工具錯誤以環境預檢處理；產品來源雜湊保持原值，未修解析器或法律邏輯。

## 交付與停止點

新增或更新兩份data/cases輸入、各案run目錄的凍結素材／範本、prompt／stream／manifest／回覆、論證、訊問、摘要出處、錨點、verdict JSON、查證原始結果、機械檢查、統計及eval／annotations；001另有兩份書狀與落地記錄，002沒有書狀。調度與評估輔助程式都在記錄目錄，外部holdout仍保留原判決、gold、removed及來源。

- [001原告起訴狀骨架](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/pleading_draft_plaintiff.txt)
- [001被告答辯狀骨架](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/pleading_draft_defendant.txt)；依SKILL 9B結構整理，本機沒有官方答辯狀範本，未冒稱使用官方答辯模板。
- [最終交付核對](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/delivery_validation.json)
- [測試資料庫](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/database/codex_runs.db)

所有main.py調用均先設LEGALDEBATE_DB_URL=sqlite:///database/codex_runs.db。未修改templates、engine、main.py或database來源，保護雜湊一致，沒有commit、push或修復產品問題。測試DB寫入與查證角色保守修改引用狀態均留trace；事後評估只讀DB。

未完成／未驗證：002三個unsupported法條及108年205舊法／施行適用、002評估發布與兩書狀、原attempt工具證據缺口、來源判決官網全文及直接出席紀錄。001書狀已產但含P2，仍待律師處理。本輪支持固定派工紀錄、區分文件及法規版本、為起訴前情境設定書狀素材邊界；這些改進未實作，未驗證某框架效果。

已到第二停止點：交付001、002評估及總報告初稿，003等待使用者決定。

**本結果為爭點分析與書狀骨架初稿,非法院判決預測,語氣潤飾與正式訴狀撰寫仍需律師覆核。**
