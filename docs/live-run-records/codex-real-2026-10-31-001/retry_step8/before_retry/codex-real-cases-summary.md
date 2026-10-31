模型設定：**gpt-6-astra；reasoning effort：ultra**。每次法律角色的 CLI 均明確指定這兩個值；事件流未提供可獨立核對的服務端 effective-model metadata。未指定 temperature，不能宣稱按舊文件建議的0.7／0.2執行。

# 001、002 真實案件實跑總報告初稿

日期：2026-10-31。兩案完成雙方三輪攻防、法官訊問、機械彙整及未發布的法官評估，**都停在Step8，沒有完成完整端到端流程，沒有生成兩份書狀**。本報告不補做被中止的角色輸出，也不以事後評估替代原查證閘門。

目前未在已採用的法律分析中確認P1、P3、P4、P5的實際重現；P2因沒有書狀為N/A。002另有2筆查證流程問題標註：解析覆蓋缺口可確認；同字號文件錯配的本次發生仍標推論。環境故障、事件證據缺口及引擎外網路探測另外記錄，不混算為法律幻覺或舊案錯誤率。

## 交付入口

| 案件 | 評估 | 逐筆標註 | 機械檢查／查證執行稽核 |
|---|---|---|---|
| 001 | [eval.md](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/eval.md) | [eval_annotations.json](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/eval_annotations.json)，空陣列 | [機械檢查](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/machine_checks.json)、[Step8稽核](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/step8_execution_audit.json) |
| 002 | [eval.md](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-002/eval.md) | [eval_annotations.json](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-002/eval_annotations.json)，2筆，其中1筆推論 | [機械檢查](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-002/machine_checks.json)、[Step8稽核](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-002/step8_execution_audit.json) |

所有quote均由原始欄位擷取，002兩筆分別31字、25字，通過既有檢查器及獨立來源子字串檢查。001沒有達門檻的實質錯誤可標，quote驗證為無項目可驗，並非一次「全流程零錯誤」測試。

## 來源、輸入與程序完成情形

| 項目 | 001 | 002 |
|---|---|---|
| 來源 | 新北地院113年度訴字第3504號，2026-10-28，減少價金等 | 士林地院115年度重訴字第242號，2026-10-28，損害賠償 |
| FJUD | [來源連結](https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=PCDV,113%2c%e8%a8%b4%2c3504%2c20261028%2c1) | [來源連結](https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=SLDV%2c115%2c%e9%87%8d%e8%a8%b4%2c242%2c20261028%2c1&ot=in) |
| 適格及信心 | 日期在門檻後、地院通常程序第一審實體民事判決、部分勝敗 | 日期在門檻後、地院通常程序第一審實體民事判決、全部敗訴；部分勝敗原為偏好而非必要條件 |
| 輸入摘要 | 原告指交屋翌日漏水、三房地板腐爛及管線／防水瑕疵；修復與交易減損共請求974,000元及送達翌日5%利息 | 原告指LINE招攬交易機器人，交10BTC十日後取15BTC；採原始15BTC先位、清償日換價及利息備位聲明 |
| 刻意排除 | 真實減價200萬元／現況交屋抗辯、法院鑑定、後來674,314元聲明、判准6,000元等 | 刑偵自承、報案及起訴日期、JM及被告金流說法、後來10BTC／34,066,792元聲明、法院判斷等 |
| Step1／1.5 | 案件、檢索詞及issues完成；不做商工查核 | 同左 |
| Stage1–3 | 六份完整JSON採用並落地 | 六份完整JSON採用並落地 |
| 法官訊問 | 14則 | 13則 |
| Step6／7 | 原樣機械錨點及完整未發布評估 | 同左 |
| Step8 | 遇工具／環境錯誤後由調度員停止；沒有最後回覆，沒有採用的最終實質查證報告 | 程序exit0，但最後回覆明言查證未通過；不能將exit0視為閘門通過 |
| Step9 | 未執行，兩份書狀皆無 | 同左 |

來源全文是使用者貼上的FJUD文字，專屬URL的法院、字號及日期與貼文相符，未成功獨立取得官網全文。兩造有實質答辯等間接出庭依據，沒有另取得出席筆錄。這些是第一站已揭露的選案信心限制。002由交通放寬為一般侵權，已經使用者同意，並非仍宣稱測了交通案。

兩份輸入保留「原起訴」標籤，沒有結構化的起訴前phase或基準日期。模型因此要求原訴狀、送達及變更資料；須將這種階段歧義與捏造既存文件分開。不得現在改寫已凍結輸入來使結果看起來較好。

## P1–P5及標準答案對照

| 模式 | 舊紀錄可核對的現象 | 本輪001／002 |
|---|---|---|
| P1 | 舊報告記錄把證據缺口升成自認的問題 | 沒有確認重現。原告主張、待證、假設及他案前提大多有明示；法官的共識限定於分析前提或請求結構，未把交付／責任改成真實被告自認 |
| P2 | 舊錄製起訴狀出現針對被告主張反駁的文字 | **兩案皆N/A**；本次未生成書狀，不能記0違規或通過 |
| P3 | 舊紀錄把引用集合位移及讓步條件過度讀為立場／勝敗方向 | 沒有確認完整重現。機械weak_points仍按falsifier生成，但本輪法官明確區分條件與其觸發事實，並將drift限於引用集合；結構風險仍在，不等於本次已產生錯結論 |
| P4 | 舊報告明確指出錯用判例 | 001讀5個字號全文、002讀13個字號15份文件後，限定法律命題都有支持。案由不同本身不足判誤引。002另有「同字號多文件取首筆」實作風險，與模型引用實體判決正確分開 |
| P5 | 舊gcis run-4曾由當前年份推定期間屆滿，後被追問撤回 | 沒有確認重現。日期／利息試算明列假設，證據名稱多為補證清單，沒有把它們當已存在的本案卷證 |

舊來源定位見[歷史比較紀錄](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/historical_comparison_notes.json)。例如[e2e舊報告](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/zh/e2e-test-report-2026-08-08.md:46)、[舊錄製資料](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/demo/recorded_cases.json:1438)、[gcis run-4原始被告分析](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/run-4/d_s1.json)。沒有在repo找到「61筆已人工確認錯誤」的逐筆清單及計數規則，不能直接拿61當本輪錯誤率分母。

001被告預見了揭露／知情、現況條款、交付時瑕疵、必要修復範圍、裝修或施工新因及殘存價差等真實防禦方向；沒有猜到200萬元減價、完整現況表及後來鑑定，不算遺漏應知事實。真實只判6,000元；模擬重點也是補證與分項，但未估出該數額，不將方向相容寫成預測命中。

002被告預見了二年時效、中斷、善意受益／利益消滅、錢包控制、第三人及換價爭議；沒有猜到報案／起訴日、JM、被告自己投資及紐約條款。法院有後來卷證而認詐欺，卻因時效及投資契約未撤銷等理由駁回；模擬沒有這些日期與證據，故保留待證並另提契約路徑。資訊差不能當成錯誤預測，沒有統計準確率可算。

本輪P1較舊例呈現更完整的限定語保留，但案件、模型、輸入標記及部分既有範本版本同時不同，沒有同案受控對照，不能把差異單獨歸因於標「原告主張」或換Codex，更不能據此說流程問題已修好。

## 已確認的查證及執行限制

1. **解析覆蓋與歷史法規。** 002的111個原始字串可歸為106個identity；凍結解析器能處理108個字串，對民法債編施行法及兩條銀行法字串不支援。這不代表法條不存在。Stage1允許提出法律候選、Step8卻要求全數通過，兩者能力未對齊；歷史民法205的版本與施行適用另未核實。
2. **字號不是文件身分。** 114台上1945同時有承受訴訟裁定及實體判決。現有取第一份檔案的規則可離線重現取到程序裁定，而實體判決確有被引用命題。本次原始回傳缺失，不能宣稱已證明當次錯配；標註保留is_inference=true。單靠案由字串相等也不能取代全文支持關係核對。
3. **角色回報不是執行證據。** 002最後自述108個published、3個unparseable、13件全文閱讀；原始整批回傳與完整工具結果不在可見trace中。可解析108個不等於已查證108個。部分工具路由失敗沒有留下完整呼叫／結果，不能反過來斷言命令從未執行。
4. **共用引用快取不是兩案完成證明。** 最後專用DB有65個published identity（60法條、5判例），覆蓋001的65個身分及002的44個身分。引用表無case_id，這些列verifier_run_id均空，不能歸屬各案查證；也不表示逐論點相關性已通過。兩案verdict及pleading列均為0。這些資料未由事後評估改寫。
5. **環境與入口偏差另列。** Step8有SQLite journal權限及背景VisualStudio遙測被白名單拒絕的錯誤；屬本次隔離／工具問題，不冒稱產品法律邏輯錯誤。001另有一次引擎外urllib官方站探測，回HTTP200，違反「僅既有引擎」的授權範圍；它不是一般網搜，但不能隱去。中間工具失敗與未知程序等待也不能包裝成成功。

這些觀察支持先把查證命令、順序、輸出保存及發布檢查交由程式固定執行，並分開存在性、文件身分、法規版本、逐論點支持與最終發布狀態。這是依本輪資料提出的改進方向，尚未實作或驗證效果，不藉此宣稱某框架必然解決法律推理錯誤。

## 機械檢查、重現紀律及時間

| 檢查 | 001 | 002 |
|---|---:|---:|
| 保存stream／可解析事件 | 11／559 | 11／485 |
| JSONL解析錯誤 | 0 | 0 |
| 統一敏感needle／其中gold防禦特徵 | 12／6 | 14／8 |
| 原名、法官、holdout路徑及gold特徵命中 | 0 | 0 |
| 來源案號命中 | 10次，均source_note | 10次，均source_note |
| 可見網路候選 | 同一官方探測的開始／完成兩事件 | 0；不代表引擎內部無連線 |
| 自認語境人工回查 | 9句不重複指定詞句，未確認錯誤 | 去機械副本重複後12句，未確認錯誤 |
| 論證與評估中的唯一裁判全文核對 | 5字號／5全文 | 13字號／15全文 |
| 程序嘗試 | 11 | 11 |
| 初次Stage1環境失敗後成功重派 | 2次未採用，各重派1次 | 同左 |
| Step8中止／未通過 | 1次由調度員停止，無最後回覆 | 1次正常退出但回報未通過 |
| 有使用量回報的呼叫 | 8／11 | 9／11 |
| 首次角色啟動至最後停止 | 127.34分鐘 | 124.11分鐘 |
| 任一角色進程活動區間聯集 | 50.94分鐘 | 50.82分鐘 |

時間含工具等待；牆鐘另含環境準備與等待使用者授權，並非純推理時間。並行呼叫不能把各角色分鐘相加當成延遲。沒有觀察到安全分類器中止的證據。CLI事件回報的用量合計：001 input 5,881,322（cached 5,300,864）、output 105,866；002 input 9,920,547（cached 9,211,904）、output 132,182。cached是input子集；未回報usage的中止呼叫不在這些數字內，沒有實際美元費用，不能套用舊2.5–3.8美元估算。詳[001時間與用量](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/run_statistics.json)、[002時間與用量](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-002/run_statistics.json)。

敏感特徵是在所有法律角色結束後才由外部gold建立，另確認不在凍結case輸入及整個corpus。所有案號命中的角色／呼叫與行號列在各案機械結果；指定詞句、日期、金額、姓名及證據候選的逐項回查見各eval及其support檔。候選不是錯誤數，重播與副本也不當成新增錯誤。

[獨立記帳稽核](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/docs/live-run-records/codex-real-2026-10-31-001/bookkeeping_audit_final.json)核對22次role calls、72項輸入雜湊／副本、30項保護原始碼雜湊對照及80個角色原始欄位，均一致；機械錨點沒有改寫。所有*.txt範本逐字填值，唯一範本偏差為指定的固定環境說明前綴。Step8原本無獨立txt，使用SKILL第75–83行原文與輸入路徑綁定，未另寫法律判準。

法律角色均為新codex exec程序、ephemeral且不resume；每次保存prompt、CLI提供的JSONL、參數／權限及可取得的最後回覆。中止程序沒有最後輸出即如實記缺。六組較早的環境probe只有stdout／stderr，缺完整呼叫紀錄；不能聲稱每次基礎設施探測也都可完全重建。較後兩次非模型codex sandbox probe另有完整參數及結果，不能補回先前缺口。

Step1–7不開角色網搜。使用者另明確允許Step8既有引擎查法務部／司法院，授權存於各案step8_network_authorization.json；此為對任務文件§4.1的明列例外。MXC設定保留host loopback，沒有封包級證據，不能宣稱絕對僅有兩網域的所有流量。001引擎外探測另列偏差，未把它算入授權內。

## 新增檔案與未完成事項

新增兩份[data輸入001](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/data/cases/real-2026-10-31-001.json)、[002](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/data/cases/real-2026-10-31-002.json)，兩案記錄目錄內的凍結輸入／範本、每次prompt／stream／manifest／最後回覆、各階段JSON、摘要出處、錨點、未發布verdict、稽核、統計及評估；以及本總報告。調度、機械檢查及評估輔助腳本均在本次記錄目錄。外部holdout保留原判決、gold、removed、來源紀錄，另新增事後污染檢查詞。

控制器的所有main.py命令均先設定 `LEGALDEBATE_DB_URL=sqlite:///database/codex_runs.db`；Step8另以shell環境政策明確注入相同值。失敗工具的參數證據缺口依前述稽核保留。

測試資料庫為[database/codex_runs.db](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/database/codex_runs.db)。沒有修改templates、engine、main.py或database原始碼，沒有commit、push或修復產品問題。專用測試DB由既有流程產生資料；不把這點說成資料庫原始碼修改。

尚未完成／驗證：兩案Step8最終完整通過、歷史法規核實、評估資料庫發布、9A／9B書狀、P2測試、部分失敗工具的完整執行證據、原FJUD全文的獨立官網核對及直接出席紀錄。003未啟動，依第二停止點交由使用者決定是否繼續；本稿不把缺項記為成功。

本結果供爭點分析與流程評估，非法院判決預測。正式法律策略與書狀仍須律師覆核；本次實際沒有生成書狀。
