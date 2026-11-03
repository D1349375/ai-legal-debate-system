# v2 接線(P2–P6 範本、SKILL Step 4–13、讀檔白名單)

> 給組長檢核。分支 `v2-wiring`,從 `origin/ui-v2-fixes`(971a4a4)開,合進 `origin/demo-v2-inputs`。照協作規則,範本與 SKILL 是組長的檔案;這批由組員先寫好,組長檢核後再合。使用者 2026-11-03 決定:退回次數統一 2 次、商工案放回甲證1–2、`legacy-v1.md` 那句字號不刪(改用讀檔白名單擋)。

## 1. 內容

| 項目 | 檔案 | 說明 |
|---|---|---|
| 讀檔白名單 | `server/live_run.py` `read_denials`、`build_args` | v2 執行時,Read／Grep／Glob 只讀得到本次執行資料夾、本案件資料夾、skill 資料夾;`references/legacy-v1.md` 另外拒絕。見第 2 節 |
| 商工案甲證1–2 | `data/cases/test-2026-11-03-v2-gcis-001.json` | 照 P1 實跑放回裁處書、登記謄本;只取事實經過提到的名稱與日期,全文缺口寫進 `known_gaps` |
| P2 範本 | `defense_stage1_prompt.txt`、`answer_prompt.txt` | 被告只讀被告角色檔;分析 `cited_precedents` 給空陣列;沒有證據的 CF(含律師新增)不能 admit |
| P3 範本 | `issue_sheet_prompt.txt` | 逐條寫出 `issue-sheet` 的硬擋規則(W5-3);準備題寫「準備清單:I1:…」(W5-2);第零步看起訴狀「四、程序事項」(W5-4);禁用自承類用語 |
| P4/P5 範本 | `round2_prompt.txt`、`opponent_summary_prompt.txt`、`round3_prompt.txt` | 輸出含 `case_id`、`stage`、`basis`、`{OUTPUT_PATH}`(W6-2);用 `{RETRIEVAL_RULES}`(W6-3);依【爭點 Ix】分段;程序補正放第一個爭點段落最後(W6-7);受挫評估寫進內部檢討(T11) |
| P6 範本 | `diagnosis_prompt.txt`、`revision_prompt.txt` | 診斷讀法官角色檔與雙方 stage 2、3,`risk_map` 新鍵逐條列硬擋規則(W7-1);改寫讀原告角色檔的 `diagnosis`,律師段落對不到時列進缺口(W7-5) |
| SKILL | `SKILL.md` Step 4–13 | 取代「Step 4 以後」過渡段;回報改 Step 13(W7-6) |
| UI | `ui/app.js` | 版本列只放起訴狀與答辯狀,準備書狀與言詞辯論意旨狀另一張卡;v2 案件的攻防分頁改用新流程文字 |

## 2. 讀檔白名單

**為什麼不是放行規則**:2026-11-03 用真的 Claude Code(2.1.183)搭配本機假 API 實測,專案資料夾內的讀取預設放行,`Read(路徑)` 放行規則收不窄;只有拒絕規則有效。反過來,不限路徑的 `Read`、`Grep`、`Glob` 放行會放行專案**外**的讀取(worktree 外層的主資料夾也在專案外)。所以 v2 執行:

- 啟動時列出專案裡每一層要擋的兄弟項目,各一條 `Read(...)` 拒絕(`read_denials`);
- 拿掉不限路徑的 `Read`、`Grep`、`Glob` 放行,專案外一律被 dontAsk 拒絕;
- 不帶路徑的 Grep／Glob 不會被拒,但結果濾掉被拒的路徑(Grep 搜 1547 回「No files found」)。

測試:`tests/test_claude_permissions.py` `test_v2_reads_only_this_run_this_case_and_the_skill`(真的 CLI,設 `LEGALDEBATE_PROBE_CLAUDE=1` 才跑)、`tests/test_gate.py` `TestV2ReadAllowlist`(離線)。

**還擋不住的**:同一個執行資料夾裡的 `case.json` 與原告角色檔,被告的 subagent 仍讀得到,靠 `scripts/audit_run.py --agent 被告 --forbid case.json` 事後確認。執行途中才新增的頂層檔案不在清單裡。

## 3. 實跑紀錄

資料庫 `database/v2-live.db`(本 worktree,不進版控);伺服器 `serve --exclude 114年度台上字第1987號 --exclude 114年度台上字第1547號`,模型 claude-sonnet-5-5,每次上限 15 美元。案件 `v2w-2026-11-03-gcis`,由 API 照 `data/cases/test-2026-11-03-v2-gcis-001.json` 建案(含甲證1–2),原告商工查核即時查得「解散」。

| 執行 | 範圍 | 結果 | 花費 | 觀察 |
|---|---|---|---|---|
| #1 | 新案件,`stop_after=answer` | 失敗:帳號 session 用量上限(HTTP 429,和同帳號其他 Claude Code 共用),停在 Step 5 第一次退回後 | 3.91 美元 | 原告分析、起訴狀 v1、被告防禦分析落地。被告 subagent description 都含「被告」,只用被告快照與 `defendant_p2.jsonl`。答辯狀第一稿 `answer --check` 未通過(正文提到 95 台上 1900 但沒列進 citations),已照流程退回同一個 subagent。被告分析寫了「起訴狀自承／自陳」沒緊接原句(`record` 只警告),之後在被告範本改成一律寫「起訴狀記載「……」」。主 agent 派撰狀 subagent 時指定了 opus。**這一次啟動時還沒拿掉不限路徑的 Read 放行**(專案外讀得到) |

| #2 | 續跑,`stop_after=answer` | 成功 | 1.26 美元 | 答辯狀 #8 落地。逐點表態 8 點:待被告本人確認 4、否認 4(都是原告舉證不足)、不爭執 0。抗辯 6 項,其中除斥期間、短期時效、法定代理人利益相反標推測。`answer --check` 一次通過;引用 15 筆全部 published,3 則判決實質核對都支持 |
| #3 | 續跑,`stop_after=issue_sheet` | 成功 | 0.63 美元 | 爭點整理表落地:爭點 7 個(I4 除斥期間、I6 法定代理、I7 時效為推測,舉證責任「未定」),不爭執事項 0 個(答辯狀沒有 admit),闡明 2、訊問 12(準備題 2)、補正追問 1(清算人是誰、是否即被告甲)。`issue-sheet --check` 一次通過,法官只讀法官角色檔。轉述警告 1 則(CF6) |
| #4 | 續跑,跑完全程 | 成功 | 8.68 美元 | 準備書狀 #9、#10,言詞辯論意旨狀 #11、#12,診斷,起訴狀 v2 #13 都落地。被告準備書狀查證退回 1 次(112 台上 1305 同字號多份);改寫後**沒有再查證**就 `record`(已改 SKILL,見第 4 節)。起訴狀 v2 退回 2 次:正文提到判決沒列進 citations;「同法第52條」「違反營業稅法第51條」查證認不得(已改範本)。對手摘要 `check-summary` 兩份都 0 警告;診斷 `check-judge` 一次通過。警告:原告新增民法第544條、公司法第23條(第255條提示);書狀含「對造」3 處;v2 的 CF1–3 改寫後不是原文 |

| #5 | 消費借貸案 `v2w-2026-11-03-e2e`,新案件一次跑完全程(第 4 節的修改之後) | 成功,14 分鐘 | 2.79 美元 | P0–P6 全部落地(起訴狀 #14、答辯狀 #15、準備書狀 #16/#17、意旨狀 #18/#19、起訴狀 v2 #20)。只有起訴狀 v1 退回 2 次(statement_quote 不是原文;正文提到判決沒列),之後各步驟都沒有退回。沒有證據清單,逐點表態 4 點全部否認,不爭執事項 0。原告準備書狀有「被告主張」×2 的用語警告(這條規則是起訴狀用的,準備書狀本來就要回應被告主張,要不要對準備書狀放寬請組長決定)。起訴狀 v2 採用備位民法第179條 |

商工案四次合計 14.48 美元,兩案五次合計 17.27 美元。主 agent 派撰狀與法官 subagent 時常指定 opus(答辯狀、爭點整理、起訴狀 v2 都是),花費因此偏高;要不要在 SKILL 寫明不指定模型,請組長決定。

稽核(#1–#5,`scripts/audit_run.py`):五次都沒有讀取被拒。#5 用消費借貸案的 `forbid`(來源字號 1547 三種寫法、舊報告、舊輸入、講稿 `video/` 等)也沒有命中;對手摘要的名稱已不含「被告」。名稱含「被告」的 agent 沒有碰 `case.json` 與原告的角色檔、分析、論證;唯一命中是 #4「對手摘要(被告看對方)」讀原告準備書狀的公開論證,那是要送達被告的內容,不算洩漏,但名稱不該含「被告」(已改 SKILL)。全部 agent 都沒有碰 `demo_audit.forbid` 的任何一項。

**實跑後發現並修正的程式問題**:原告準備書狀正文標明「民事訴訟法第255條」卻沒列進 `cited_statutes`,`brief` 只擋清單裡的引用,書狀落地後畫面與匯出卡在「未放行」。`record` 的每輪檢查改成正文提到、清單沒列的法條與判決要退回(`tests/test_brief.py` `test_citations_in_the_public_text_must_be_listed`)。#9、#11 用 `verify 民事訴訟法第255條` 補查後可匯出。

**斷網重播(X10)**:`export-demo --out <暫存>` 匯出(兩件 v2 案件加原有 5 件錄製案:7 件案件、20 份書狀、2 份爭點整理表),匯入空資料庫,擋掉本機以外的所有連線後逐件打 API:0 次對外連線;兩件 v2 案件各有論證 6 筆、爭點整理表、診斷、7 份書狀,關卡 1 指到的版本對得上,14 份全部可匯出。匯出的準備書狀標題後「(模擬…)」移到副標題保留,檔名依書狀種類(`_brief_v9_`、`_closing_v12_`)。**沒有寫進 `demo/`**:要不要用這次的實跑取代示範資料,請組長決定(見第 4 節)。

稽核(#1,`scripts/audit_run.py`):名稱含「被告」的 agent 沒有碰 `case.json`、`plaintiff_view.json`、`p1_analysis.json`、`complaint.json`;全部 agent 沒有碰商工案 `demo_audit.forbid` 的任何一項(來源字號三種寫法、`corpus/judgments`、新舊輸入檔、`docs/live-run-records`、`demo/recorded_cases.json`)。只看工具輸入,看不到結果(審查 W8-3)。

## 4. 實跑後改的範本與 SKILL

| 問題(實跑) | 改法 |
|---|---|
| 被告分析寫「起訴狀自承／自陳」沒緊接原句(#1、#4) | 被告分析與兩輪範本:轉述書狀一律寫「起訴狀記載「……」」「被告於答辯狀稱「……」」,不寫自承類用語 |
| 被告準備書狀查證退回後,改寫完沒有再查證就落地(#4) | SKILL Step 7 第 5 點:改寫後一定再派乾淨的查證 subagent 查全部引用(主 agent 不讀輸出檔,不知道有沒有新增) |
| 起訴狀 v2 寫「同法第52條」被擋(#4) | 起訴狀 v2 與兩輪範本:法條一律寫全名 |
| 正文標第255條沒列進清單(#4) | 兩輪範本寫明正文提到的每個法條都要列;`record` 硬擋(第 3 節) |
| 對手摘要 subagent 名稱含「被告」(#4) | SKILL Step 8:名稱只寫「對手摘要 1」「對手摘要 2」 |

## 5. 待組長決定

1. **範本與 SKILL 的檢核**:這些是組長的檔案,本分支先寫好給組長看。
2. **示範資料**:要不要用這次實跑的兩件 v2 案件重新匯出 `demo/recorded_cases.json`(現在的 demo 是舊流程)。匯出指令見第 3 節;`recorded_party_checks.json` 只會匯出這個資料庫查過的那一筆,會蓋掉 demo 現有的 150 KB,要一起決定。
3. **subagent 模型**:主 agent 常指定 opus,要不要在 SKILL 寫明不指定(沿用 `CLAUDE_CODE_SUBAGENT_MODEL`)。
4. **答辯狀 admit 的門檻**:範本規定只有附證據、而且被告無從爭執的事實才能 admit,實跑結果 0 點 admit,爭點整理表因此沒有不爭執事項(X6 驗不到)。要放寬(例如官方文書記載的事實可以 admit)還是維持保守,請組長決定。
5. **UI 改成新流程介面**:已照 [ui-v2-flow-handoff.md](ui-v2-flow-handoff.md) 的 A–G 實作(v2 案件改用照流程排的 8 個分頁,舊案不變);和交接建議不同的地方寫在該文件第 0 節,請組長檢核。
6. **合併順序**:本分支已包含 `mff-small-fixes` → `t7-merge` → `live-run-v2` → `ui-v2-fixes` 與 `demo-v2-inputs`,合進 `pleading-exchange` 時可以直接合本分支。
