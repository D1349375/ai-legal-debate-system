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

- 開始時間:
- 結束時間:
- 基準 commit:
- 基準測試(指令與數字):

### 迭代過程

| # | 做了什麼 | 看到什麼 | 決定 |
|---|---|---|---|
| 1 | | | |

### `--disallowedTools PowerShell` 的依據

### 結果

- 最後測試(指令與數字):
- 新增測試與各自測什麼:
- 改了的檔:
- 與本文件不同的做法與原因:
- 沒解決或沒驗證的事:

## 檢核結果(Claude 填寫)

- 日期:
- 結果:
- 要改的地方:
