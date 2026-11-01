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

- 開始時間:2026-11-02 01:31（臺灣時間，開始填寫紀錄）
- 結束時間:2026-11-02 01:49（臺灣時間）
- 基準 commit:`b4de1bf`
- 基準測試(指令與數字):原指令 `python -X utf8 -m pytest -q -m "not network" -p no:cacheprovider` 得 `169 passed, 1 skipped, 13 deselected, 116 errors`，原因是 Windows 測試暫存目錄權限不足。改用 `python -X utf8 -m pytest -q -m "not network" -p no:cacheprovider --basetemp t1tmp --tb=short`，並以有權存取該目錄的執行權限重跑，得到有效基準 `285 passed, 1 skipped, 13 deselected`（150.69 秒）。

### 迭代過程

| # | 做了什麼 | 看到什麼 | 決定 |
|---|---|---|---|
| 1 | 執行指定的離線全套測試。 | `169 passed, 1 skipped, 13 deselected, 116 errors`；116 個錯誤都是 pytest 暫存目錄權限問題。 | 將測試暫存目錄設在此工作目錄內，重跑同一套測試取得有效基準。 |
| 2 | 設定 `TMP`、`TEMP` 指向工作目錄的 `.pytest_cache` 後重跑（另加 `--tb=short`）。 | 結果仍為 `169 passed, 1 skipped, 13 deselected, 116 errors`；pytest 仍使用無權限的系統預設暫存目錄。 | 改用 pytest 的 `--basetemp` 明確指定工作目錄內的新位置。 |
| 3 | 加 `--basetemp .t1-test-tmp --tb=short` 重跑離線全套測試。 | 測試仍有 116 個暫存目錄權限錯誤，且 pytest 結束清理時也遭 `PermissionError: [WinError 5]`；未產生有效總結。 | 改以有權存取 Windows 測試暫存目錄的執行權限，仍將測試資料放在此工作目錄。 |
| 4 | 以有權存取測試暫存目錄的執行權限執行 `python -X utf8 -m pytest -q -m "not network" -p no:cacheprovider --basetemp t1tmp --tb=short`。 | `285 passed, 1 skipped, 13 deselected`，無錯誤。 | 以此作為有效基準，先補 T1 回歸測試再改程式。 |
| 5 | 在 `tests/test_live_run.py` 新增環境變數、假 Claude 寫入及參數優先權三項測試，執行 `python -X utf8 -m pytest -q tests/test_live_run.py::TestDatabaseUrlResolution -p no:cacheprovider --basetemp t1tmp --tb=short`。 | 修正前 `2 failed, 1 passed`：`app.state.live.db_url` 仍為 `None`；假 Claude 因寫錯資料庫而回報 `incomplete`。這次測試意外在受保護的預設資料庫留下 `ui-20261101-001` 的測試紀錄。 | 先備份資料庫，為假 Claude 加測試用位址檢查，避免再寫錯；清理意外紀錄待使用者同意。 |
| 6 | 將預設資料庫複製到測試備份位置，並在 `tests/fake_claude.py` 加入僅於測試設定時啟用的資料庫位址檢查；重跑同一指令。 | 備份的 SQLite 完整性檢查為 `ok`；回歸測試仍 `2 failed, 1 passed`，假 Claude 在收到錯誤位址時以結束碼 4 停止，未再寫入錯誤資料庫。 | 保留這個測試護欄，開始修改程式。 |
| 7 | 依使用者同意，先將完整備份放在被 Git 忽略的 `database/t1-db-url-before-cleanup.db`，只刪預設資料庫內 `ui-20261101-001` 於四張指定表的列。 | 刪前筆數依序為論證 6、訊問 1、評估 1、書狀 2；刪後均為 0。W0b 前後維持 6、8、1、2；W0 前後維持 6、7、1、2；`citation_verifications` 總數前後皆 100；完整性檢查 `ok`。 | 意外測試紀錄已清除；後續維持假 Claude 位址檢查。 |
| 8 | `server/app.py` 在建立 session 前解析參數與環境變數，將同值傳給即時執行及 health；`server/live_run.py` 保留繼承環境變數後備；`main.py` 加資料庫類型啟動訊息。 | 尚未觀察測試結果。 | 先跑三項回歸測試，再跑離線全套。 |
| 9 | 執行 `python -X utf8 -m pytest -q tests/test_live_run.py::TestDatabaseUrlResolution -p no:cacheprovider --basetemp t1tmp --tb=short`。 | `3 passed`（5.88 秒）。 | 接著跑全套離線測試，確認既有行為未退化。 |
| 10 | 執行 `python -X utf8 -m pytest -q -m "not network" -p no:cacheprovider --basetemp t1tmp --tb=short`。 | `288 passed, 1 skipped, 13 deselected`（166.18 秒），較有效基準增加 3 項通過，無新失敗。 | 檢查 diff 與工作樹，完成實作紀錄及修正清單。 |
| 11 | 檢查程式與測試 diff、清理兩個測試暫存目錄，並唯讀複查預設資料庫。 | `git diff --check` 無錯；測試案件在四張表仍均為 0 筆，SQLite 完整性檢查 `ok`；備份仍留在被 Git 忽略的 `database/t1-db-url-before-cleanup.db`。 | 完成文件紀錄；保留備份供檢核。 |
| 12 | Claude 檢核通過後，首次嘗試將七個 T1 檔案加入 Git 暫存區。 | Git 無法建立工作樹的 `index.lock`，回報 `Permission denied`；檔案未加入暫存區。 | 改用有權寫入 Git 索引的執行權限重試，仍只指定七個 T1 檔案。 |

### 結果

- 最後測試(指令與數字):`python -X utf8 -m pytest -q tests/test_live_run.py::TestDatabaseUrlResolution -p no:cacheprovider --basetemp t1tmp --tb=short`：`3 passed`；`python -X utf8 -m pytest -q -m "not network" -p no:cacheprovider --basetemp t1tmp --tb=short`：`288 passed, 1 skipped, 13 deselected`。兩者皆以可存取 Windows 測試暫存目錄的執行權限執行。
- 新增測試與各自測什麼:`tests/test_live_run.py` 新增 3 項：環境變數未明傳參數時，管理器與 health 都使用自訂資料庫；假 Claude 子程序寫入環境變數指定的資料庫；明傳 `db_url` 時優先於環境變數。
- 改了的檔:
  - `server/app.py`：在 `create_app` 開頭解析資料庫位址，供 session factory、即時執行與 health 共用。
  - `server/live_run.py`：子程序環境變數先保留已解析或繼承的值，再後備到預設資料庫。
  - `main.py`：啟動時只顯示「預設資料庫」或「自訂資料庫」，不顯示完整位址。
  - `tests/test_live_run.py`：新增三項資料庫位址回歸測試。
  - `tests/fake_claude.py`：測試要求預期位址時先檢查，錯誤位址立即停止，避免再污染預設資料庫。
  - `docs/zh/w0-findings/T1-db-url.md`：逐次記錄嘗試、測試數字與資料庫意外寫入的修復。
  - `docs/zh/main-finals-fix-list.md`：於文末新增「W0 後修正」與 T1 一列。
- 與本文件不同的做法與原因:指定的原始 pytest 指令因 Windows 暫存目錄權限而產生 116 個環境錯誤；有效基準與最後全套測試須加 `--basetemp t1tmp --tb=short` 並使用可存取該目錄的執行權限。測試護欄額外修改 `tests/fake_claude.py`。修正前第一次回歸測試曾意外寫入受保護的預設資料庫；取得使用者同意後，依指定四張表與案件 ID 清除 10 筆，保留被 Git 忽略的備份 `database/t1-db-url-before-cleanup.db`。文件紀錄與總清單是共同規則另外要求的變更。
- 沒解決或沒驗證的事:尚未用真實 Claude 與 UI 重跑 C1，故尚未驗證真實子程序的案件、商工查核與評估全程落在指定資料庫；也未實際啟動 `serve` 檢查終端訊息，只由程式碼確認不印完整位址。

## 檢核結果(Claude 填寫)

- 日期:2026-11-02
- 結果:**通過。**
  - diff:`create_app` 開頭解析一次,同一個值給 session factory、`LiveRunManager` 與 health;`live_run.py` 改成 `self.db_url or env.get(DB_URL_ENV) or 預設`,兩層都防;啟動訊息只印類型。改動只在任務文件允許的檔案,外加測試護欄 `tests/fake_claude.py`(合理,只在設了 `FAKE_CLAUDE_EXPECT_DB_URL` 時生效)。
  - 測試:Claude 自己重跑離線全套,`288 passed, 1 skipped, 13 deselected`(165.63 秒,`--basetemp` 指到 scratchpad),和紀錄一致。
  - 實際啟動:以 `LEGALDEBATE_DB_URL` 指向暫存資料庫啟動 `main.py serve --port 8131`,終端機印「資料庫:自訂資料庫」,`/api/health` 的 `database.path` 是「(自訂資料庫)」、案件數是暫存資料庫匯入的 5 件;worktree 的 `database/legal_debate.db` 前後 md5 相同。沒有印出完整路徑。
  - 資料庫清理:備份 `database/t1-db-url-before-cleanup.db` 被 `.gitignore` 的 `*.db` 排除;`t1tmp`、`.t1-test-tmp` 已清掉。
  - 真實 Claude 子程序寫入指定資料庫,仍待 C1。
- 要改的地方:無。
- 附記:系統暫存目錄的權限問題是 Codex 執行環境造成的,不是專案問題;之後的任務可以沿用 `--basetemp` 的做法。
