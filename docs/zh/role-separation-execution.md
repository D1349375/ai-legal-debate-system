# 職責分離改版執行紀錄

依據：[實作計畫](role-separation-redesign-plan.md)、[事前固定驗收標準](role-separation-acceptance.md)。

## 範圍與分工

- [x] 先由獨立驗證 agent 制定驗收矩陣與兩案六項固定指標。
- [x] 核心實作 agent：案件欄位、角色投影、結構化主張、狀態轉移、法官輸入、彙整、評估、書狀與程式回報。
- [x] 查證實作 agent：文件身分、摘句、版本與失敗狀態、重試、每案紀錄、查證閘門。
- [x] 主 agent：範本與調度說明、API/UI、重跑腳本與整合。
- [x] 獨立驗證 agent：黑箱、對抗、相容性驗收；不修改產品實作。
- [ ] 全部【A】項目驗收完成後，重跑 real-2026-10-31-002（001只保留固定反例）；保留原始基準。
- [ ] 獨立驗證重跑產物、固定指標與計畫覆蓋結果。

## 實作界面

核心協議版本：`v2-role-separation-2026-10-31`。
`engine.role_protocol` 提供 `role_view(session, case_id, role)`、`argument_summary(session, case_id, side, stage)`、`build_report(session, case_id)`、`render_report(report)`。
五項新增查證工程依使用者縮減移至【B】；沿用既有verify與_assert_all_published，不新增專用閘門或寫入指令。

## 已裁決事項

- 使用者已提供定案計畫並授權實作，直接依計畫執行，不重開設計核准程序。
- 在現有 `role-separation-redesign` 專用分支實作，保留尚未追蹤的兩案輸入與完整基準紀錄，避免新工作樹缺少重跑所需的檔案。不同實作 agent 以檔案所有權隔離；獨立驗證 agent 不改產品程式。
- 本次完成全部三層【A】項目；【B】完整狀態機與歷史法條下載依原計畫保留。
- 新案 API 要求代理方；舊資料庫案例仍可讀取。既有建案測試輸入需補明代理方，以符合新契約，不能以靜默預設掩蓋必填要求。
- 重跑使用新目錄與獨立資料庫，不覆寫原始 `codex-real-*` 凍結紀錄；兩案均採最小輸入轉換。

## 基準與環境

首次離線 pytest：114 passed、1 skipped、8 deselected、94 setup errors；錯誤集中在預設暫存目錄存取。
指定專案內 `--basetemp .pytest-tmp/baseline-db` 後，資料庫基準 9 passed，證實是環境暫存路徑問題。後續各 agent 使用不同專案內暫存目錄。

後續完整命令與逐項驗證由 [驗證紀錄](role-separation-verification.md) 保存。

## 最新範圍修訂

使用者已確認只完整重跑002，001保留起訴狀固定反例。新增verify-gate、自動網路重試、record-verification、逐輪法條解析與書狀引用格式檢查皆列【B】；歷史205不能借用現行published為本輪必要正確性修正。

## 獨立驗收與程式審查 checkpoint

獨立驗收80項、控制器15項、瀏覽器6組程式斷言通過；001舊起訴狀固定反例拒絕。第一輪全套310 passed、21 failed，失敗為19項舊版串流fixture不合新建案契約、一項未知法規分類更新、一項施工中的測試import；舊協議串流fixture修正後38 passed。

獨立全分支審查另提出2項P1與2項P2（5個反例測試先紅）：第三層查證輸出缺正式流程入口、UI編輯/匯出錯用共用快取、空訊問批次續跑誤判、爭點附輪次參照漏算等級。以上均列必修，修正後重驗，不能以先前80項通過取代。既有verify入口接收支持性結果屬原A必要串接，不另新增延期的record-verification專用命令。

## 凍結與002重跑核准狀態

最終完整 `python -m pytest -q --tb=short --basetemp _tmp/final-full --junitxml=_tmp/final-full.xml`：374 passed、1 skipped，302.83秒；包含真實官方網路查證。skip為需顯式啟用的Claude權限探針，未當成通過。完整輸出/JUnit在 `_tmp/final-full.txt`、`_tmp/final-full.xml`。

獨立審查CR01–04已全部閉環，窄範圍10項通過。另補歷史版本明示欄位 `applicable_version=108年` 紅綠回歸與查證投影巢狀私密欄位清除。

002正式目錄：`docs/live-run-records/role-separation-real-2026-10-31-002-redesign-20261031/`。預檢passed、模型gpt-6-astra/ultra、原始/匿名轉換輸入與程式/範本雜湊已凍結。

啟動正式模型的動作遭自動核准審查拒絕：審查認為需要使用者明確同意將指定案件輸入傳至外部模型服務及可能用量/費用。尚未啟動任何正式模型呼叫，manifest仍preflight_passed、nodes空。不得以其他途徑繞過；待使用者對該匿名輸入及OpenAI Codex服務目的地明確授權後接續。001維持只做固定反例。

使用者後續已確認使用其Codex額度並明確答覆「同意」外部OpenAI Codex重跑。2026-10-31正式啟動獲核准，manifest狀態running，開始獨立角色呼叫；仍待完成後核對六指標。
