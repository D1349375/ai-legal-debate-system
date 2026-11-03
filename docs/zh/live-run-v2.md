# 即時執行的書狀交換流程(第 3 批:審查 A1–A6、假 Claude P0–P6)

> 組長不在時交給組員(Claude Code)的第 3 批。分支 `live-run-v2`,疊在 `t7-merge` 上。
> 改 `server/live_run.py`、`server/app.py`(停止點清單)、`main.py`(`serve --exclude` 與檢索指令讀排除清單)、
> `engine/judgment_search.py`(排除清單環境變數)、`tests/fake_claude.py`。**SKILL.md、範本都沒改**,下面第 2、3 節是給組長寫 SKILL 與範本時照用的名稱。

## 1. 步驟表(A1)

`server/live_run.py` `RUN_STEPS_V2`,續跑起點、落地是否連續、執行是否完成都看這張表,只看資料庫。

| key | 名稱(畫面與續跑提示) | SKILL.md | CLI | 完成判定(資料庫) |
|---|---|---|---|---|
| `analysis` | 原告請求權基礎檢驗 | Step 2 | `record` | 原告 stage 1 |
| `complaint` | 起訴狀 v1 | Step 3 | `complaint` | 系統起訴狀(`pleading_type=complaint`、`source` 為空或 system) |
| `gate1` | 關卡 1 | — | UI | `Case.gates_json.complaint` |
| `defense` | 被告防禦分析 | Step 4 | `record` | 被告 stage 1 |
| `answer` | 被告答辯狀 | Step 5 | `answer` | 系統答辯狀(`pleading_type=answer`) |
| `issue_sheet` | 爭點整理表 | Step 6 | `issue-sheet` | `IssueSheet` 有一列(**不再看 `CourtQuestion`**) |
| `stage2` | 第 2 輪論證(分方) | Step 7 | `record` | 雙方 stage 2 |
| `brief` | 準備書狀(分方) | Step 7 | `brief --round 2` | 雙方 `pleading_type=brief` |
| `stage3` | 第 3 輪論證(分方) | Step 8 | `record` | 雙方 stage 3 |
| `closing` | 言詞辯論意旨狀(分方) | Step 8 | `brief --round 3` | 雙方 `pleading_type=closing` |
| `verdict` | 診斷評估 | Step 9 | `verdict` | `Verdict` 有一列 |
| `revision` | 起訴狀 v2 | Step 12 | `revision` | `source=system_revision` 的起訴狀 |

- Step 編號照計畫第 3 節:W4 = Step 4–5、W6 = Step 7–8、W7 = Step 9–12;**回報改 Step 13**(審查 W7-6)。Step 10、11 留給評估的 `check-judge` 與查證(落地紀錄只有 `verdict`,所以表上沒有)。
- 分方的四步,`pipeline_missing` 列成「原告第 2 輪論證」「被告準備書狀」這種寫法;續跑時只有一方落地,`missing_sides` 寫另一方,prompt 照舊寫「只派某方」。
- `_auto_gate`:流程越過關卡 1(被告 stage 1 等有落地)就記自動通過。停止點是 `answer`、`issue_sheet` 時也記(這兩個停止點在關卡 1 之後)。

## 2. 停止點(A2)

`STOP_AFTER = ("complaint", "answer", "issue_sheet")`;API(`server/app.py` `StartRunRequest.stop_after`)同步放寬。

| 停止點 | prompt 寫的 | 停在 | 關卡 1 |
|---|---|---|---|
| `complaint` | 本次只跑到起訴狀(Step 1–3) | 起訴狀 v1 | 不自動通過,等律師 |
| `answer` | 本次只跑到模擬答辯狀:跑到 SKILL.md Step 5 | 答辯狀 | 自動通過 |
| `issue_sheet` | 本次只跑到爭點整理表:跑到 SKILL.md Step 6 | 爭點整理表 | 自動通過 |

- 續跑時能選的停止點在 `resume_plan()["stop_after_options"]`:停止點要在續跑起點之後;過了關卡 1 不能選 `complaint`。`stop_after_allowed`(UI 用)仍只代表「可以只跑到起訴狀」。
- UI 還只有「只產起訴狀」一個選項;`answer`、`issue_sheet` 目前只能用 API 指定(`POST /api/cases/<id>/runs` body `{"stop_after": "answer"}`)。要不要在 UI 加按鈕由組長決定。

## 3. 範本檔名(組長寫範本時照用)

全部放 `.claude/skills/legal-debate/templates/`。舊流程(`references/legacy-v1.md`)繼續用 `judge_question_prompt.txt`、`stage2_prompt.txt`、`stage3_prompt.txt`、`verdict_prompt.txt`,所以 v2 的這幾步**另開新檔**,不改舊檔(審查 W5-1、W6-2、W7-1 都提到舊流程共用同一份)。

| 步驟 | 範本 | 讀什麼(角色檔) | 輸出 |
|---|---|---|---|
| Step 4 被告防禦分析 | `defense_stage1_prompt.txt`(計畫已定的名字) | `role-view --role defendant` | stage 1 JSON(`side: defendant`) |
| Step 5 答辯狀 | `answer_prompt.txt`(計畫已定) | 被告角色檔 + 被告分析(`public-args --stage 1 --side defendant`) | `answer` 的 JSON |
| Step 6 爭點整理表 | `issue_sheet_prompt.txt` | `role-view --role judge` | `issue-sheet` 的 JSON |
| Step 7 第 2 輪 | `round2_prompt.txt` | 原告:`role-view --role judge`;被告:`role-view --role defendant`;雙方加爭點整理表 | stage 2 JSON(含 `case_id`、`stage`、`basis`,寫進 `{OUTPUT_PATH}`) |
| Step 8 對手摘要 | `opponent_summary_prompt.txt` | `public-args --stage 2 --side <對造>` | `check-summary` 的 JSON |
| Step 8 第 3 輪 | `round3_prompt.txt` | 同第 2 輪,加對手摘要 | stage 3 JSON |
| Step 9 診斷評估 | `diagnosis_prompt.txt` | `role-view --role judge`(含爭點整理表)、雙方 stage 2、3 公開論證、`finalize --for-judge` | `verdict` 的 JSON(新鍵見 `engine/diagnosis.py`) |
| Step 12 起訴狀 v2 | `revision_prompt.txt`(計畫已定) | 原告角色檔 + 評估的 `complaint_revisions` | `revision` 的 JSON |

`main.py prompt <範本名>` 會拒絕範本裡沒有的佔位符,可以當防呆(審查 A3)。

## 4. 執行 prompt(A3、A6)

`build_prompt_v2` 第 1 點改寫:

- `case.json` **只給主 agent** 判斷流程版本,「不得把這個檔案或它的路徑交給任何 subagent」。
- 各角色只讀自己的角色檔:原告 `role-view --role plaintiff`、被告 `--role defendant`、法官 `--role judge`(都加 `--out`)。SKILL 或範本要填案件事實的地方一律填該角色的角色檔。原本「SKILL.md 提到案件輸入檔或 `{CASE_FACTS_PATH}` 時填這個檔案」那句刪掉了。
- 第 4 點已是 T5 的 Bash 說法(T7 時改的,A6)。
- 沒有停止點時寫「本次跑完全程(到起訴狀 v2)」,不再寫「照 SKILL.md『Step 4 以後』接著跑」。

**注意**:現在的 SKILL.md「Step 4 以後」還是過渡做法(借舊流程)。這個分支的 prompt 已經照新流程寫,**SKILL Step 4–13 與範本接好之前,不要用這個分支做 Claude 實跑**,否則 prompt 與 SKILL 說法不一致。

## 5. 續跑(A4)

- v2 的 `landed.json`(`_export_landed_v2`)只放進度:論證只列 `side`、`stage`、`created_at`(**不含全文**,stage 1 有內部檢討);`confirmed_complaint`(關卡 1 確認版全文,起訴狀本來就是給被告讀的);各書狀的 id、方、種類、輪次、來源;`issue_sheet`(已落地的整理表,沒有時 `null`);評估只給 id 與版本。舊流程的 `landed.json` 不變。
- `resume_instructions_v2` 改寫:從 `SKILL.md <Step>(<名稱>)` 開始;「landed.json 只給你(主 agent)看進度……不要交給任何 subagent」;被告只讀 `role-view --role defendant`,法官讀 `--role judge`;關卡 1 確認版照舊寫明是哪一版。舊句「它含雙方內部檢討,給法官與摘對手摘要仍要用 public-args」刪掉(已經沒有內部檢討)。

## 6. 排除來源裁判(A5)— 組員提的做法

**由伺服器設定,檢索指令自己套用,不經過模型、不寫進 prompt。**

1. 啟動:`python main.py serve --exclude 114年度台上字第1987號 --exclude 114年度台上字第1547號`(字號或 JID,可重複;字號照第 5 批案件檔的 `demo_audit.exclude`)。格式錯就不啟動(`LiveRunManager` 啟動時用 `exclusion_keys` 解析)。
2. `LiveRunManager.start` 把清單設進 Claude Code 子程序的環境變數 `LEGALDEBATE_EXCLUDE`(`;` 分隔);沒設時把繼承來的同名變數清掉,免得上一次的設定殘留。
3. `main.py` 的 `judgment`、`search-judgments`、判決引用搜尋把環境變數併進 `--exclude`(`_exclusions`)。Claude Code 的 Bash 工具繼承環境變數,所以主 agent 與每個 subagent 跑的檢索指令都會套用。
4. `retrieval-rules` 與 `prompt --phase` 印出的檢索規則**不**併入環境變數(只照指令上的 `--exclude`),所以角色看不到排除了哪一件,也不會被提示哪一件是來源裁判。
5. 讀不到全文,`verify --read-by` 就會擋(`not_read_by_side`),來源裁判不會被當成引用落地。

為什麼不放 `case.json`:`case.json` 是 UI 建案時從資料庫產生的,UI 建的案件 ID 和 `data/cases/` 的檔名不同,對不上;放進 `case.json` 也等於讓主 agent 讀到來源字號。為什麼不寫進 prompt 叫主 agent 帶 `--exclude`:那要靠模型照做,而且字號會出現在派工檔與檢索規則裡。

限制:同一個 `serve` 跑的所有案件都套用同一份清單(示範時兩件的來源裁判一起排除,對其他案件無害)。`audit_run.py --forbid` 仍要另外跑,因為 Read、Grep 直接讀 `corpus/judgments/` 不經過檢索指令(審查 W8-3)。

## 7. 假 Claude(`tests/fake_claude.py` `run_v2`)

- 照第 1 節的順序落地 P0–P6 全部步驟:原告分析、起訴狀 v1、被告分析、答辯狀(`render_answer` 組成,有逐點表態)、爭點整理表、雙方 stage 2 與準備書狀、雙方 stage 3 與言詞辯論意旨狀、評估(`risk_map` 含新鍵,`protocol_version=v2-pleading-exchange`)、起訴狀 v2(`record_complaint_revision`)。
- 認得三個停止點(prompt 的「本次只跑到起訴狀/模擬答辯狀/爭點整理表」),續跑時跳過資料庫已有的紀錄。
- 內容是固定的假資料,直接寫資料庫,**不經過 `main.py` 的檢查**(只為了讓步驟表與畫面跑得完)。
- 另外把收到的 `LEGALDEBATE_EXCLUDE` 寫進執行資料夾的 `exclude_env.txt`,測試用。
- 瀏覽器用法:`FAKE_CLAUDE_DELAY=0.3` 之類讓每步停一下;啟動方式見第 4 批文件(瀏覽器驗證是在第 4 批的分支上做的)。

## 8. 實作紀錄

- 2026-11-03 約 12:30–13:10(組員,Claude Code)。基準 `t7-merge` `51ae2e2`,離線全套 780 通過、2 略過、13 未選。

| # | 做了什麼 | 看到什麼 | 決定 |
|---|---|---|---|
| 1 | 讀 `live_run.py` 的步驟表、`_pipeline_missing_v2`、`_resume_plan_v2`、`export_landed`、`_auto_gate`、`start`,與 `test_gate.py` | 舊表在 `answer` 之前還有 questions、stage2、stage3、verdict(借舊流程);`_auto_gate` 只在「沒有停止點」時記 | 新增 `_v2_done` 一次算出各步驟,`_pipeline_missing_v2`、`_resume_plan_v2` 共用 |
| 2 | 先寫 `tests/test_live_run_v2.py`(33 項) | 第一次跑在 `pleading_side` 沒 import 就停 | 補 import 後 33 項全過 |
| 3 | 跑 `test_gate.py`、`test_live_run.py`、`test_server.py` | `test_gate.py` 5 項失敗,都是**照舊流程過渡做法寫的預期**:續跑 prompt 要有「legacy-v1.md Step 2」、`from_doc` 是 legacy、被告 stage 1 之後接「法官訊問」、`pipeline_missing` 最後一項是「被告答辯狀」、`stop_after="answer"` 會回 422、被告書狀只有 1 份 | 改這 5 項的預期,原因是本批要做的事就是把步驟表換成新流程(審查 A1、A2)。每處留註解。斷言的意思沒變的地方(只能續跑一次、關卡不被覆寫)沒動 |
| 4 | A5 | `retrieval_rules.build` 的規則文字會把 `--exclude` 的字號寫出來 | 環境變數只併進實際檢索,不併進規則文字(第 6 節第 4 點) |

- 新增測試(`tests/test_live_run_v2.py`,33 項):步驟順序與停止點清單;每一步落地後續跑起點是下一步(9 組);全部落地;答辯狀落地不再被判不連續;完成判定看爭點整理表;只落地一方;不連續要拒絕;三個停止點的 `pipeline_missing`;續跑可選的停止點;prompt 不把 `case.json` 交給角色、有三個 `role-view`;兩個新停止點的 prompt;續跑 prompt 不叫 subagent 讀 `landed.json`;v2 `landed.json` 沒有論證全文(哨兵字串)、有爭點整理表;舊流程 `landed.json` 不變;`judgment` 指令套用環境變數的排除(不連網就拒絕);`retrieval-rules` 不洩漏排除字號;`LiveRunManager` 把清單交給子程序且 prompt 沒有字號;格式錯的排除清單啟動就拒絕;假 Claude 跑完全程各步驟都落地;兩個新停止點會停、關卡自動通過、續跑起點正確;停在答辯狀之後續跑完成且 `landed.json` 沒有全文。
- 沒驗證:沒有 Claude 實跑(SKILL 與範本還沒接,第 4 節);`serve --exclude` 只在測試裡建 `LiveRunManager`,沒有真的啟動 `serve` 看印出的那行;沒有在 Windows 以外跑。

## 9. 測試數字

- 基準:780 通過、2 略過(`51ae2e2`)。
- 做完:**813 通過、2 略過、13 未選**(多 33 項,都是 `test_live_run_v2.py`;改了預期的既有測試只有 `test_gate.py` 5 項,見第 8 節第 3 點)。
