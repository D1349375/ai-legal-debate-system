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

(實跑後補)

## 4. 待組長決定

(實跑後補)
