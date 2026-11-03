# main.py 檢查與畫面資料(第 4 批:W7-4、W5-5、W6 列、W7-3、W5-6、W4-4、舊設計殘留第 2 項 B、T9)

> 組長不在時交給組員(Claude Code)的第 4 批。分支 `ui-v2-fixes`,疊在 `live-run-v2` 上。

## 1. 改了什麼

| 審查編號 | 檔案 | 做法 |
|---|---|---|
| W7-4 | `main.py` `cmd_check_judge` | 評估 JSON 也跑 `_verdict_v2_gate`:`risk_map` 新鍵的結構問題在查證之前就退回,勝訴機率字樣照樣只警告。退回訊息和自承檢查分開寫 |
| W5-5 | `main.py` `cmd_check_judge` | 收到爭點整理表(有 `issues`、`undisputed` 或 `clarifications`)不再 KeyError,結束碼 2,提示改用 `issue-sheet --check`;看不出是訊問還是評估也回 2 |
| 第 4 節 W6 列 | `main.py` `_round_check` | v2 案件還沒有爭點整理表時,stage 2、3 的 `record` 拒絕落地。舊流程不變 |
| W7-3 | `server/services.py`、`server/app.py`、`ui/app.js` | 起訴狀 v2(`source=system_revision`)是第三種來源:標籤「起訴狀 v2(系統建議版)」、引用依資料庫判定(落地時已過閘門)、匯出檔名 `_revision`、匯出資訊寫明是建議版。**沒有**把它加進 `_is_system`,總覽與關卡 1 的原告書狀仍是起訴狀 v1(另開 `_is_revision`) |
| W5-6 | `server/services.py`、`ui/app.js` | 案件資料多 `issue_sheet`(原樣 JSON + `render_issue_sheet` 組成的四張表文字 + 「不爭執事項來自模擬答辯」說明);v2 的進度改用 `_progress_v2`,步驟與完成判定和 `live_run.RUN_STEPS_V2` 同一份(看 `IssueSheet`,不看法官訊問);起訴審查卡片的「第 N 則追問」改讀爭點整理表的 `questions`。總覽加一張「爭點整理表(P3,模擬)」卡片(全文預設收合) |
| 舊設計殘留第 2 項 B | `database/db.py` `finalize_case`、`server/services.py` `drift_detail`、`_anchor_check`、`ui/app.js` | v2 案件的 `position_drift` 是 `{plaintiff: null, defendant: null}` 加 `position_drift_note`;`drift_detail` 回 `not_applicable`;`_anchor_check` 不比引用清單差異、只加中性說明,所以不會出現紅色「不一致」;畫面寫「新流程不適用」。舊流程完全不變 |
| W4-4 | `ui/app.js` | `DOCUMENT_V2`:v2 的起訴狀、答辯狀說明改成「程式依結構化內容組成」「被告只讀起訴狀、逐點表態」;舊錄製案照舊用 `DOCUMENT` |
| T9 | `engine/summary_check.py` | `check-summary` 兩個欄位都收:只有 `strongest_point_verbatim` 時照它檢查;兩個都給又不同時結束碼 2 |

## 2. 和審查不同的做法

- W5-6 審查建議「不爭執事項標明來自模擬答辯」:放在 `issue_sheet.undisputed_note`,畫面卡片的第一行顯示。
- 第 2 項 B 的說明文字放在 `database/db.py` `V2_DRIFT_NOTE`,`services` 共用。

## 3. 瀏覽器驗證(假 Claude)

用暫存資料庫與 `tests/fake_claude.py` 當 Claude Code 啟動 UI(啟動腳本在組員的暫存資料夾,不進 git;`.claude/launch.json` 只暫時加一項,用完已還原)。建一件 v2 案件(不給統編),不指定停止點開始執行:

| 看什麼 | 結果 |
|---|---|
| 執行 | 32 則事件,P0–P6 全部落地,「執行完成,各階段皆已落地資料庫」,關卡 1 自動通過 |
| 總覽 | 「爭點整理表(P3,模擬)・1 個爭點」卡片與說明 |
| 爭點評估 | 綠色 ✓「已比對欄位與落地時的計算結果一致……(引用清單差異新流程不適用)」;沒有紅色 |
| 機械彙整 | 按「執行彙整計算」後兩方都是「新流程不適用」 |
| 訴狀骨架・起訴狀 | 版本列「起訴狀 v2(系統建議版) #7・接在 #1 之後・✓」;選它時是說明 banner,不是「律師編輯版」;副標題「起訴狀 v2．系統建議版」 |
| 訴狀骨架・答辯狀 | 說明是 v2 文字;舊錄製案的說明不變 |
| console | 沒有錯誤 |

**看到但沒有改(不在本批範圍)**:準備書狀、言詞辯論意旨狀也列在各方的版本列(「系統產生版 #3、#5」),而且答辯狀分頁預設選最新一份,打開看到的是言詞辯論意旨狀,副標題還寫「模擬答辯」。`versionsOf` 沒有依 `pleading_type` 分開。這是 W6 接線後 UI 要處理的(例如版本列只放起訴狀/答辯狀,準備書狀另一張卡),請組長決定。

## 4. 實作紀錄

- 2026-11-03 約 13:00–13:40(組員,Claude Code)。基準 `live-run-v2` `a75737f`,離線全套 813 通過、2 略過、13 未選。
- 先寫 `tests/test_ui_v2_fixes.py`(15 項)再改程式;第一次跑 2 項失敗(匯出檔名、UI 文字),照預期。之後補 1 項(追問讀爭點整理表),**這一項是先改程式再寫測試**,沒有先看到紅燈;第一次寫的版本沒有商工查核、程序事項是空的,斷言空清單也會過,改成先記一筆「解散」的查核。
- 兩次用 bash heredoc 寫 Python 改檔時字串裡的 `\n` 被換成真的換行(第 3 批也發生一次),改用 Edit 工具或先寫成檔再執行。
- 新增測試(16 項):`check-judge` 對 v2 評估擋新鍵、勝訴機率只警告、爭點整理表與看不懂的 JSON 回 2 不當掉;v2 沒有爭點整理表時 stage 2、3 拒絕落地、舊流程照常;`strongest_point_verbatim` 收、兩欄不同回 2;`finalize_case` 的 v2 不適用與舊流程不變;假 Claude 跑完全程的案件:回傳爭點整理表、進度照新步驟、起訴狀 v2 是自己的來源且匯出檔名 `_revision`、總覽原告書狀仍是 v1、引用清單差異不適用且一致;追問讀爭點整理表;`app.js` 有 v2 文字。
- 改了的檔:`main.py`、`engine/summary_check.py`、`database/db.py`、`server/services.py`、`server/app.py`、`ui/app.js`、新測試檔、本文件。
- 沒驗證:沒有 Claude 實跑;沒有斷網重播;舊錄製案只看了訴狀分頁的說明,其他分頁靠既有測試;程序事項畫面只用測試確認,瀏覽器那件案件沒有商工查核。

## 5. 測試數字

- 基準:813 通過、2 略過(`a75737f`)。
- 做完:見 commit 與回報。
