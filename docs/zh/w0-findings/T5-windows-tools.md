# T5 即時執行停用 PowerShell 工具(F7)

- **分支 / 工作目錄**:`main-finals-fixes` / `.claude/worktrees/main-finals-fixes`
- **做的人**:Codex。檢核:Claude。實跑驗證:C1。
- **調研**:[README 第 2 節 F7](README.md#f7-windows-上-cli-先用-powershell-工具被拒後查證-subagent-沒跑-verify)

## 問題

Windows 上的 Claude Code CLI 有 `PowerShell` 工具。即時執行只允許 `Bash(python main.py *)`,在 `--permission-mode dontAsk` 下 PowerShell 一律被拒,但模型看得到這個工具,會先試。W0 的 `stream.jsonl` 有 26 處 PowerShell;查證 subagent 用它跑 `verify` 被拒 2 次後沒有改用 Bash,主 agent 另派一個才完成 Step 8。

相關程式:`server/live_run.py` 的 `ALLOWED_TOOLS`、`DISALLOWED_TOOLS`、`build_args`、`build_prompt`、`build_pleading_prompt`(第 6 點「指令只能用 `python main.py ...`」)。

## 要做的

1. `DISALLOWED_TOOLS` 加入 `"PowerShell"`。既有的 `"WebFetch"`、`"WebSearch"` 保留,順序不動,新項目加在後面。
2. `build_prompt` 與 `build_pleading_prompt` 的指令說明改成:指令一律用 **Bash 工具**執行 `python main.py ...`,一次一個指令,不用迴圈或複合指令。派 subagent 時要把這句帶進 subagent 的指示(查 SKILL Step 8 有沒有對應說明,沒有就在 SKILL 的查證 subagent 指示加一句)。
3. 用 `claude --help` 或官方文件確認 `--disallowedTools` 接受工具名稱 `PowerShell`。**不要為了確認而跑 `claude -p`**(會用額度),能確認多少寫多少,剩下的在 C1 驗。
4. UI 的工具描述(`_describe_tool`)若遇到 `PowerShell`,目前會顯示「使用工具 PowerShell」,保留即可,不用改。

不要做:不放寬 `ALLOWED_TOOLS`;不改 `SNAPSHOT_ENV`。

## 測試(先寫)

- `build_args` 的輸出含 `--disallowedTools` 且其後含 `PowerShell`,原有兩項仍在。先看 `tests/test_claude_permissions.py` 已經測了什麼,加在同一檔。
- prompt 文字含 Bash 工具的說明(避免之後被改掉)。

## 完成定義

- 測試全過;離線全套通過數 = 基準 + 新增數。
- 實作紀錄寫出第 3 點查到的依據(說明出處,或寫「無法確認,待 C1」)。

## 檢核方式(Claude)

- 讀 diff,確認既有規則沒動。
- C1 實跑:`stream.jsonl` 裡 PowerShell 出現 0 次;查證 subagent 沒有因工具被拒而重派。

## 實作紀錄(Codex 填寫)

> 本項由組員以 Claude Code 實作(不是 Codex),工作分支 `t5-windows-tools`。

- 開始時間:2026-11-02 19:30
- 結束時間:2026-11-02 19:50
- 基準 commit:`982075a`(`main-finals-fixes`)
- 基準測試(指令與數字):`python -m pytest -q -m "not network" --basetemp <暫存資料夾>` → `307 passed, 1 skipped, 13 deselected`

### 迭代過程

| # | 做了什麼 | 看到什麼 | 決定 |
|---|---|---|---|
| 1 | 開工前搜尋 `DISALLOWED_TOOLS`、`--disallowedTools` 與「指令只能用」的所有用處 | 只有 `server/live_run.py`(定義、兩份 prompt、`build_args`)與 `tests/test_live_run.py` 的 `test_minimal_permissions` 用到;沒有文件或 UI 列出這份清單 | 改動範圍就是這兩個檔加 SKILL |
| 2 | 照本文件打算把測試加在 `tests/test_claude_permissions.py` | 該檔整個以 `pytestmark` 預設略過(要真的 claude.exe,設 `LEGALDEBATE_PROBE_CLAUDE=1` 才跑),加在那裡離線全套不會執行 | 改加在 `tests/test_live_run.py`,和現有 `test_minimal_permissions` 同一組 |
| 3 | 先寫 2 個測試再跑 | `2 failed`:`--disallowedTools` 之後只有 `WebFetch`、`WebSearch`;prompt 沒有 Bash 工具的說明 | 照預期失敗,開始改程式 |
| 4 | `DISALLOWED_TOOLS` 尾端加 `"PowerShell"`;兩份 prompt 的指令說明改成「一律用 Bash 工具…一次一個指令,不要用迴圈或複合指令…派 subagent 時把這一句寫進它的指示」 | 用 Python 改檔後 git 警告 CRLF:Windows 上 `write_text` 把整個檔案換成 CRLF | 以 LF 重寫一次,`git diff` 只剩 4 增 3 刪 |
| 5 | 初稿把「其他 shell 指令會被拒絕」寫成「其他 shell 指令與工具會被拒絕」 | Read、Grep、Agent 等工具是允許的,這樣寫會誤導 | 保留原句「其他 shell 指令會被拒絕」 |
| 6 | SKILL Step 8 查證 subagent 的第一項任務前加一句:派工時寫明用 Bash 工具、一個 `verify` 指令列出全部引用、不要用 PowerShell、不要用迴圈逐筆跑 | SKILL 原本沒有任何工具說明;W0 查證 subagent 正是用 PowerShell 的 `foreach` 跑 `verify` 被拒 | 加在原有句子的括號內,不動 Step 8 其他內容 |
| 7 | 跑 `tests/test_live_run.py` 與離線全套 | `43 passed`;全套 `309 passed, 1 skipped, 13 deselected` | 通過數 = 基準 307 + 新增 2 |

### `--disallowedTools PowerShell` 的依據

1. **參數接受工具名稱**:本機 `claude --help`(Claude Code 2.1.183)寫 `--disallowedTools, --disallowed-tools <tools...>  Comma or space-separated list of tool names to deny (e.g. "Bash(git *)" Edit)`。
2. **工具名稱就是 `PowerShell`**:進 git 的 `docs/live-run-records/run-1`~`run-4/stream.jsonl` 第一行(`system`/`init`)的 `tools` 清單都有 `"PowerShell"`。
3. **被列入的工具會從模型看得到的清單移除**:`DISALLOWED_TOOLS = ("WebFetch", "WebSearch")` 是 2026-10-28(`dbf8d87`)隨 UI 即時執行加入的,上面四份紀錄都是之後跑的(Claude Code 2.1.222、2.1.312)。四份的 `init` 工具清單都**沒有** `WebFetch`、`WebSearch`(兩者是 Claude Code 內建工具),但有 `PowerShell`;沒被允許也沒被禁止的 `Write` 仍在清單上。也就是說 `--allowedTools` 只管權限,`--disallowedTools` 才會把工具從清單拿掉,加 `PowerShell` 應有同樣效果。
4. **沒確認的**:subagent 是否同樣看不到 PowerShell、組長電腦上的 CLI 版本行為是否一致,**待 C1**。C1 檢查方式:`stream.jsonl` 第一行 `tools` 不含 `PowerShell`;全檔 `"name":"PowerShell"` 出現 0 次;查證 subagent 沒有因工具被拒而重派。
5. 依本文件指示沒有跑 `claude -p`。另一種不花額度的確認方式是仿照 `tests/test_claude_permissions.py`:讓 claude.exe 連本機假的 Messages API,看 CLI 送出的工具清單有沒有 `PowerShell`。這仍會執行 `claude -p`(但不連 Anthropic、不用額度),是否要做交給組長決定,本次沒做。

### 結果

- 最後測試(指令與數字):`python -m pytest -q -m "not network" --basetemp <暫存資料夾>` → `309 passed, 1 skipped, 13 deselected`(基準 `307 passed`)
- 新增測試與各自測什麼(`tests/test_live_run.py`):
  - `test_powershell_is_hidden_and_old_denials_stay`:`build_args` 的 `--disallowedTools` 之後剛好是 `WebFetch`、`WebSearch`、`PowerShell`,原有兩項與順序不變。
  - `test_prompts_say_to_use_the_bash_tool`:`build_prompt` 與 `build_pleading_prompt` 都含「指令一律用 Bash 工具執行」、「不要用迴圈或複合指令」與「派 subagent 時」。
- 改了的檔:
  - `server/live_run.py`:`DISALLOWED_TOOLS` 加 `PowerShell`(附一行註解);兩份 prompt 的指令說明改寫。
  - `.claude/skills/legal-debate/SKILL.md`:Step 8 查證 subagent 指示加一句工具說明。
  - `tests/test_live_run.py`:新增 2 個測試。
  - 本文件與 `docs/zh/main-finals-fix-list.md`:實作紀錄。
- 與本文件不同的做法與原因:測試加在 `tests/test_live_run.py` 而不是 `tests/test_claude_permissions.py`,因為後者預設整檔略過,離線全套不會執行(迭代第 2 列)。
- 沒解決或沒驗證的事:
  - 模型與 subagent 是否真的看不到 PowerShell、查證 subagent 是否因此一次跑完 `verify`,待 C1。
  - SKILL 這一句會在 T7 合併時一起進 `pleading-exchange`;若 W3 也改了 Step 8 開頭附近,合併時要留意。

## 檢核結果(Claude 填寫)

- 日期:2026-11-02
- 結果:**通過。**
  - `DISALLOWED_TOOLS` 尾端加 `PowerShell`,原本兩項與順序不變;兩份 prompt 改成「一律用 Bash 工具,一次一個指令」;`SKILL.md` Step 8 查證 subagent 指示加一句;新增 2 項測試。`ALLOWED_TOOLS`、`SNAPSHOT_ENV`、UI 工具描述都沒動。
  - Claude 在暫存 worktree 重跑離線全套:`309 passed`(基準 307 + 新增 2),和紀錄一致。
  - 依據屬實:本機 CLI `--help` 寫明 `--disallowedTools` 接受工具名稱;實跑 #1–#4 的工具清單都有 `Bash`、`PowerShell`,沒有已禁用的 `WebFetch`、`WebSearch`,被禁用的工具確實會從清單移除。
  - 測試放 `tests/test_live_run.py` 而不是任務文件指定的 `tests/test_claude_permissions.py`:後者預設整檔略過,放那裡離線全套不會跑,調整合理。
- 還沒驗證(C1):模型與 subagent 是否真的看不到 PowerShell;查證 subagent 能否一次跑完 `verify`。
- 留給 T7:`pleading-exchange` 的 v2 prompt(`server/live_run.py` `build_prompt_v2` 第 4 點)仍寫「指令只能用 `python main.py`」,T7 合併時一起改並補測試。組員兩次 P1 實跑被拒的是 Bash 的 `python -c`、heredoc、`>` 導向,不是 PowerShell,T5 處理不到。
- 要改的地方:無。
