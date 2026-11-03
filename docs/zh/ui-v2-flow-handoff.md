# UI 改成書狀交換流程(v2)介面:交接

> 給接手實作的人。分支 `v2-wiring`(origin 上最新 55a93ff 之後);背景見 [v2-wiring.md](v2-wiring.md)。2026-11-03 由組員整理,使用者決定交給另一位實作。

## 0. 實作狀態(2026-11-03 更新)

**A–G 都已實作**,在 `v2-wiring`(本節下面第 1 節是實作前的現況,留作對照)。和本文件建議不同的地方:

- **B 進度軌沒有新增 `v2_progress`**:`get_case_detail` 對 v2 案件回的 `progress` 已經是 `_progress_v2`,步驟與判定都來自 `RUN_STEPS_V2`、`_v2_done`,和續跑計畫同一套。UI 直接用它(濾掉機械彙整、引用查證兩格),不另做一份。
- **C 的「原告主張」欄由後端組好**:答辯狀的 `pleadings.defendant` 多一個 `complaint_facts`(答辯狀回應的那一版起訴狀,用 `complaint_facts` 取各〔CF〕那一行)。
- **F 的差異對照放在版本資料裡**:`pleading_versions` 中 `source === "system_revision"` 的版本多一個 `diff`(`complaint_diff(上一版, 本版)`),不另開端點。診斷分頁最下方直接顯示差異；起訴狀分頁選到 v2 時有「全文／與 #N 比較」切換。
- **G 新案件**:後端 `stop_after_options` 只在續跑時才有值(新案件是空陣列),所以新案件固定畫四顆:只產起訴狀、跑到模擬答辯狀、跑到爭點整理表、跑完全程；續跑照 `stop_after_options` 畫。執行確認視窗拿掉了「被告防禦分析以後借舊流程」這句過時的說明。
- **A 分頁**:`/api/cases` 每筆多一個 `protocol`,分頁在案件明細載入前就能分流。舊網址 `debate`→書狀交換、`verdict`/`aggregate`→診斷、`pleading`→起訴狀；舊案照舊 7 個分頁。原本攻防分頁的 v2 分支移到「書狀交換(P4–P5)」分頁,總覽的爭點整理表卡片移到自己的分頁。
- **E 舊三鍵**照舊顯示在新鍵之後；讓步條件改成診斷分頁的一張卡(取第 3 輪論證的 `falsifier`,不用按鈕計算)。

驗證：兩件 v2 實跑案與舊錄製案 `test-2026-10-27-gcis-001`,用無頭 Chrome 逐頁看深色、淺色,console 沒有錯誤；手機寬度(390px)沒有橫向捲動。Claude in Chrome 當時沒連上,所以是無頭瀏覽器截圖,不是在使用者的瀏覽器裡點。

## 1. 現況(實作前)

v2 流程(P0–P6)已用 Claude 實跑通過,資料都落地、API 也都回得出來,但 **UI 還是舊流程的骨架**,新流程的東西是附加上去的:

| # | 問題 | 位置 |
|---|---|---|
| 1 | 分頁仍是「案件總覽、起訴前檢查、攻防過程、機械彙整、引用查證、爭點評估、訴狀骨架」;「機械彙整」是舊流程概念 | `ui/app.js` `TABS`(約第 30 行) |
| 2 | 總覽統計寫「攻防論證(雙方 × 3 階段)」「法官訊問 0 則」,看不出走到 P 幾 | `ui/app.js` 約第 335 行 `stat(...)` |
| 3 | 爭點整理表埋在總覽底部(`issueSheetCard`) | `ui/app.js` `issueSheetCard`(約第 348 行) |
| 4 | 答辯狀的逐點表態沒有表格,只能讀書狀全文 | 訴狀分頁 `pleadingPanel` |
| 5 | 診斷分頁只畫舊的三個鍵(對原告不利之處、對被告不利之處、建議補強證據),新鍵沒有呈現 | `ui/app.js` `verdictPanel`(約第 1006 行) |
| 6 | 起訴狀 v1 與 v2 看不出差異 | `engine/pleading_diff.py` 已有 `complaint_diff(old_text, new_text)`,**API 還沒接** |
| 7 | 執行只有「只產起訴狀」「跑完全程」,沒有「跑到答辯狀」「跑到爭點整理表」 | 後端 `resume_plan` 已回 `stop_after_options`(`server/live_run.py` 約第 661 行);UI `runBtn`(約第 1857 行)只做了 complaint |

已經做好、不用重做的:版本列只放起訴狀與答辯狀、準備書狀與意旨狀另一張卡(`roundDocsCard`);v2 攻防分頁的新流程文字與 P1–P5 標題;起訴審查補正改看起訴狀「四、程序事項」(`proceduralCoverageBanner`、`procIssueItem` 的 `cured_in === "complaint"`)。

## 2. 要做的(只改 v2 案件,舊錄製案維持原樣)

判斷 v2:`isV2(d)`(`d.case.protocol === "v2"`)。舊案的分頁、文字、測試都不要動;`tests/test_ui*.py` 有綁舊文字的斷言。

**建議先做 B、D、E**(簡報最可能截圖的畫面),再做 A、C,F、G 有時間再做。競賽 2026-11-07,以簡報為主。

### A. 分頁照流程排

v2 案件用另一組分頁(舊案照舊 `TABS`):

| 分頁 | 內容 | 資料 |
|---|---|---|
| 案件總覽 | 進度軌(B)、案件輸入、執行紀錄 | 現有 |
| 起訴前檢查 | 照舊 | 現有 |
| 起訴狀(P1、關卡 1) | 起訴狀 v1 與律師版、關卡卡片 | 現有 `pleadingPanel` 原告側 |
| 答辯狀(P2) | 逐點表態表(C)與答辯狀全文 | `d.pleadings.defendant.structured` |
| 爭點整理表(P3) | D | `d.issue_sheet` |
| 準備書狀與意旨狀(P4、P5) | 雙方各兩份書狀;論證原文可折疊放這裡(取代「攻防過程」) | `pleading_versions` 中 `pleading_type` 為 `brief`、`closing`;`d.arguments` stage 2、3 |
| 診斷與起訴狀 v2(P6) | E、F | `d.verdict`、`pleading_versions` 中 `source === "system_revision"` |
| 引用查證 | 照舊 | 現有 |

「機械彙整」對 v2 只剩讓步條件(引用清單差異已標「新流程不適用」),併進診斷分頁的一張卡即可。路由用 hash(`#/<案件ID>/<分頁>`),舊網址 `#/<id>/debate`、`#/<id>/verdict`、`#/<id>/pleading` 對 v2 案件要導到新分頁,不要壞連結。

### B. 總覽的進度軌

P0–P6 各一格:案件輸入 → 原告分析 → 起訴狀 v1 → 關卡 1 → 被告分析 → 答辯狀 → 爭點整理表 → 準備書狀(雙方)→ 意旨狀(雙方)→ 診斷 → 起訴狀 v2。每格顯示已落地／進行中／未開始,點了跳到對應分頁。

- 步驟清單與完成判定**後端已有**:`server/live_run.py` `RUN_STEPS_V2` 與 `_pipeline_missing_v2`(續跑計畫 `resume_plan` 回的 `landed_keys`)。建議在 `get_case_detail` 加一個 `v2_progress`(照 `RUN_STEPS_V2` 的順序回 `[{key, label, done}]`),UI 不要自己重算,免得和續跑判定不一致。
- 關卡 1 要顯示「律師確認」或「自動通過,未經律師確認」(`d.gates.complaint`,已有 `gateCard` 可參考)。
- 舊的統計(「雙方 × 3 階段」「法官訊問」)對 v2 換成:爭點數、不爭執事項數、引用通過數、書狀份數。

### C. 答辯狀的逐點表態表

`d.pleadings.defendant.structured`(`stored_answer` 存的):`responses[]`(`fact_id`、`stance`、`ground`、`reason`、`hypothetical`)、`defenses[]`(`type`、`statement`、`legal_basis`、`hypothetical`)、`to_confirm[]`。

- 表格欄位:CF、原告主張(從起訴狀正文取該〔CF〕那一行;`engine/pleading_render.py` `complaint_facts` 是同一邏輯,可在後端先組好)、表態(`STANCE_LABEL`:不爭執／否認／爭執其形式上真正／待被告本人確認)、理由(`GROUND_LABEL` 加 `reason`)、推測標記。
- 抗辯清單:推測的標「推測」,`legal_basis` 用現有的引用 chip。
- `to_confirm` 列為「待被告本人確認」。
- 頁首註明:模擬被告只讀起訴狀,不是對方實際的答辯。

### D. 爭點整理表分頁

`d.issue_sheet`:`sheet`(`undisputed`、`issues`、`clarifications`、`questions`)、`text`(後端 `render_issue_sheet` 組好的四張表文字)、`undisputed_note`。

- 四張表用表格畫:表一聲明與請求權基礎、表二預期不爭執事項、表三爭點整理表(序次、爭點、原告主張、原告證據、被告抗辯、被告證據、法律依據、舉證責任;推測爭點標「推測」)、表四證據清單。欄位對齊司法院標準化須知例示 3–5(規格 5.5)。
- 闡明(`clarifications`)與訊問(`questions`)分開列;`based_on` 以「官方事實層(」開頭的標「補正追問」,以「準備清單:」開頭的標「準備題・假設」(`isPrepQuestion` 已有)。
- 不爭執事項是空的時候要說明原因:「模擬答辯狀沒有任何一點表示不爭執」(兩件實跑都是 0 點,這是範本的保守規則,見 v2-wiring.md 第 5 節第 4 點)。

### E. 診斷分頁的新鍵

`d.verdict.risk_map` 的新鍵(格式見 `engine/diagnosis.py` 檔頭):

| 鍵 | 呈現 |
|---|---|
| `issue_assessment[]` `{issue_id, strength, reason}` | 爭點強弱表:爭點編號＋爭點文字(從 `d.issue_sheet.sheet.issues` 對)、強／中／弱(用顏色 chip)、理由 |
| `evidence_todo[]` `{issue_id, missing, why}` | 待補證據表;`issue_id` 是「官方事實層(<id>)」的標「程序」 |
| `complaint_revisions[]` `{fact_id, kind, suggestion}` | 起訴狀修改建議:`revise` 改寫、`add_alternative` 新增備位、`delete` 刪除;連到 F 的差異對照 |
| `fact_gaps[]` | 事實缺口清單 |
| `opponent_hypotheticals[]` | 「被告推測的事實,請向當事人確認」清單 |

舊三鍵照舊顯示。**不顯示勝訴機率**(規格:只給爭點強弱)。`verdict_main_text`、`verdict_analysis` 現在的顯示方式可沿用。

### F. 起訴狀 v1 與 v2 的差異對照

- 後端:在 `pleading_version` 或新端點用 `engine/pleading_diff.py` `complaint_diff(parent_text, text)`,`source === "system_revision"` 的版本對 `parent_id` 那一版。
- UI:選到起訴狀 v2 時多一個「與 #<parent_id> 比較」的切換,新增行綠、刪除行紅。
- v2 只是建議版,不取代關卡 1 確認的版本;banner 已有(`versionBanner`)。

### G. 執行按鈕加停止點

`resume_plan` 回的 `stop_after_options` 已有 `complaint`、`answer`、`issue_sheet`(依已落地的進度過濾)。UI 依這個陣列畫按鈕:「只產起訴狀(停在關卡 1)」「跑到模擬答辯狀」「跑到爭點整理表」「跑完全程」。送出照現在的 `stop_after` 欄位(約第 1645 行)。執行紀錄的 chip(約第 1749 行)補上 `answer`、`issue_sheet` 的標示。

## 3. 怎麼驗

**資料**:`v2-wiring` worktree 的 `database/v2-live.db`(不進版控,只在這台機器)有兩件跑完 P0–P6 的 v2 案件:`v2w-2026-11-03-gcis`(商工案,有甲證、有程序補正、有律師確認關卡的自動通過紀錄)與 `v2w-2026-11-03-e2e`(消費借貸案,沒有證據)。另有 5 件舊錄製案,用來確認舊畫面沒被改壞。

**伺服器**:主資料夾 `.claude/launch.json` 的 `v2-wiring-live`(埠 8150,啟動腳本在本 session 的 scratchpad,指向上面的資料庫並排除兩件來源裁判)。換機器或 scratchpad 不在時,自己起:

```
set LEGALDEBATE_DB_URL=sqlite:///<worktree>/database/v2-live.db
python main.py serve --port 8150 --no-browser
```

**檢查**:
- 每個新分頁在瀏覽器逐頁看兩件 v2 案件,深色、淺色都看;console 沒有錯誤;`node --check ui/app.js`。
- 舊錄製案(例如 `test-2026-10-27-gcis-001`)的分頁與文字不變。
- 測試:`tests/test_ui_v2_fixes.py` 的寫法(API 欄位斷言＋檢查 `app.js` 含新文字);後端新增欄位(`v2_progress`、差異對照)要有測試。離線全套:`python -m pytest -q -m "not network" --basetemp <暫存>`,目前基準 845 通過、3 略過。
- 不需要再花錢實跑:這批只動 UI 與 `server/services.py`、`server/app.py` 的讀取端。

## 4. 規則

- `ui/`、`server/` 原本是組長的檔案;這批延續使用者對 `v2-wiring` 的授權,改完推上 `v2-wiring`(或從它開新分支),由組長檢核,不要推 `pleading-exchange`、`main-finals-fixes`、`main`(`docs/zh/teammate-collaboration.md`)。
- 做完在 `docs/zh/iteration-log.md` 加一列(看到什麼、改了什麼、怎麼驗證、測試數字),並更新本文件第 1 節的現況。
