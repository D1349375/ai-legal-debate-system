# T1 資料庫設定傳給即時執行的子程序(F1)

- **分支 / 工作目錄**:`main-finals-fixes` / `.claude/worktrees/main-finals-fixes`
- **做的人**:Codex。檢核:Claude。
- **調研**:[README 第 2 節 F1](README.md#f1-指定資料庫時即時執行的子程序寫到別的資料庫)

## 問題

以 `LEGALDEBATE_DB_URL` 指定資料庫啟動 `python main.py serve` 時,伺服器自己讀的是指定的資料庫,但 UI 觸發的 Claude Code 子程序被改寫成預設的 `database/legal_debate.db`。W0 第 1 次實跑因此作廢。

相關程式:

| 位置 | 現況 |
|---|---|
| `database/db.py` `make_session_factory` | `db_url or os.environ.get(DB_URL_ENV) or 預設`,伺服器端會讀環境變數 |
| `main.py` `cmd_serve` | `create_app(live=...)`,沒傳 `db_url` |
| `server/app.py` `create_app` | `LiveRunManager(factory, root=ROOT, db_url=db_url, ...)`,`db_url` 是 `None`;`/api/health` 以 `db_url is None` 決定顯示的路徑 |
| `server/live_run.py` 約第 703 行 | `env[DB_URL_ENV] = self.db_url or f"sqlite:///{default_db_path()}"`,把繼承的環境變數覆寫掉 |

## 要做的

1. 在 `server/app.py` `create_app` 開頭解析一次實際使用的資料庫位址:參數 `db_url` → 環境變數 `DB_URL_ENV` → `None`(預設檔)。同一個值傳給 `make_session_factory`、`LiveRunManager` 與 `/api/health`。
2. `/api/health` 的 `database.path`:用預設檔時維持 `database/legal_debate.db`;用自訂位址時維持「(自訂資料庫)」,**不要把完整路徑回給前端**(公開畫面不放本機路徑)。
3. `server/live_run.py` 那一行保留後備邏輯,但改成不會蓋掉已解析的值(例如 `self.db_url or os.environ.get(DB_URL_ENV) or 預設`),兩層都防。
4. `cmd_serve` 啟動訊息加一行說明目前用的是預設資料庫還是自訂資料庫(同樣不印完整路徑)。

不要做:不新增 `--db-url` 參數(現在用環境變數就夠,少一個介面);不改 `make_session_factory`。

## 測試(先寫)

- 設了環境變數、`create_app()` 不傳 `db_url` 時,`app.state.live.db_url` 等於環境變數。
- 用 `tests/fake_claude.py` 的既有機制跑一次即時執行:設環境變數、不傳 `db_url`,假 Claude 寫入的列要出現在**環境變數指的那顆**資料庫。這是 W0 第 1 次失敗的情境,一定要有。
- `/api/health` 在設環境變數時顯示「(自訂資料庫)」。
- 傳了 `db_url` 參數時以參數為準(既有測試應已涵蓋,確認仍通過)。

## 完成定義

- 上面測試全過;離線全套測試通過數 = 基準 + 新增數,沒有新失敗。
- `git diff` 只動 `server/app.py`、`server/live_run.py`、`main.py`(啟動訊息)與測試檔。

## 檢核方式(Claude)

- 讀 diff,確認三個使用點拿到同一個值。
- 跑新測試與全套離線測試。
- C1 實跑時刻意設 `LEGALDEBATE_DB_URL` 指向暫存資料庫,確認案件、商工查核、評估都落在那顆。

## 實作紀錄(Codex 填寫)

- 開始時間:
- 結束時間:
- 基準 commit:
- 基準測試(指令與數字):

### 迭代過程

| # | 做了什麼 | 看到什麼 | 決定 |
|---|---|---|---|
| 1 | | | |

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
