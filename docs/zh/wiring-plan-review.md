# W4–W8 接線計畫審查(組員,2026-11-03)

> 給組長。對照[計畫](pleading-exchange-plan.md)第 3 節 W4–W8、第 6 節備註、[規格](pleading-exchange-spec.md)、[接手文件](pleading-exchange-handoff.md),以及 `main-finals-fixes` 的 T7、T10、T11、C1 文件,看照計畫接線能不能跑通 P2–P6。
>
> - **基準**:`pleading-exchange` `2989919` 加上組員還沒合併的六條分支(到 `t9-check-summary` `9571e27`);`main-finals-fixes` `fdc2c0d`。
> - **做法**:每個 W 各派一個審查 subagent 讀程式與文件,只讀不改;組員再抽查約 12 項關鍵說法,標 ✔ 的是組員自己對過程式。其餘每項 subagent 都附了行號,組員沒有逐條重驗。
> - **沒做的**:沒有用假 Claude 或 Claude 跑過任何 P2–P6;沒有開瀏覽器看畫面。
> - 行號以 `9571e27` 為準。

## 1. 結論

**照計畫現在的寫法接線,P2–P6 跑不通。** 組員的純程式本身能用(各 W 的測試檔子 agent 都重跑過,全過),問題在計畫寫於組員程式之前,接線一定要做的事很多沒列進去。最大的三類:

1. `server/live_run.py` 的 v2 步驟表、完成判定、續跑還是舊流程的樣子(第 2.1 節),每接一個 W 都會被判「落地不連續」。
2. 範本:被告分析、答辯狀、起訴狀改寫三份不存在;法官、評估、stage2/3 的範本讀錯輸入或缺輸出欄位,而且舊流程也在用同一份。
3. 被告隔離:執行 prompt、續跑用的 `landed.json`、`public-args` 都會讓被告讀到原告的東西,X8 稽核一定命中。

建議的停損點見第 6 節。

## 2. 接線清單(計畫沒寫但要做的)

嚴重度:**擋** = 不做就跑不通;**誠** = 影響正確或誠實;**小** = 可以之後。

### 2.1 跨 W 共通:`server/live_run.py`

| # | 嚴重度 | 問題 | 證據 | 建議 |
|---|---|---|---|---|
| A1 | 擋 | ✔ `RUN_STEPS_V2` 把答辯狀排最後、指向 legacy Step 9;法官那步看 `CourtQuestion`;沒有 `brief`、起訴狀 v2。答辯狀一落地就被判不連續,爭點表落地仍判「缺法官訊問」,P6 改寫失敗仍記成功 | `live_run.py:545-549`、`523`、`572-577`、`597-605`、`1062` | 照新流程重排:分析 → 起訴狀 → 被告分析 → 答辯狀 → 爭點表(看 `IssueSheet`)→ stage2 → stage3 → `brief` → 評估 → 起訴狀 v2;`_pipeline_missing_v2`、`_auto_gate`、假 Claude 一起改 |
| A2 | 擋 | ✔ `STOP_AFTER` 只有 `complaint`,W4–W7 想單獨驗一段時停不下來,會跑進過渡的舊 stage2/3 | `live_run.py:69` | 加 `answer`、`issue_sheet` 等停止點,或比照 W2 在 prompt 加一句並標「不完整」 |
| A3 | 誠 | ✔ 執行 prompt 規定 `{CASE_FACTS_PATH}` 填 `case.json`,和「被告只讀角色檔」衝突 | `live_run.py:172` | 新範本改用角色檔佔位符;`main.py prompt` 會拒絕範本沒有的佔位符,可當防呆 |
| A4 | 誠/擋 | 續跑用的 `landed.json` 含雙方 stage 1 全文與內部檢討,續跑指示和 SKILL:90 叫後續步驟讀它;它又沒有爭點整理表,P4 以後續跑讀不到 | `live_run.py:203-207`、`660-689` | 被告改讀 `role-view --role defendant`;`export_landed` 加 `issue_sheet`;`resume_instructions_v2` 重寫 |
| A5 | 誠 | `--exclude`(排除來源裁判)沒有任何帶入路徑,`server/`、SKILL 都沒有 | 接手文件 3.3 第 3 項「最晚 W8 前決定」 | `build_prompt_v2` 加一條固定條件寫明排除字號,或 `case.json` 加欄位、SKILL 規定照帶 |
| A6 | 誠 | T5「用 Bash 工具、不要用迴圈」只改了 v1 的 prompt,T7 合併後 `build_prompt_v2` 仍是舊句 | 試合併後 `live_run.py:180` | T7 時一起改 |

### 2.2 W4 答辯狀

| # | 嚴重度 | 問題 | 證據 | 建議 |
|---|---|---|---|---|
| W4-1 | 擋 | ✔ `templates/` 沒有被告分析、答辯狀範本 | `templates/` 只有 complaint、judge_question、stage1–3、verdict | 新寫 |
| W4-2 | 誠 | `public-args --through-stage 1` 不分方,撰狀 subagent 會連原告分析一起拿到 | `db.py` `public_arguments` | 交被告分析檔,或組員加 `--side`(見第 7 節) |
| W4-3 | 擋 | SKILL Step 4–5 要寫:答辯狀落地前先 `verify` 全部引用(抗辯的新法條沒查過會被拒);判決要 `--review-json` 並 `verify --read-by defendant`;被告 subagent 的派工 description 含「被告」(`audit_run.py` 靠它篩);被告分析 `cited_precedents` 給空陣列;`answer --check` 退回流程;Step 10 回報逐點表態 | 計畫第 6 節 W4 列 | 照 Step 3 的寫法補 |
| W4-4 | 小 | 改 `DOCUMENT.defendant.lede` 會連舊錄製案一起改;逐點表態表讀 `pleadings.defendant.structured` | `app.js:19`、`services.py:393-403` | 依 `protocol` 分流 |

### 2.3 W5 爭點整理表

| # | 嚴重度 | 問題 | 證據 | 建議 |
|---|---|---|---|---|
| W5-1 | 擋 | 法官範本讀 Stage 1、輸出 `uncontested_points`;舊流程(`legacy-v1.md:48`)也用同一份 | `judge_question_prompt.txt:1-4`、`34` | 比照 W2,舊範本搬到 `references/` 再改寫 |
| W5-2 | 擋 | ✔ 計畫要保留第三步(準備清單),但 `issue-sheet` 只收「I1:」或「官方事實層(」開頭,「準備清單:」會被硬擋;UI 靠這個前綴辨識 | `issue_sheet.py:131-135`、`app.js:619` | 組員改 `issue-sheet` 收「準備清單:I1:…」(第 7 節),範本寫明格式 |
| W5-3 | 擋 | 計畫沒寫怎麼避免法官被反覆退回(最多 2 次)。範本要逐條寫出硬擋規則:`legal_basis` 只寫「OO法第N條」、證據只能用角色檔 `evidence` 的編號(被告證據實際只能空陣列)、`clarifications.based_on` 寫「I1」、`questions.based_on` 寫「I1:…」、`hypothetical` 是布林;P3 禁用自承、自認、自陳、坦承 | `issue_sheet.py:60-135` | 範本列規則 |
| W5-4 | 誠 | 「保留第零步」:第零步要看原告 Stage 1 的補正段落,v2 法官讀不到 | `pleading_render.py:192-195` | 改看起訴狀「四、程序事項」 |
| W5-5 | 小 | 陷阱段說要改 `check-judge`,但 `issue-sheet` 已自己檢查;`check-judge` 收到沒有 `questions` 鍵的爭點表會 KeyError | `main.py:151-156` | v2 的 P3 只跑 `issue-sheet`,不跑 `check-judge` |
| W5-6 | 誠 | `get_case_detail` 不回爭點表;`_progress`、起訴審查的「法官第 N 則追問」讀 `CourtQuestion` | `services.py:527-537`、`565`、`632` | UI 四張表可直接用 `engine/issue_sheet.py` `render_issue_sheet`;不爭執事項標明來自模擬答辯 |
| W5-7 | 誠 | T10 的轉述核對只接在 `check-judge`、`record`、`verdict`,v2 的 `issue-sheet` 沒有 | `main.py` `cmd_issue_sheet` | 接 W5 時加上 |

### 2.4 W6 準備書狀

| # | 嚴重度 | 問題 | 證據 | 建議 |
|---|---|---|---|---|
| W6-1 | 擋 | ✔ `brief` 要求該輪引用全部已放行,但 P4/P5 之後沒有查證步驟,論證又不可覆寫:一個引用沒過,書狀永遠落不了地 | `main.py:618`;規格第 4 節流程圖 | `record` 之前派查證 subagent 跑 `verify --read-by <side>`,不過就退回;`record` 過了接著跑 `brief` |
| W6-2 | 擋 | stage2/3 範本輸出沒有 `case_id`、`stage`、`basis`,也沒有 `{OUTPUT_PATH}`;`record` 直接取 `payload["case_id"]` 會 KeyError | `stage2_prompt.txt:53`、`main.py:198-199` | 重寫範本時加入,改用 `prompt --phase p4/p5 --side --case-dir` |
| W6-3 | 擋 | 範本還用 `{STATUTES_DIR}`、`{JUDGMENTS_DIR}` 加 Read/Grep,和禁止直接讀快取衝突 | `stage2:23,40`、`stage3:19,32` | 換 `{RETRIEVAL_RULES}`(p4、p5 規則已有);對造判例查核用 `judgment <字號> --snapshot --log --issue` |
| W6-4 | 誠 | 被告在 P4 讀得到事實:見 A3、A4 | | 被告讀 `role-view --role defendant`,原告讀 `role-view --role judge`(有答辯狀與逐點表態,沒有事實經過) |
| W6-5 | 誠 | 計畫要用哨兵字串驗被告讀不到事實,但 P4 的對手資料由 SKILL 拼出,沒有程式可測 | `tests/test_brief.py` 沒有這項 | 要嘛組員加 P4 角色檔指令,要嘛靠稽核並照實講 |
| W6-6 | 擋 | P5 對手摘要誰寫沒定;`public-args` 取 stage 2 一定連帶 stage 1,主 agent 自己摘又違反「大檔不經主 agent」 | `main.py:139-143` | 組員加 `--stage`、`--side`;小 subagent 摘,主 agent 只跑 `check-summary` |
| W6-7 | 小 | 第一個【爭點】標記之前的文字不進書狀,程序補正段落會消失 | `brief.py:24-28` | 範本規定放在哪個爭點底下 |
| W6-8 | 小 | 匯出會剝掉標題後的「(模擬…)」 | `pleading_export.py:75-78` | W8 做匯出時處理 |
| W6-9 | 小 | 規格 5.6 寫退回 1 次,第 7 節與 SKILL 寫 2 次 | | 選一個 |

### 2.5 W7 診斷與起訴狀 v2

| # | 嚴重度 | 問題 | 證據 | 建議 |
|---|---|---|---|---|
| W7-1 | 擋 | ✔ 評估範本讀案件事實全文與三階段紀錄,不讀爭點表和 CF;有爭點表時新鍵硬擋,v2 評估落不了地。舊流程也用這份 | `verdict_prompt.txt:3-4`、`legacy-v1.md:70` | 另寫 v2 評估範本;組員在 `role-view --role judge` 加爭點表(第 7 節) |
| W7-2 | 擋 | ✔ 沒有 `revision_prompt.txt` | | 新寫 |
| W7-3 | 誠 | ✔ v2 起訴狀**會**出現在畫面,但被標成「律師編輯版・基於#…・✓」;引用顯示 0/0 卻寫「存檔時逐條查證」;匯出檔名帶 `_lawyer`。(計畫第 6 節 W7 列組員寫「不會出現在畫面」是錯的,特此更正) | `services.py:365-399`、`508-513`;`app.py:291` | 另開第三種來源分支。**不能**直接把 `system_revision` 加進 `_is_system`,否則總覽的原告書狀會變成 v2(`services.py:657`) |
| W7-4 | 誠 | `check-judge` 沒呼叫 `_verdict_v2_gate`,要到查證完、`verdict` 落地才被退回 | `main.py:146-161` | 接上 |
| W7-5 | 誠 | 規格只寫改寫輸入是確認版與 `complaint_revisions`,但事實對應要用原告角色檔;確認版是律師版時,律師新增的事實可能對不上被擋 | `main.py:1173`、規格 5.7 | 輸入改原告角色檔,律師段落怎麼處理寫明並回報 |
| W7-6 | 小 | SKILL Step 9–12 和現有 Step 10 回報撞號 | `SKILL.md:99` | 回報改 Step 13 |

### 2.6 W8 收尾

| # | 嚴重度 | 問題 | 證據 | 建議 |
|---|---|---|---|---|
| W8-1 | 擋 | ✔ 兩件示範案的 v2 輸入檔都不存在,計畫沒寫誰做。gcis-001 沒有證據、金額、已知反應、缺口;e2e-001 的事實摘要含被告抗辯 | `data/cases/` 只有舊格式 | 今晚做,組員可以接(第 7 節) |
| W8-2 | 誠 | ✔ 消費借貸案的來源裁判 114 台上 1547 在 `corpus/judgments/`,答案(抵償抗辯)寫在 `demo/recorded_cases.json`(24 處)、`docs/zh/e2e-test-report-2026-08-09.md`、`e2e-001.json`。計畫說「留在 repo 外」不成立 | | 1547 加進排除與稽核;這三個檔也列進 `--forbid` |
| W8-3 | 誠 | `audit_run.py` 只看工具輸入,看不到結果:不帶路徑的 Grep、`grep -r` 搜到來源裁判時抓不到;檔名寫法(`TPSV,114,台上,1987,…`)和字號寫法不同 | `audit_run.py:16-18` | `--forbid` 同時帶 `台上,1987`、`114年度台上字第1987號`、`corpus/judgments`;不帶路徑的搜尋人工看;對外說「工具呼叫紀錄未見讀取」 |
| W8-4 | 誠 | X8 沒寫判準 | 計畫 W8 節 | 寫明 `audit_run --agent 被告 --forbid case.json --forbid p1_analysis.json --forbid landed.json --forbid "role --role plaintiff"` 結束碼 0 才算通過 |
| W8-5 | 不清楚 | X10:商工查核不在 fixture,斷網時查無字號只顯示 network_error;匯出排在 W11(11/5),X10 卻要 11/4 晚前驗 | `seed.py:23-27` | W8 當天就匯出並斷網重播;簡報不示範查無字號 |
| W8-6 | 小 | X3 沒門檻;X9「不同括號」沒定義;X7 逐句人工比對沒估工時;第 5 節採用條件缺一份 X1–X10 證據對照表 | 計畫 257-265 | 補判準 |

舊設計殘留第 3、4 項計畫寫得夠具體,照做得到;v2 的補產按鈕已隱藏(`app.js:1765`)。

## 3. T7 合併

- 組員六條分支是 `pleading-exchange` 的直接後代,**快轉,不會衝突**。
- ✔ 快轉後再和 `main-finals-fixes` 合併,`git merge-tree` 試合併有 6 個檔衝突:`SKILL.md`、`main.py`、`server/live_run.py`、`server/services.py`、`tests/fake_claude.py`、`docs/live-run-records/README.md`。T7 文件列的預期衝突檔不對(列了 `app.py`、`db.py`)。先 T7 再合組員分支,`main.py` 要解兩次,建議先快轉。

| # | 嚴重度 | 問題 | 建議 |
|---|---|---|---|
| T7-1 | 誠 | `main-finals-fixes` 改 `SKILL.md` 的是 v1 的 Step 6、8、10,這些段落在新分支已搬到 `references/legacy-v1.md`。衝突取新分支那邊,T2、T5、T10 的說明會消失,`legacy-v1.md` 還寫著要把 `mechanical_anchor_json` 抄進 verdict JSON | 四處修改移進 `legacy-v1.md` |
| T7-2 | 誠 | `cmd_verdict` 兩邊都要留:`anchor` 重算(T2)、`protocol_version`(W7)、兩組警告。只取一邊,T2 失效或 W7 分流壞掉 | T7 文件寫明解法 |
| T7-3 | 擋 | ✔ **不會有衝突標記**:`fake_claude.py` 合併後一律要求 `FAKE_CLAUDE_EXPECT_DB_URL`,`tests/test_gate.py` 沒設,18 項會回 4 而失敗 | fixture 加 `setenv` |
| T7-4 | 誠 | 不會有衝突標記:見 A6 | |
| T7-5 | 小 | T7 文件的基準數字(427)過時;前提沒提 T10;寫 Codex 做,協作文件寫組長;要在 v2 案件重跑 T3、T4 量測,但 v2 案件沒有法官輸出 | 更新 T7 文件 |
| T7-6 | 擋 | 計畫沒寫 T7 是 W8 的前置:沒有 T7,W8 缺 T1(指定資料庫)、T2(機械彙整誠實性)、T5、T6(X10 斷網重播) | 計畫標明 |

**T11 與 C3**:T11 改 stage2/3 範本,W6 也要改寫同兩份。建議 T11 不單獨做在 `main-finals-fixes`,組長接 W6 範本時直接把「受挫評估寫進內部檢討段落」寫進去;在 v2 裡更重要,因為段落外的自我評估會直接進到法官與對造讀的書狀。C3 只有 11/4 晚決定退回 `main-finals-fixes` 時才跑。

## 4. 待組長確認項目的建議(計畫第 6 節)

| W | 項目 | 建議 |
|---|---|---|
| W4 | 沒給版本用最新系統原稿 | **改**成 `current_complaint`,不開 CLI 參數(免得版本交給主 agent 選)。組員改(第 7 節) |
| W4 | 引用未通過的律師版不給被告;多給 `fact_evidence`;不給 `proves`;`ground` 硬擋;要先有被告分析才能落地;證物欄「模擬答辯未附證物」 | 接受。律師新增的 CF 不能 `admit`,範本要說明改用 `deny` 或 `to_confirm` |
| W4 | 判決要 `precedent_notes`、`--review-json`、被告讀過全文 | 接受,規格 5.4 的 JSON 範例補這兩欄,SKILL 多一個查證 subagent |
| W4 | 種類含「書」「文」當文書 | 接受(只警告) |
| W5 | `kind` 收 fact、law、defense;證據要在起訴狀證據裡;推測標示不一致只警告 | 接受 |
| W5 | `questions.based_on` 格式 | 接受,另收「準備清單:Ix:」(W5-2) |
| W5 | 訊問與闡明要不要寫進 `court_questions` | 訊問寫、闡明留在爭點表;要和 `record_issue_sheet` 同一次 commit,中途斷掉才不會只落一半。完成判定仍改看 `IssueSheet`(A1) |
| W6 | 段落標記「【爭點 I1】」;原告證物欄;第 255 條寫進【本稿產出說明】;`basis` 不是法條硬擋 | 接受 |
| W6 | 標題後綴 | 接受,但原告第 3 輪改「回應系統模擬的對造書狀」 |
| W6 | 沒有爭點表時不檢查 | 只到 W6 接線為止,之後 v2 沒有爭點表就拒絕落地,否則 P3 失敗時 P4 完全沒檢查就落地 |
| W7 | 新鍵欄位 | 接受;`check-judge` 接 `_verdict_v2_gate`(W7-4);`_is_system` 照 W7-3 改 |
| T9 | 摘要欄位、重摘最多 2 次、接在 v2 的 P5 | 接受 |

## 5. 要組長決定的事

1. **舊設計殘留第 2 項選 A 或 B**:審查建議 **B**(新流程顯示「不適用」)。A、B 都要改 `services.py` 的 `drift_detail` 與 `_anchor_check`,只改 `finalize_case` 會讓畫面出現紅色「不一致」;A 另外要處理律師版沒有結構化引用,而且 P5 只深化既有爭點,數字還是雜。它不擋 W8,但示範時不要講這個數字。選定後組員實作。
2. **`--exclude` 怎麼帶入**(A5)。
3. **兩件示範案輸入誰做**(W8-1)。
4. **T7 與 W4–W7 的先後**,以及 W4–W7 分項實跑要不要併進 W8 那兩次(計畫原則 4 要求每個範本改動都實跑)。

## 6. 時程與停損(審查建議)

關鍵路徑:快轉組員分支 → T7 → 範本與 SKILL Step 4–13 → `live_run.py` 步驟表 → 假 Claude 跑完 P0–P6 → 第一次 Claude 實跑。UI 和接線是同一個人,排不了平行。

| 時間 | 停損條件 | 沒達成 |
|---|---|---|
| 11/3 24:00 | T7 合併、離線全套通過、假 Claude 在瀏覽器跑完 P0–P6 | 當晚改用 `main-finals-fixes`,不等到 11/4 晚 |
| 11/4 10:30 | 商工案第 1 次 X1 通過 | 容許修一次重跑,13:00 截止 |
| 11/4 16:00 | 消費借貸案(商工案通過後才跑) | 只用商工案 |

每次實跑約 5 小時額度 25%,一天最多 3–4 次。建議砍:W9、W10;消費借貸案的命中對照改選做;時間軸做最小版。

## 7. 組員這邊的修改

審查也找到組員程式的問題。組員依「不改會不會擋 W8、會不會讓對外說法不實」分三級,前兩級已做完,在分支 `wiring-fixes`(疊在 `t9-check-summary` 上,一樣可以快轉)。

### 7.1 已做

| 審查編號 | 改動 | 介面變化(接線時注意) | 新增測試 |
|---|---|---|---|
| W5-2 | `issue-sheet` 的 `questions.based_on` 也收「準備清單:I1:…」(全形冒號也收),後面仍要接存在的爭點編號 | 無,只是多收一種寫法 | `test_issue_sheet.py` `test_prep_questions_keep_their_prefix` |
| W5-3 | `issue-sheet` 的結構問題與自承類用語**一次列出**(原本結構全過才查自承,要分兩輪退回) | 錯誤訊息可能同時有兩類 | `test_structure_and_admission_problems_come_back_together` |
| W4 待確認 1 | `defendant_view` 沒給版本時改用 `current_complaint`。`role-view --role defendant` 因此和 `answer`、`judge_role_view` 讀同一版 | 關卡 1 確認律師版後,`role-view --role defendant` 改給律師版(原本給最新系統原稿) | `test_answer.py` `test_without_a_version_the_confirmed_complaint_is_read` |
| W7-1、A4 | `judge_role_view`(`role-view --role judge`)多一個 `issue_sheet` 鍵:已落地的爭點整理表,還沒落地是 `null`。P4–P6 與續跑可以從這裡讀 | 新增鍵 | `test_landed_sheet_is_in_the_view` |
| W4-2、W6-6 | `public-args` 加 `--stage N`(只給這一階段)、`--side S`(只給這一方),可以和 `--through-stage` 一起用。例:P5 對手摘要 `public-args --stage 2 --side defendant` | 新增選用參數,不帶時行為不變 | `test_internal_review.py` `test_public_args_can_give_one_side_one_stage` |
| W7(審查第 6 點) | `revision` 沿用確認版起訴狀(律師版往上找系統原稿)已存的判決實質核對(`citation_review` 裡 `supports: true` 的),只有 v2 新加的判決要 `--review-json`;這次給的核對優先 | SKILL 只要對 v2 新增的判決派核對 | `test_revision.py` `TestInheritedReviews` 3 項 |
| W7(審查第 8 點) | `risk_map.evidence_todo` 的 `issue_id` 也收「官方事實層(<id>)」(程序事項要調閱的資料,例如清算人登記) | `verdict_prompt.txt` 寫新鍵時一併說明 | `test_evidence_todo_can_point_to_a_procedural_issue` |
| W6(審查第 8 點,T9) | `check-summary` 的「原句」改成**完整的一句或連續幾句**(以 。!?;換行斷句)。原本是子字串,只取「已罹於時效,惟起算日資料未載,待確認」的前半句也不警告 | 警告訊息改寫 | `test_check_summary.py` `test_half_a_sentence_is_not_verbatim` |
| W4(審查第 7 點) | `answer` 從逐點表態的 `reason` 另外抽判決:那一行因為引了起訴狀原文整行被濾掉,理由裡提到的判決原本不會被要求列進 `citations` 與查證 | 理由裡有判決時要列進 `citations` 並附 `precedent_notes` | `test_answer_pleading.py` `test_judgment_in_a_stance_reason_must_be_listed` |

審查第 6 點說 v2 新判決會被判「原告沒讀過全文」:查過,「讀過全文」的紀錄存在案件資料夾的 `retrieval_cache/plaintiff`(`server/live_run.py:922`),跨執行還在,所以只需要沿用實質核對。v2 新加、原告在本案沒讀過的判決仍然會被擋,這是對的。

### 7.2 判斷不必做(只記錄)

| 項目 | 理由 |
|---|---|
| W7-5 `record_gate` 沒排除 `system_revision` | 執行中不能確認關卡,自動通過在執行結束才記,正常流程碰不到;只是防呆 |
| `complaint_revisions` 的 `delete` 必填 CF | 規格一致性,不影響結果 |
| W6(審查第 12 點)第 255 條改用條號正規化比對 | 只是警告會誤報 |
| W6-7 第一個爭點標記前的文字消失 | 範本規定段落位置就能避開 |
| W6-5 P4 角色檔指令(哨兵測試用) | 可以靠稽核並照實講;組長要的話組員再做 |

### 7.3 還沒做、等組長

- **兩件示範案的 v2 輸入檔**(W8-1):組員可以接,等組長說要不要、輸入要照哪個欄位格式。
- **舊設計殘留第 2 項**:等組長選 A 或 B(第 5 節)。

### 7.4 實作紀錄

- 2026-11-03 08:13–08:26,基準 `9571e27`(`t9-check-summary`)。
- 基準離線全套:708 通過、2 略過、13 未選(在另一個乾淨 worktree 跑)。第一次基準和改檔同時跑,出現 2 個失敗,是改到一半的檔被測試讀到,作廢重跑。
- 做完:**719 通過、2 略過、13 未選**,新增 11 項(上表),沒有改既有測試的預期。
- 改了的檔:`engine/issue_sheet.py`、`engine/summary_check.py`、`engine/diagnosis.py`、`database/db.py`(`defendant_view`、`judge_role_view`)、`main.py`(`cmd_issue_sheet`、`cmd_public_args` 與其參數、`cmd_answer`、`cmd_revision` 與新函數 `_with_inherited_reviews`)、上述六個測試檔;計畫第 6 節 W7 列更正一句。
- 沒驗證:沒有用假 Claude 或 Claude 跑;範本與 SKILL 沒接,實際派工時會不會照新參數用,要接線後才知道。
