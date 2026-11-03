# T7 把 main-finals-fixes 合併進 pleading-exchange

- **分支 / 工作目錄**:原寫 `pleading-exchange`;2026-11-03 實際改在工作分支 `t7-merge`(從 `origin/wiring-fixes` 開,組員六條分支加 `wiring-fixes` 都是 `pleading-exchange` 的直接後代,可以快轉),做完推分支,由組長檢核後合併。
- **做的人**:原寫 Codex;2026-11-03 組長同意由組員(Claude Code)做。檢核:Claude。前提:T1–T6、C1、T10(`65f6c6d`)都已完成並 commit;T11 還沒做,不在這次合併裡。

## 為什麼

`pleading-exchange` 是從 `cf6f98c` 開出來的,T1–T6 修在 `main-finals-fixes`。新架構也要有這些修正,而且 W0 的根因(F1、F2、F3、F5、F7)在新分支一樣存在。

## 要做的

1. 確認兩個工作目錄都乾淨。`pleading-exchange` 有未 commit 的檔就停下來回報,不要 stash。
2. 在 `pleading-exchange` 執行 `git merge main-finals-fixes`(一般 merge,不要 rebase、不要 squash)。
3. 實際衝突的檔(2026-11-03 在 `wiring-fixes` `1db311b` 上合併 `fdc2c0d`):`.claude/skills/legal-debate/SKILL.md`、`main.py`、`server/live_run.py`、`server/services.py`、`tests/fake_claude.py`、`docs/live-run-records/README.md`。原本預期的 `server/app.py`、`database/db.py` 自動合併成功。另有三處**不會出現衝突標記**但要一起改:`references/legacy-v1.md`(T2、T5、T10 改的舊流程段落搬到這裡了)、`build_prompt_v2` 的指令句(T5 只改了 v1)、`tests/test_gate.py`(合併後假 Claude 一律要求 `FAKE_CLAUDE_EXPECT_DB_URL`)。
   - `DISALLOWED_TOOLS`:新分支的既有規則**全部保留**,再加 T5 的 `PowerShell`。
   - `SNAPSHOT_ENV` 不動。
   - `server/services.py` `_anchor_check`、`get_case_detail`:新分支改過不少,T2 的比對邏輯要套在新分支的版本上,不要整段蓋掉。
   - 每個衝突怎麼解,寫進實作紀錄(檔案、衝突內容一句話、怎麼解、為什麼)。
4. T3、T4 的量測工具在新分支重跑一次(新分支的示範資料與 `protocol=v2` 案件),確認沒有新增誤擋或誤報。
5. 更新新分支的文件:
   - `docs/zh/pleading-exchange-handoff.md` 第 2 節:加一列「W0 後修正 T1–T6 已併入」,commit 先寫「未 commit」。
   - `docs/zh/iteration-log.md`:依該檔格式加一列,來源「實跑」(W0)與「查核」。
   - `docs/zh/pleading-exchange-plan.md` 的 W0 列改成已完成。

不要做:不 push;不併 `main`;不動組員維護的檢索模組。

## 測試

- 合併後離線全套測試全過。基準:`wiring-fixes` `1db311b` 719 通過、2 略過(原寫約 427 項,是 11/2 之前的數字)。
- 連網測試 11 項(手冊第 4 節的指令)若環境可連網就跑,不能就寫「沒跑」。
- 另開埠(用暫存資料庫)用瀏覽器看一個舊案、一個 `protocol=v2` 新案,確認 UI 正常、機械彙整核對顯示正確。

## 完成定義

- merge 完成、沒有殘留衝突標記(`git grep -n '<<<<<<<'` 為空)。
- 測試數字寫進紀錄。

## 檢核方式(Claude)

- 看 merge commit 的衝突解法,特別是 `DISALLOWED_TOOLS`、`_anchor_check`。
- 跑全套測試;另開埠看 UI。

## 實作紀錄(組員 Claude Code 填寫,2026-11-03)

- 開始時間:12:26(基準跑完後)。結束時間:見結果。
- 合併前兩邊的 commit:`wiring-fixes` `1db311b`(= `pleading-exchange` `2989919` 加組員六條分支與 `wiring-fixes`);`main-finals-fixes` `fdc2c0d`。之後再合第 1 批 `mff-small-fixes` `bc0e460`。
- 合併前基準測試:`python -m pytest -q -m "not network" --basetemp <暫存>`,**719 通過、2 略過、13 未選**(`1db311b`)。
- 做法:`git merge --no-ff origin/main-finals-fixes`(一般 merge,沒有 rebase、squash)。衝突解法與合併才需要的改動放在合併 commit `7952d4b`;W5-7(issue-sheet 轉述核對)另一個 commit;第 1 批另一個合併 commit。

### 衝突與解法

| 檔案 | 衝突內容 | 解法 | 理由 |
|---|---|---|---|
| `SKILL.md` | 新分支把舊流程搬到 `references/legacy-v1.md`;`main-finals-fixes` 改的是舊流程 Step 6、8、10 與「法官輸出被自承檢查退回時」 | 取新分支的 v2 runbook;四處修改(T2 機械彙整不抄進 verdict、T5 查證用 Bash 單一指令、T10 回報轉述警告、轉述警告不退回法官)逐字移進 `legacy-v1.md`。v2 的 Step 3 查證與 Step 10 回報也加上 T5、T10 的句子 | 審查 T7-1:只取新分支會讓三項說明消失,`legacy-v1.md` 還會叫主 agent 抄 `mechanical_anchor_json` |
| `main.py` | import(新分支多了 `re`、角色檔函數;T10 多了 `attribution_sources`);`cmd_verdict` 落地參數與結尾警告 | import 取聯集;`cmd_verdict` 用程式重算的 `anchor`(T2)、`protocol_version` 取 `_verdict_v2_gate`(W7);結尾先印 v2 警告,再印轉述警告 | 審查 T7-2:兩邊都要留,只取一邊 T2 失效或 W7 分流壞掉 |
| `server/live_run.py` | `DISALLOWED_TOOLS`(新分支加檢索快取 Read 規則;T5 加 PowerShell);補產書狀 prompt 第 6、7 點 | 既有規則全保留再加 `PowerShell`;第 6 點用 T5 的 Bash 說法,第 7 點保留新分支的「照 legacy-v1.md 處理」。`SNAPSHOT_ENV` 沒動 | T7 文件第 3 點;Step 9C 現在在 legacy-v1.md |
| `server/services.py` | import 兩處 | 取新分支的 import,加 T4 的 `review_warnings`、`strings_in` 與 T10 的 `attribution_review`、`attribution_warnings`、`attribution_sources`。`main-finals-fixes` 那邊的 `HISTORICAL_NOTE` 等是 `cf6f98c` 的舊 import,新分支已移除,沒有加回 | `_anchor_check`、`get_case_detail` 自動合併成功,T2 的比對邏輯套在新分支版本上(合併後 `test_server.py` 全過) |
| `tests/fake_claude.py` | import | 取新分支的(`run_v2` 還用 `finalize_case`、`record_verdict`);舊流程那段已照 T2 改成呼叫 `main.py verdict` | |
| `docs/live-run-records/README.md` | 兩邊各加一段 | 兩段都留 | |

### 迭代過程

| # | 做了什麼 | 看到什麼 | 決定 |
|---|---|---|---|
| 1 | 照上表解衝突;再改三處沒有衝突標記的地方:`legacy-v1.md`、`build_prompt_v2` 第 4 點、`test_gate.py` fixture 設 `FAKE_CLAUDE_EXPECT_DB_URL` | `git grep` 沒有殘留標記 | |
| 2 | 跑 `test_gate`、`test_live_run`、`test_cli`、`test_server` 等 8 個檔 | 1 項失敗:T5 的 `test_powershell_is_hidden_and_old_denials_stay` 斷言清單**剛好等於**三項,新分支多了三條檢索快取規則 | 改成「前三項是 WebFetch、WebSearch、PowerShell,且等於 `DISALLOWED_TOOLS`」。這是改既有測試的預期,原因:T7 文件要求保留新分支既有規則,原測試寫在沒有那些規則的分支上 |
| 3 | W5-7:先寫 `tests/test_issue_sheet_attribution.py` 3 項(轉述對方的話要警告且照樣落地、訊問依 `target_side` 判斷「你方」、逐字引用不警告) | 2 項紅燈(逐字那項本來就綠) | `main.py` 加 `_issue_sheet_attributions`,`cmd_issue_sheet` 在結構檢查通過後印轉述警告(`--check` 與落地都印),只警告 |
| 4 | 新增 `tests/test_t7_merge.py` 3 項:v2 prompt 有 Bash 說法、`legacy-v1.md` 有 T2/T5/T10 的句子且不再叫人抄 `mechanical_anchor_json`、v2 SKILL 的查證與回報句 | 全過 | |
| 6 | 合併後離線全套 | **4 項失敗**,都在 `tests/test_revision.py` `TestVerdictCommand`:W7 的測試在沒有 stage 2、3 的案件上落地評估,T2 之後 `main.py verdict` 會自己跑 `finalize_case`,沒有 stage 3 就拒絕落地。這就是審查 T7-2 說的兩邊交互,沒有衝突標記 | 不改程式(實際流程評估一定在 stage 3 之後),改測試:加 `add_rounds` 在評估前補雙方 stage 2、3(舊案另補 stage 1);`verdict()` 的 JSON 拿掉 `mechanical_anchor_json`(T2 起不再由模型提供,留著會多印一行「與程式重算結果不同」,舊案那項斷言 stderr 是空的)。斷言沒有改 |
| 5 | 合併第 1 批 `mff-small-fixes` | `server/seed.py` 衝突:新分支 `_TABLES` 加了 `issue_sheets`,第 1 批加了 `party_checks` | 兩個都留 |

### 結果

- 最後測試:見下方「最後數字」。
- T3、T4 量測在新分支的結果:**沒做**。v2 案件還沒有法官輸出(P3 以後沒接線),沒有東西可量;等 W5–W7 接線後的實跑再量(審查 T7-5)。
- 改了的檔(合併以外):`references/legacy-v1.md`、`SKILL.md`(v2 Step 3、Step 10 各一句)、`server/live_run.py`(`build_prompt_v2` 第 4 點)、`main.py`(`_issue_sheet_attributions`)、`tests/test_gate.py`、`tests/test_live_run.py`(上面第 2 點)、新增 `tests/test_issue_sheet_attribution.py`、`tests/test_t7_merge.py`、本文件。
- 沒做:`pleading-exchange-handoff.md`、`iteration-log.md`、`pleading-exchange-plan.md` 的 W0 列(第 5 點)由組長合併時一起更新;沒有另開埠用瀏覽器看舊案與 v2 案(第 3 批做完假 Claude 全程後一起看);連網測試沒跑。

## 檢核結果(Claude 填寫)

- 日期:
- 結果:
- 要改的地方:
