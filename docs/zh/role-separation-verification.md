# 職責分離改版：獨立驗證紀錄

驗證日期：2026-10-31。驗收依據：[role-separation-acceptance.md](role-separation-acceptance.md)。

本文件由獨立驗證 agent 維護。驗證 agent 沒有修改產品程式；只維護驗收文件及 `tests/test_role_separation_acceptance.py`。實作 agent 的自測證據與本文件的獨立驗證分開記錄。

## 授權範圍修訂

使用者後續把五項移至【B】：新增 `verify-gate` CLI、自動網路重試、新增 `record-verification` 專用指令、每輪法條解析、新增書狀引用型態檢查。本次不以這五項未實作為缺陷，亦不把未執行的檢查記作通過。既有 published 引用閘門保留。

使用者已進一步明確指定：**只完整重跑002；001只保留固定反例測試**。001未完整模型重跑不列本次未完成事項。

## 環境與基準

- 首次預設 `python -m pytest -q -m 'not network'` 遭作業系統暫存目錄權限影響，多項 fixture setup error；該次中止，不能算產品基準失敗。
- 第一次指定 `.pytest-tmp/verifier-red` 時父目錄尚未存在，產生46個 `FileNotFoundError` setup errors；建立 repo 內 `.pytest-tmp` 後重跑。該次亦不算功能驗證。
- 所有後續驗收指定 repo 內獨立 `--basetemp`，不使用共用測試目錄、不讀寫使用者真實資料庫。
- API測試另遇Windows事件迴圈停在 `asyncio.proactor_events._make_self_pipe → socket._fallback_socketpair → accept`。`faulthandler.dump_traceback_later(15)` 已定位，尚未進入產品API路由。同一probe於一般執行環境（`require_escalated`，自動審核通過）2.54秒回應HTTP200。因此含API測試在一般環境驗證，沒有修改產品迴避環境限制。
- 完整既有基準由主 agent 以 `.pytest-tmp/baseline-full` 重跑；待主 agent 結果後補。

## 測試與結果

| 階段 | 命令／輸入 | 狀態 |
|---|---|---|
| 事前驗收標準 | 在產品實作前寫 `role-separation-acceptance.md` | 已固定；五項後續授權延期另行記錄 |
| 首輪黑箱測試 | `python -m pytest tests/test_role_separation_acceptance.py -q --basetemp .pytest-tmp/verifier-complete1 --tb=short` | 56 passed，151.77秒；基礎CLI/API/洩漏/撤回/P2驗收 |
| 獨立擴充評估與金額 | `-k 'evaluation or reference_grade or breakdown' --basetemp .pytest-tmp/verifier-eval1` | 2 failed / 15 passed，21.01秒；已交實作者修正，見下方缺陷紀錄 |
| 獨立查證隔離 | `-k 'q03 or q05 or q07' --basetemp .pytest-tmp/verifier-citation1` | 4 passed，11.40秒 |
| 修正後完整驗收 | `--basetemp .pytest-tmp/verifier-complete2 --junitxml=.pytest-tmp/verifier-complete2.xml` | 77 passed，229.17秒 |
| 額外巢狀私密欄位 | `-k 'nested_internal' --basetemp .pytest-tmp/verifier-nested1` | 1 passed，4.14秒；公開投影不洩漏巢狀internal_notes |
| 額外機械彙整 | `-k 'mechanical_anchors' --basetemp .pytest-tmp/verifier-anchor1` | 1 passed，2.30秒；三holder／撤回理由／引用格式差異為0 |
| 額外角色資料流 | `-k 'cannot_bypass_opponent_summary' --basetemp .pytest-tmp/verifier-role-only` | 1 passed，2.69秒；party檔僅己方歷史、法官雙方公開歷史 |
| 最後80項完整驗收 | `--basetemp .pytest-tmp/verifier-final80 --junitxml=.pytest-tmp/verifier-final80.xml` | **80 passed，243.96秒；退出碼0**。此結果不是由實作者自述代替，為獨立驗證agent實際執行 |
| 重跑控制器本機測試 | `python -u -m pytest tests/test_rerun_role_separation.py -q --basetemp .pytest-tmp/verifier-harness1 --tb=short` | **15 passed，77.78秒；退出碼0**。未呼叫模型，不等於002完整重跑 |
| 全套回歸 | 全部離線測試 | 待實作完成 |
| UI實際操作 | 獨立本機18765埠、`.pytest-tmp/ui-acceptance.db`、背景IAB實際操作 | 下方各案例已操作驗證；截圖功能不可用，僅保存DOM證據，不能宣稱像素排版已驗證 |
| 程序門檻官方實查 | `docs/zh/role-separation-procedure-checks.json` | 已獨立讀取：427條50萬、436之8條10萬，2條published，含官方URL／全文／時間 |
| real-001固定反例 | 舊起訴狀混入「對造／Stage」的實際凍結產物 | 通過拒絕落地測試；完整模型重跑依使用者指示取消 |
| real-002完整重跑 | 獨立目錄、固定六指標 | 待實作完成 |

### 已修正並複驗的實際缺陷

1. 合法v2評估曾呼叫 `_assert_all_published(..., case_id=...)`，但當時函式沒有該參數，產生TypeError。實作者補上本案查證入口後，合法評估及原文保存測試通過。
2. 金額明細原可引用 `plaintiff:P1@S1`，有繞過最終主張狀態的風險。實作者限制明細只能引用S3；修正後同一反例被拒絕。
3. 新版書狀頁仍稱「直接帶入攻防結果原文」，與9A素材限制矛盾。已改為claim_statement／asserted主張的素材說明，代理被告標為起訴前準備草稿。
4. 總覽程序提示顯示英文資料key且重複警示，已改為中文提示並去重；內部備註輪次與明細金額的數字原未顯示，已修正並在UI確認1/2/3、100、合計100均可讀。金額明細中的巢狀procedure提示也經整頁reload後程式斷言確認不再露出英文key。

### UI實際操作案例

- 以新表單建立 `ui-verifier-plaintiff`：代理原告、三欄事實、兩種書證、金額100000；送出前明示小額程序且不阻擋，案件頁保留F1/F2/F3、書證名稱、對方說法轉述來源。
- 新版總覽依序顯示三類待辦、對方預測、爭點表、我方備註、書狀金額、歷程；代理原告不顯示被告私密備註，代理被告只顯示被告己方備註。
- 完成六份測試論證與I1評估後，爭點表顯示參考中／評估中、準備欄、F1；實際點開 `plaintiff:P1@S3`，可見該輪label/elements/source原文。
- 原告書狀選項為起訴狀與「對方可能答辯要點（預演用，非書狀）」；實際點選後顯示非書狀預演。被告案則選己方預先準備答辯草稿，另一選項為對方可能起訴要點。
- 明細已確定價金100：UI可見金額100、合計100、與原案100000不符的提示，沒有因警示阻擋保存。
- 另建無represented_side的舊協議測試案：仍顯示原有總覽、原始事實、4/6論證進度，沒有強迫舊資料套新格式。
- DOM快照存於 `.pytest-tmp/ui-overview*.snapshot.txt`、`ui-issue-table.snapshot.txt`、`ui-expanded-reference.snapshot.txt`、`ui-defendant-pleading.snapshot.txt`、`ui-amount-final.snapshot.txt`、`ui-legacy.snapshot.txt`。Browser screenshot回傳「Unable to capture screenshot」，未以其他產物冒充視覺截圖。
- 另外以實際瀏覽器DOM互動執行**6組程式斷言，全部通過**：舊版相容；新版三facts／私密備註／輪次及金額；爭點表與展開原文；原告書狀及對造非書狀預演；被告草稿及對造非書狀預演；金額明細巢狀程序提示純中文。結果存 `.pytest-tmp/ui-programmatic-results.json`。
- 驗收結束後已關閉驗收分頁並停止18765臨時服務；暫存測試資料保留為證據，使用者原資料庫未變更。

## 尚未可由單元測試證明的事

- 判例第三層實質支持，需要與寫論證分離的查證 context 實查；判例存在、摘句確實存在不能取代此判斷。
- 回報或法官文字語意是否與 item 原文完全一致，需要原文帶出與人工抽核；機械參照檢查只能證明可追溯。
- 002真實重跑的完成狀態與固定六指標，必須讀到實際輸出後才可填寫；啟動工作不等於重跑完成。001依後續指示只驗固定反例。

## 全套最終回歸與正式重跑狀態（主agent）

完整pytest含官方網路：374 passed、1 skipped，302.83秒；證據 `_tmp/final-full.txt`、`_tmp/final-full.xml`。獨立程式審查10個回歸通過，見code-review文件。002正式模型啟動遭自動核准審查拒絕，要求對指定匿名payload及OpenAI Codex外部服務明確授權。尚無正式模型呼叫，不能記為重跑完成；新run manifest為preflight_passed、nodes空。

### 002後續進度（非完成結論）

使用者已明確同意使用Codex額度及指定匿名資料/外部服務，正式重跑獲核准並已開始。Stage1雙方各一次格式退回後，第二次通過並一起落地；原告22項（6 asserted、16 to_confirm）、被告25項（2 asserted、23 to_confirm），無withdrawn。時效與善意受領利益不存在目前待確認；這是第一輪狀態，不能代替最終M1。法官訊問已於首次呼叫通過落地，Stage2雙方產出中，尚未讀holdout。
