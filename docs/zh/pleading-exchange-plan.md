# 書狀交換改版:逐項實作計畫

> 依據 [pleading-exchange-spec.md](pleading-exchange-spec.md) v0.2。基準 commit `cf6f98c` 加上搬入的檢索引擎,離線測試 383 項通過。
> 所有估時都是判斷,不是量測。工作目錄 `.claude/worktrees/pleading-exchange`。

## 1. 原則

1. **一次做完一項**。上一項沒過,不開下一項。
2. **每項都讓流程能跑到底**。新流程未接上的部分暫用舊範本,不留斷點。
3. **先寫會失敗的測試,再實作**。
4. **改範本的項目要用 Claude 實跑**,只跑到該步驟,再人工讀產出。只過假 Claude 不算完成。
5. **每項完成後 commit 到 `pleading-exchange`**,不 push,不動 `main`。
6. **不要把語料全文、本機路徑、資料庫 commit 進公開 repo**。

每項完成時寫進第 6 節的紀錄:狀態、測試數字、實跑編號、分類器中止次數、耗時、和計畫不同的做法。也要更新 [接手文件](pleading-exchange-handoff.md) 與 [迭代紀錄](iteration-log.md)。

## 2. 時程與停損

| 日期 | 目標 | 判斷 |
|---|---|---|
| 11/2 | W0、W1、W2 | W0 失敗先查原因,不往下做 |
| 11/3 | W3–W7 | **晚上**:主線沒完成就不做 W9、W10 |
| 11/4 上午 | W8 主線全程實跑兩件 | |
| 11/4 下午 | 有餘裕才做 W9,再做 W10 | |
| 11/4 晚 | **決定是否採用**(第 5 節) | 沒過就退回 `main-finals-fixes` |
| 11/5 | W11 匯出、簡報、講稿、擬答 | **晚上凍結** |
| 11/6 | 只演練 | |

W1–W8 最晚可以延到 11/4 中午。超過就不做擴充,全力收斂主線。

## 3. 工作項目

### R0 搬入檢索(已完成,`7ae2d9d`)

**範圍**:從 `retrieval-optimization`(`e8404f7`)搬入 `engine/fjud.py`、`law_lookup.py`、`retrieval_cache.py`、`search_log.py`、`judgment_search.py`、`judgment_text.py`、`verify.py`、法規名稱索引、`main.py` 檢索指令、`--snapshot`、`live_run.py` 的快照環境變數與禁止直接讀規則,以及相關測試與文件。

**沒有搬入**:`role_protocol.py`、`citation_review.py`、職責分離的資料表與範本、`docs/live-run-records` 的 Codex 紀錄、評估結果 JSON。

**接線決定**:
- 這些檢索檔案由組員維護,之後他直接在本分支更新。
- `network_error` 取代 `verification_failed`;UI 保留舊標籤,舊紀錄還能顯示。
- `unsupported_law` 取代 `unknown_law`;同字號多份文件改回 `ambiguous`,不放行。這比 M5 嚴格。
- `_assert_all_published` 改用 `citation_warning`,舊版條文、已廢止與索引外法規都不放行。
- 連線失敗不再錄成查證結果(`server/seed.py`)。

**還要組員提供**:
1. `retrieval-rules` 指令。W2 的 `{RETRIEVAL_RULES}` 靠它;W2 開工時還沒有,就先在 `SKILL.md` 寫死介面文件第八節的規則,他做好再換。
2. `search-judgments` 排除來源裁判的參數(W8 示範案要用)。
3. 本機未推的修正。

**驗證**:離線 `383 passed, 2 skipped, 13 deselected`;連網 `11 passed`;CLI 實測 105 台簡上 33 `published`、105 台上 99999 `not_found`、銀行法第 29 條 `published`、108 年民法第 205 條 `version_unverified`、外星人保護法第 3 條 `unsupported_law`。

### W0 第二批修正實跑(分支 `main-finals-fixes`)

**為什麼先做**:新架構疊在 M9–M15 上。先有基準,後面出錯才分得清原因。

- **操作**:11/2 額度重置後,在 `main-finals-fixes` 另開埠啟動,建新案件(統編 29112102),兩份書狀都產。
- **檢查**:`main-finals-fix-list.md` 的 V30–V46。
- **決定**:依分類器中止次數決定是否把 `【內部檢討】` 改成結果型欄位(規格第 8 節)。
- **完成**:V30 全部落地;紀錄寫進該文件。沒過就依該文件的分級流程修。

### W1 P0 資料契約與起訴前檢查

**改動**:
- `database/schema.py`:`Case`、`PleadingDraft`、`CourtQuestion`、`LiveRun` 新欄位。
- `engine/precheck.py`(新):純函數。程序判斷參考組員 `engine/role_protocol.py` 的 `procedure_warning`,只複製邏輯,不併分支。
- `database/db.py` `record_case`:接新欄位,`protocol='v2'`。
- `main.py`:`case` 接新欄位;新增 `precheck`、`role-view`。
- `server/services.py` `create_case`、`get_case_detail`;`server/app.py` `CreateCaseRequest`。
- `server/live_run.py` `start`:`case.json` 寫入新欄位。
- `ui/app.js` `createPanel`、`submitCreate`:證據清單可增刪列、金額、對方已知反應、已知缺口。

**注意**:
- `role-view` 這時只做 plaintiff;defendant、judge 在 W4、W5 做。
- `parties` 分頁標題改「起訴前檢查」,key 不動。
- 舊案不顯示新區塊。

**測試**:
- T1.1 金額空白、100000、100001、500000、500001 的程序提示。
- T1.2 非金錢案由 ≤10 萬不得寫成小額。
- T1.3 交通事故案由同時提示第 403 條第 1 項第 7 款與第 427 條第 2 項第 11 款。
- T1.4 時效提示不含「已罹於」「已消滅」等結論字樣。
- T1.5 舊案件 JSON 仍可落地,`protocol` 為 NULL。
- T1.6 API 建案新欄位往返一致;非法金額回 422。
- T1.7 匯出再匯入後新欄位還在。

**驗證**:瀏覽器建一件 v2 案件,深淺色都看;舊案件畫面不變。不跑 Claude。

**估時**:半天。

### W2 P1 起訴狀 v1

**改動**:
- `engine/fact_points.py`(新):CF 標記抽取、事實對應檢查。
- `engine/pleading_render.py`(新):依司法院範例組成起訴狀。當事人欄帶入邏輯從 `main.py cmd_party` 與 `ui/app.js` `partyRepresentativeText` 整理成共用函數。
- `database/db.py` `record_pleading`:接 `pleading_type`、`round`、`is_simulated`、`structured_json`,閘門不變。
- `main.py complaint --case-id X --json F [--check]`。
- `server/pleading_export.py`:匯出移除 `〔CF…〕`;檢查 `lint_pleading` 是否受影響。
- `.claude/skills/legal-debate/templates/stage1_prompt.txt`:拿掉被告段,加入新欄位;語料路徑換成三個檢索佔位符。
- `templates/complaint_prompt.txt`(新):輸出 `basis`、`precedent_notes`。
- `SKILL.md`:新流程 Step 1–3,舊流程移到 `references/legacy-v1.md`。
- `server/live_run.py` `build_pleading_prompt`:舊案補產改指向 `legacy-v1.md`。

**陷阱(已讀程式確認)**:
- `server/services.py` `get_case_detail` 的 `pleadings[side]` 取最後一筆 system 版。之後有答辯狀與 v2,必須依 `pleading_type` 過濾。這一項就先改。
- `_is_system` 只認 `None`、`system`。
- `_pleading_citation_check` 從正文抽引用,要確認 `〔CF1〕` 不影響 `extract_citations`。
- 無人值守只允許單一 `python main.py` 指令(`server/live_run.py` `ALLOWED_TOOLS`),新流程不能靠管線或其他 shell 指令。

**測試**:
- T2.1 無證據也無逐字引述的事實被拒;對應不到的錯誤訊息點名 CF。
- T2.2 引述與主張經過只差空白時通過;改一個字被拒。
- T2.3 不存在的證據編號被拒。
- T2.4 解散案當事人欄是「清算人(待查明…)」,且不含任何姓名;沒查核的一方照實留空。
- T2.5 未 published 引用拒絕落地,DB 沒有新列。
- T2.6 匯出沒有 `〔CF`;畫面文字有。
- T2.7 舊案 `pleadings` 回應不變。

**實跑(Claude,只到 P1,用商工解散案)**:
- 中止次數、耗時、花費。
- 起訴狀沒有「被告主張」與流程用語。
- 逐點抽查事實都能在案件資料找到。
- 當事人欄沒有編造清算人。
- 檢索次數、實際上網抓全文數;`quote_not_found` 應為 0。

**估時**:大半天。

### W3 關卡 1 與續跑

**改動**:
- `server/live_run.py`:`RUN_STEPS_V2`、`resume_plan` 與 `pipeline_missing` 依 `protocol` 分流;`stop_after`;`build_prompt` 寫明跑到哪裡停。
- `server/app.py`:`RunRequest.stop_after`;`POST /api/cases/{id}/gates/complaint`,body 為 `version_id`、`action`(`continue`、`finish`)。
- `database/db.py`:關卡寫入 `Case.gates_json`,不可覆寫。
- `ui/app.js`:`liveRunCard` 加「只產起訴狀」與「跑完全程」;`pleadingPanel` 加關卡按鈕。
- `tests/fake_claude.py`:新增 v2 流程。

**陷阱**:現行 `resume_plan` 把任一書狀視為 Step 9 完成。v2 在 P1 就有書狀,舊邏輯會判成落地不連續而拒絕續跑,一定要分流。

**測試**:
- T3.1 `stop_after=complaint` 跑完狀態為 `succeeded`,不視為缺步驟。
- T3.2 未確認不能續跑;確認後從防禦分析開始。
- T3.3 引用未通過的律師版不能確認。
- T3.4 不指定停止點時全程跑完,`gates_json` 標 `auto`。
- T3.5 確認後 `role-view` 讀的是律師版。
- T3.6 舊案續跑行為不變(`tests/test_live_run.py` 全過)。

**驗證**:假 Claude 走一次瀏覽器流程;再用 W2 的 Claude 案件編輯後確認,看 prompt 與檔案是否指向律師版。

**估時**:半天。

### W4 P2 防禦分析與模擬答辯狀

**改動**:
- `main.py role-view --role defendant`、`main.py answer`。
- `engine/fact_points.py`:逐點表態檢查。
- `engine/pleading_render.py`:答辯狀,用司法院範例文字。
- `templates/defense_stage1_prompt.txt`、`templates/answer_prompt.txt`(新)。
- `SKILL.md` Step 4–5:明寫不得讀 `case.json`,`{CASE_FACTS_PATH}` 填被告角色檔。
- `ui/app.js`:`DOCUMENT.defendant.lede`、逐點表態表。
- `scripts/audit_run.py`(新):解析 `stream.jsonl`,列出每個 subagent 讀過的檔案。

**測試**:
- T4.1 漏一個 CF、重複一個 CF 都被拒。
- T4.2 律師新增、刪除 CF 後,以確認版為準。
- T4.3 無證據事實 `admit` 被拒。
- T4.4 `alternative_explanation` 未標推測被拒。
- T4.5 `role-view` 不含 `facts_summary`、`known_gaps`、內部檢討與未列入起訴狀的證據,用哨兵字串驗。
- T4.6 答辯狀有「模擬答辯」副標。

**實跑(接續 W3 案件)**:
- 用 `audit_run.py` 確認被告 subagent 沒有讀 `case.json`。這層隔離靠提示與調度,程式擋不住,要靠稽核,也要照實講。
- 人工比對:被告攻擊的是起訴狀寫的內容;有沒有比實跑 #4 明顯變窄。
- 待確認事項是否合理,沒有把資料未載寫成 `admit`。

**估時**:大半天。

### W5 P3 爭點整理表

**改動**:
- `database/schema.py`:`IssueSheet`;`server/seed.py` `_TABLES` 加入。
- `database/db.py` `record_issue_sheet`、`main.py issue-sheet`、`role-view --role judge`。
- `engine/issue_sheet.py`(新)。
- `templates/judge_question_prompt.txt`:改讀書狀,輸出爭點表、闡明與訊問。保留第零步補正審查與第三步法律題、事實題分流。
- `main.py check-judge`、`server/services.py`、`ui/app.js`:新增「爭點整理表」分頁,呈現官方四張表。

**陷阱**:`check-judge` 目前以 `questions` 判斷輸入類型,新輸出要同時檢查 `questions` 與 `clarifications`。`uncontested_points` 舊欄位不再用,`resume_instructions` 那句提示要依 `protocol` 分流。

**測試**:
- T5.1 不爭執事項來源非 `admit` 被拒,含 `to_confirm`。
- T5.2 爭點參照不存在的 CF、闡明參照不存在的爭點被拒。
- T5.3 商工追問 `官方事實層(plaintiff:dissolved):` 可落地,UI 標示不變。
- T5.4 匯出匯入後爭點表還在。
- T5.5 推測爭點在表上有標示。

**實跑**:爭點是否來自雙方書狀;舉證責任人工抽查;自承檢查退回次數。

**估時**:半天。

### W6 P4、P5 依爭點組織

**改動**:
- `templates/stage2_prompt.txt`、`stage3_prompt.txt`:依爭點分段,回應闡明。
- `main.py brief`:組成書狀,不呼叫模型。
- `engine/issue_sheet.py`:爭點涵蓋檢查;第 255 條與推測字樣警告。
- `SKILL.md` Step 7–8。

**陷阱**:`aggregate.py`、`public_arguments` 不動。`pleading_materials` 只給舊案用。P4 的對手資料是對造書狀(規格 5.6),不是 `public-args` 的 stage 1;P5 的對手摘要只從對造 stage 2 萃取,最強論點要逐字。測試要用哨兵字串驗被告在 P4 讀不到事實經過。

**測試**:
- T6.1 缺爭點段落被拒;推測爭點不強制。
- T6.2 `brief` 同輸入輸出一致,且不含內部檢討與 falsifier。
- T6.3 原告新增民法條文有第 255 條警告,但可落地。
- T6.4 `finalize` 與 `anchor_check` 不受影響。

**實跑**:V44 對手摘要逐字;雙方是否真的回應闡明。

**估時**:半天。

### W7 P6 診斷與起訴狀 v2

**改動**:
- `templates/verdict_prompt.txt`:`risk_map` 新增鍵,保留舊鍵。
- `main.py` `PROTOCOL_VERSION` 依案件分流;`verdict` 檢查新鍵的結構。
- `templates/revision_prompt.txt`(新)、`main.py revision`。
- `server/services.py`:`difflib` 差異;`ui/app.js` `verdictPanel`、`pleadingPanel`。
- `SKILL.md` Step 9–12;引用查證涵蓋新增引用。

**測試**:
- T7.1 v2 含被告推測內容被拒。
- T7.2 v2 新事實對應不到被拒。
- T7.3 `parent_id` 指向確認版,不是原稿。
- T7.4 診斷文字含勝訴機率類字樣時警告。
- T7.5 舊評估顯示不變。

**實跑**:補證清單是否指到具體爭點;v2 差異律師讀得懂;程序事項仍先於實體。

**估時**:半天到大半天。

### W8 主線收尾與全程實跑

**改動**:
- `ui/app.js`:新增「書狀時間軸」,v2 案件預設顯示;P2–P5 標模擬並預設收合;總覽放起訴狀 v1、補證清單、v2。
- `_progress` 依 `protocol` 分流。
- `server/pleading_export.py` 支援四種書狀標題與檔名。

**兩件案件**:

| 案件 | 用途 | 輸入 |
|---|---|---|
| 商工解散案(統編 29112102) | 商業組主軸 | 取自 114 台上 1987 原審認定,證據只列案件事實提到的文件 |
| 消費借貸案 | AI 工具組主軸 | 由 `e2e-001` 拆層:輸入只留原告方,被告抗辯留在 repo 外當對照 |

**防污染**:兩件的來源裁判在 `corpus/judgments/`。`audit_run.py` 檢查有沒有 subagent 讀到來源裁判,讀到就不能拿來講「命中」。

**全程檢查**:
- X1 全部步驟落地,不靠人工修改 JSON。
- X2 每個 subagent 的中止次數;同角色同階段 3 次都中止算失敗。
- X3 時間與花費,對照 #4 的 14 分 39 秒、估 3.25 美元。
- X4 起訴狀 v1、v2 沒有被告主張與流程用語。
- X5 逐點表態涵蓋全部 CF。
- X6 不爭執事項全部可追溯到 `admit`。
- X7 自承類用語逐句人工對照,不成立數為 0。
- X8 被告隔離稽核通過。
- X9 第 249 條與 115 台抗 105 不同括號,沒有編造清算人。
- X10 匯出後乾淨 clone、斷網可重播。

**對照(只看方向,不是統計)**:消費借貸案比對被告攻擊與保留的真實抗辯,列命中、漏掉、多出。事實型抗辯先前偏弱,要看推測內容有沒有改善。

**估時**:UI 半天,實跑與檢查半天。

### W9 三劇本與關卡 2(擴充)

**前提**:W8 兩件都通過。

- `DefenseScenario`、`main.py scenarios`、`templates/scenario_prompt.txt`、關卡 API 與 UI。
- `resume_plan` 插入新步驟。
- **測試**:未勾選不能續跑;無人值守預選並標示;未選劇本留在報告;推測不進原告交付書狀。
- **實跑**:一件,確認三個劇本實質不同,不只換句話。

**估時**:半天。

### W10 全文互看與第 255 條細化(選做)

只有 W9 完成且 11/4 下午還有時間才做。要跑同案對照,比較 `position_drift`、用語重複與新論點數。結果不明確就維持摘要。

### W11 定案後的對外材料

| 位置 | 要改 |
|---|---|
| 兩組投影片第 3、4 頁 | 改成書狀交換流程;第一輪互相看不到的說法改掉 |
| 兩組投影片第 5 頁 | 示範改為時間軸:v1、模擬答辯、爭點表、補證清單、v2 |
| AI 組第 6 頁 | 測試數字、時間、花費改新實跑 |
| 共同擬答 Q-A | 「第一輪互相看不到」改成:原告獨立分析,被告只看到起訴狀與公開資料,內部檢討不交換 |
| 擬答 N2、N5 | 新輸入欄位與答辯狀性質 |
| 商業組 | 強調商工資料由程式直接帶入當事人欄 |

送件文件仍寫舊流程,要準備一句說明:決賽版已改版,送件時是舊流程。11/2 行前通知若允許更新就更新。

## 4. 解鎖的對外講法

| 通過 | 可以說 | 仍不能說 |
|---|---|---|
| W2 | 輸入後第一個產物就是起訴狀初稿,當事人欄由官方登記帶入 | 可直接遞狀 |
| W4、X8 | 模擬被告只讀起訴狀與公開資料,且事後稽核過 | 程式強制隔離 |
| W5 | 爭點表格式參考司法院標準化須知 | 法院一定採用 |
| W7、X1 | 系統會根據攻防產出補證清單與修改版起訴狀 | 修改後一定更好 |
| X3 | 這次實跑的時間與花費 | 平均數字 |
| 任一項 | | 縮短律師 N% 時間(沒有律師工時資料) |

## 5. 11/4 晚的採用條件

全部符合才採用:

1. W1–W8 完成,離線測試全過,兩件 X1–X10 通過。
2. 沒有靠人工修改模型輸出才落地。
3. 只跑一次通過也要照實講是單次結果。
4. 兩組示範案都能斷網重播。
5. 你讀過兩件的起訴狀 v1、v2 與補證清單,認為比舊流程的骨架有用。

有任何一項沒過,決賽用 `main-finals-fixes`,書狀交換講成下一版設計。

## 6. 進度紀錄

| 項目 | 狀態 | 測試 | 實跑 | 備註 |
|---|---|---|---|---|
| R0 | 已完成,`7ae2d9d` | 離線 383、連網 11 | 不需要 | 流程範本還沒接上檢索 |
| W0 | 已完成(在 `main-finals-fixes`) | | 2026-11-02 第 2 次通過 | 紀錄在該分支 `docs/live-run-records/w0-2026-11-02.md`;修正 T1–T6 由 Codex 進行 |
| W1 | 已完成,`ca38d03` | 新增 44 項,全套 427 項 | 不需要 | 瀏覽器走過建案、總覽、起訴前檢查,深淺色與舊案都看過。與計畫不同:這項只加 `Case` 欄位,其他表的新欄位等用到時才加 |
| W2 | 已完成,`624fe8e` | 新增 24 項,離線全套 451 通過、2 略過 | 2 次,只到 P1:第 2 次 5 分 12 秒、1.15 美元、5 小時額度 23%→28%、分類器中止 0、權限被拒 0 | 紀錄 `docs/live-run-records/w2-2026-11-02.md`。與計畫不同:實跑不是按 UI 按鈕(還沒有 `stop_after`),而是同一條程式路徑加一句「只跑到 Step 3」;撰狀後的查證與實質核對合成一個查證 subagent;`--review-json` 是新增的參數;正文出現的判決一定要列進 `citations`;事實點文字不是原文時只警告;`main.py party` 的法定代理人文字改用共用函數(已解散又董監事查詢失敗時,CLI 改顯示清算人,和 UI 一致);UI 沒有改,事實缺口與律師附註放在正文後的【本稿產出說明】 |
| W3 | 已完成,Claude 檢核通過(2026-11-02) | 新增 18 項(`tests/test_gate.py`),之後接組員第十三節第 4 件再加 3 項(`tests/test_complaint.py`);加完後離線全套:531 通過、2 略過、13 未選(5 分 27 秒),沒有新失敗。第一次全套(只有 18 項時):離線全套 528 通過、2 略過、13 未選(7 分 7 秒;合併組員檢索後的基準是 510 通過,加上新增 18 項),沒有新失敗。這次全套和瀏覽器伺服器、W2 複本腳本同時跑,沒有受影響 | 沒有(依指示只用假 Claude;`SKILL.md` 加了「關卡 1」一節、v2 有新的執行 prompt,都還沒經 Claude 實跑) | 與計畫不同:(1) 自動通過由後端在執行結束時記錄,不是主 agent 記;只在起訴狀之後真的有落地才記,中途失敗或取消時律師仍可確認。(2) 「到此結束」也要求版本引用全部放行(規格只寫「確認繼續」),因為結束後要能匯出。(3) v2 案件不選書狀、不能補產(Step 9C),API 拒絕。(4) 該案件執行中不能確認關卡。(5) 規格 5.3「新段落沒有〔CF〕提示」一併做了(`new_paragraphs_without_cf`,只提示)。(6) 每次執行另存 `prompt.txt`。(8) 依啟動 session 的補充,接了組員 `retrieval-interface.md` 第十三節第 4 件:`main.py complaint` 落地時要原告讀過全文(`read_by`),其他三件見接手文件 3.3。(7) `tests/test_live_run.py` 的 `create()` 改成直接落地舊案件,另一個斷言改成 `legacy-v1.md`(W2 留下的第 2 件),其餘不變。驗證:瀏覽器(暫存資料庫、假 Claude、埠 8141、8142;強制重新載入 `app.js`):新案件按「只產起訴狀」→ 執行完成、畫面停在關卡 1;律師版加一個查不到的字號 → 關卡兩個按鈕都停用、顯示未通過;再改一版移除 → 確認並繼續 → 版本列標「關卡 1 採用」;回總覽續跑 → 從被告防禦分析跑完,假 Claude 讀到的是律師版;另一件按「跑完全程」→ 關卡記為自動通過並顯示警示;舊錄製案件的書狀分頁沒有關卡區塊;W2 的 Claude 案件(複本)顯示關卡 1 等待中。深色、淺色都看過,console 沒有錯誤。途中發現 W3 之前的執行(W2 實跑)被標成「跑完全程」,但那次其實是在指示裡另外寫只跑到起訴狀,改成不加標籤;W2 案件用資料庫複本確認律師版後,prompt、`landed.json`、`role-view` 都指向律師版 |
| W4 | 程式部分完成(分支 w4-defendant-view 已合併;`scripts/audit_run.py` 在分支 w4-audit-run;`main.py answer` 與答辯狀組成在分支 w4-answer),範本、SKILL、UI 待組長接線 | 新增 10 項(`tests/test_answer.py`,T4.1、T4.3–T4.5;T4.2 只驗以傳入的正文為準),離線全套 527 通過、2 略過(做之前 517、2 略過) | 不需要 | 做了 `main.py role-view --role defendant`(`database/db.py` `defendant_view`)與 `engine/fact_points.py` `response_problems`。與計畫不同:律師確認版由呼叫端以 `complaint_id` 指定,CLI 還沒有參數,沒給就用最新系統版,待 W3 從關卡紀錄帶入;引用未通過(blocked)的律師版不能給被告;角色檔多給 `fact_evidence`(正文每個 CF 的證據編號,律師新增的 CF 為空),供 `admit` 檢查;證據只給編號、種類、日期、描述,不給原告律師寫的 `proves`;`ground` 的值也硬擋。還沒做:`main.py answer`、答辯狀組成(T4.6)、範本、SKILL、UI。**`audit_run.py`(w4-audit-run)**:新增 9 項(`tests/test_audit_run.py`),離線全套 569 通過、2 略過(做之前 560);列出主 agent 與每個 subagent(名稱取派工 `description`)讀、搜、寫過的檔與指令、工具次數、權限被拒次數;`--forbid` 比對工具輸入與派工 prompt,`--agent` 限定名稱,命中結束碼 1。路徑改成相對 cwd、家目錄遮成 `~/`,結果可進 git。在 run-1–4 與 P1 兩次實跑上跑過。看不到工具結果的內容,被告 subagent 的派工 `description` 要含「被告」才篩得準(待組長接 SKILL 時規定)。**`main.py answer`(w4-answer,疊在 w4-audit-run 上)**:新增 17 項(`tests/test_answer_pleading.py`),離線全套 586 通過、2 略過(做之前 569);被告讀的起訴狀取 `current_complaint`,明確傳給 `defendant_view`,不依賴它的預設;`engine/pleading_render.py` 加 `answer_problems`(逐點表態沿用 `response_problems`,另檢查 `defenses`、`legal_argument`、`citations`)、`render_answer`(T4.6:標題「民事答辯狀(模擬答辯,非針對實際起訴狀)」,答辯聲明依起訴狀有沒有聲請假執行調整第一項,第三項是否保留寫進【本稿產出說明】;逐點表態引起訴狀該點原文;推測標「推測」)、`stored_answer`(多存 `complaint_id`)。與規格不同或待組長確認:判決引用比照起訴狀要 `precedent_notes` 與 `--review-json`,查證要被告讀過全文(`read_by=defendant`);`authenticity` 警告以證據種類含「書」或「文」當文書;答辯狀沒有被證,證物欄寫「模擬答辯未附證物」;落地前要先有被告防禦分析(stage 1) |
| W5 | 未開始 | | | |
| W6 | 未開始 | | | |
| W7 | 未開始 | | | |
| W8 | 未開始 | | | |
| W9 | 未開始 | | | 主線通過才做 |
| W10 | 未開始 | | | 選做 |
| W11 | 未開始 | | | 定案後 |
