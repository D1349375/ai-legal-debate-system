# 職責分離改版：獨立程式審查

審查日期：2026-10-31。審查範圍為目前工作目錄的產品程式、調度範本、UI服務與一次性重跑控制器；先讀 diff package，再讀最新原檔。圖譜仍包含舊版函式，新增程式以原檔核對。審查者未修改產品程式，也未重跑既有77項驗收。

本輪不將 `verify-gate`、自動retry、`record-verification`專用指令、逐輪法條parse、新書狀citations型態檢查五項延期內容列為缺陷。候選未通過可列律師待核並繼續，實際採用的引用仍須本案published且判例通過支持性查證。自然語言語意無法完全機械驗證不列缺陷。

**最終窄範圍複驗結論：CR-01至CR-04均已修正，獨立10項反例／CLI案例通過；四項已報告發現沒有剩餘阻礙。** 以下保留修正前證據；本結論不代替全套回歸、網路實查、UI操作驗收或real-002完整重跑。

## 初次審查結論

發現2項P1與2項P2；下列為修正前可重現證據。修正由實作者負責，最後是否仍阻礙完成須以文末複驗狀態為準。

### CR-01 [P1] UI正式流程缺少獨立查證結果的寫入接點

- 位置：`main.py:117–139`（`cmd_verify`）、`database/db.py:401–418`、`server/live_run.py:43–44, 122`、`.claude/skills/legal-debate/templates/verify_prompt.txt`。
- 觸發：新協議案件最終評估／書狀採用一筆真實判例，例如114台上1945、日期20260513，文件身分與摘句通過，獨立角色另產 `supports_proposition=true` 的查證JSON。
- 現況：`verify`只保存機械結果；機械查證沒有 `supports_proposition=true`。獨立角色範本禁止直接寫DB，而UI正式執行只允許 `python main.py ...`。沒有任何既有CLI參數消費這份獨立JSON。因此後端對判例的 `_assert_all_published` 必然拒絕。重跑harness直接呼叫 `record_case_citation_check`，故它能通過不代表正式UI可通過。
- 影響：有合法判例的UI full與9C流程無法完成；為繼續而刪掉判例是內容降級，不能視為正確串接。
- 最小修法：在既有 `verify` 增加可選 `--review-json`，消費獨立查證JSON；先重新核對機械結果、文件notes、版本hints，拒絕把機械失敗升級為published；只把支持性判斷寫本案紀錄。同步SKILL/live指示。不需要新增延期的專用指令。

### CR-02 [P1] UI編輯與匯出仍依全域快取，繞過本案失敗與歷史版本限制

- 位置：`server/services.py:323–350`、`370–405`、`412–454`；`database/db.py:334–339`。
- 三個最小輸入：
  1. 新案紀錄115台上447 `status=unsupported, supports_proposition=false`；編輯一份空引用草稿，加上該判例。
  2. 原稿含現行「民法第205條」，全域存在published；本案新增「108年民法第205條」為 `version_unverified`，將正文改成後者。
  3. 系統稿184條原先本案published，之後本案最新查證為network_error，但全域仍published；讀取書狀版本。
- 修正前實際輸出：三者皆為 `status=published`；前兩者 `exportable=true`。第一項使用 `verified_via=local_corpus`，第二項使用 `verified_via=previous_record`。
- 原因：UI讀取、編輯、重驗與匯出走另一套只看全域查證的邏輯；引用抽取又把「108年」從引用前綴切掉，視為原引用未改動。
- 影響：核心落地層拒絕的引用，透過正式UI編輯可被標為「全部已查證通過」並匯出。每案隔離與歷史205防護在實際使用入口失效。
- 最小修法：新協議所有版本消費本案最新查證狀態；判例要求支持性通過，失敗不得被本地存在性覆蓋；保留年份／修正前資訊。編輯可存為blocked，匯出時重新檢查。舊案維持舊路徑；不需新增書狀引用型態檢查。
- 獨立回歸：`tests/test_role_review_regressions.py`前三項。

### CR-03 [P2] 合法的零訊問法官批次被UI視為尚未完成，導致無法續跑

- 位置：`server/live_run.py:426–427, 451`。
- 輸入：雙方Stage1完成；`record_judge_bundle`成功保存 `questions=[]`（可包含爭點／準備事項）；雙方Stage2完成後停止。
- 修正前實際輸出：`resume_plan(...)[possible] == false`，理由是「法官訊問未落地，但Stage2已落地」；`pipeline_missing`亦列「法官訊問」。
- 原因：新版以JudgeBundle代表整批法官工作，合法允許零問題，但正式UI仍只計算CourtQuestion筆數。
- 影響：模型沒有必要追問時，完成流程被誤標不完整；中斷後無法繼續，甚至要求使用者重建案。
- 最小修法：新協議以JudgeBundle存在作為該節點完成依據；舊案才沿用CourtQuestion判斷。完成檢查與resume共用同一規則。
- 獨立回歸：`test_ui_resume_recognizes_completed_judge_bundle_with_no_questions`。

### CR-04 [P2] 合法的附輪次爭點參照在最終參考等級計算時被丟棄

- 位置：`engine/role_protocol.py:396–408`。
- 輸入：法官批次的issue使用通過驗證的 `items=["plaintiff:P1@S1", "defendant:D1@S1"]`；到Stage3原告P1為asserted且所有要件met、F1依據，被告D1為to_confirm。
- 修正前實際輸出：`reference_grade="中"`；相同item使用無輪次參照時，依既定規則應為「高」。
- 原因：`issues_with_grades`只建立Stage3 index，卻用原始 `@S1` key查找，雙方項目全被忽略後落入無我方項目的預設「中」。
- 影響：機械評估值因合法參照的格式差異改變，法官還必須解釋為何偏離這個錯誤基準。
- 最小修法：依side/item穩定ID解析Stage3項目，或在JudgeBundle落地時明確拒絕帶輪次的爭點參照；不得靜默漏掉有效項目。
- 獨立回歸：`test_grade_uses_final_items_for_stage_qualified_issue_references`。

## 驗證與其他審查範圍

初次執行 `python -X utf8 -m pytest tests/test_role_review_regressions.py -q`：**5 failed**，全部為上述明確的產品行為差異；未呼叫模型或網路，未碰正式DB。另有既有requests相依警告及Windows console結束時訊息，不是這5項斷言失敗原因。

已閱讀角色投影、內部備註／準備清單分離、item狀態轉移與遺漏檢查、法官引用與錨點覆蓋、9A素材／金額結構、per-case引用查證、UI新案資料流、正式live調度及重跑harness。未將無法完全理解自然語言的限制當成缺陷。重跑控制器最新版已改為收齊並檢驗雙方JSON後才落地；M4亦已改成同一句的局部引用計數，這兩個已知修正不列未解問題。

## 修正後複驗

2026-10-31由原獨立審查者複驗，只追查上述四項及其修正邊界，未重新展開全分支審查，未修改產品程式。

| 發現 | 修正與獨立證據 | 結果 |
|---|---|---|
| CR-01 | 既有`verify`新增`--prepare-only`、`--candidate-json`、`--review-json`；查證輸入由已存資料與草稿產生，獨立結果經整批交叉核對才落地。真實本地114台上1945文件與摘句檢查通過後，測試用獨立JSON可保存支持旗標並讓書狀通過既有落地。 | 已修正 |
| CR-01反升級 | 115台上447只有存在性、未提供第一二層notes，即使review三個布林皆true仍拒絕；同批有效判例加歷史205錯誤升級，整批拒絕，`CaseCitationCheck`與全域`CitationVerification`皆無新列。 | 通過 |
| CR-01版本傳遞 | item註明舊法，候選採用同條不同項款字串，prepare輸出仍含對應歷史版本hint。 | 通過 |
| CR-02 | UI編輯、系統版與律師版讀取／匯出共用本案落地檢查；拒絕本案已否定判例，歷史205不借現行快取，系統稿也遵守本案最新失敗。 | 已修正 |
| CR-02去重邊界 | 複驗發現「先現行205、後108年205」仍會把歷史引用去重掉；已先新增反例確認紅，再由實作者修正去重key，現在同文歷史版本仍被保留並blocked。 | 已修正 |
| CR-03 | `pipeline_missing`與`resume_plan`接受已保存的JudgeBundle；零問題且Stage2完成後可以從Stage3續跑。 | 已修正 |
| CR-04 | 計算最終等級前依side/item穩定ID移除舊輪次限定，合法`@S1`參照取到Stage3內容，固定案例回傳「高」。 | 已修正 |

獨立測試均在`tests/test_role_review_regressions.py`，現共10項。執行紀錄：

1. 原5個反例：修正前5 failed。
2. 新增混合現行／歷史去重邊界：修正前1 failed。
3. 修正後執行整檔：前6項passed；新增4個CLI案例因系統Temp無法建立pytest目錄，在setup階段error，未執行測試，不算產品失敗也不算通過。
4. 改用工作目錄下新建暫存區，只重跑未執行的4項：`python -X utf8 -m pytest tests/test_role_review_regressions.py -k 'live_cli or live_prepare' --basetemp _tmp/review-ingestion-confirm-01 -q`，**4 passed、6 deselected，exit 0**。

合計本輪獨立複驗10項通過。未重跑實作者的完整測試套件；全套回歸由主agent統一執行。測試中的獨立支持性JSON是驗證資料流與寫入限制的固定輸入，不宣稱這些測試命題已接受真實法律實質查證。real-002模型重跑、獨立法律查證與holdout評估仍須另有執行證據。
