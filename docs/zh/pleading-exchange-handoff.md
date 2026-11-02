# 書狀交換改版:接手文件

> 更新於 2026-11-02(W2 程式完成後)。給下一個接手的 agent 或組員。每完成一項就更新第 2、3 節。
> 決賽 2026-11-07,程式 11/5 晚上凍結。

## 1. 先讀這些

| 順序 | 文件 | 看什麼 |
|---|---|---|
| 1 | 本文件 | 現況與下一步 |
| 2 | [pleading-exchange-plan.md](pleading-exchange-plan.md) | 每一項要改什麼、測試、實跑檢查、停損 |
| 3 | [pleading-exchange-spec.md](pleading-exchange-spec.md) | v0.2 規格 |
| 4 | [iteration-log.md](iteration-log.md) | 做過什麼、為什麼 |
| 5 | [retrieval-interface.md](retrieval-interface.md) | 組員的檢索介面,寫範本前要看 |
| 6 | [main-finals-fix-list.md](main-finals-fix-list.md) | W0 的檢查清單 V30–V46、M12 退回時的分級流程 |

規格與組員文件對基準分支的說法不同時,以本文件為準:新架構在 `pleading-exchange`,不從 `retrieval-optimization` 開。

## 2. 目前狀態

| 分支 | 工作目錄 | commit | 用途 | 遠端 |
|---|---|---|---|---|
| `pleading-exchange` | `.claude/worktrees/pleading-exchange` | `624fe8e`(W2)之後的文件 commit | 新架構主線 | 只 push 到 `e1b5436`,W2 沒有 push |
| `main-finals-fixes` | `.claude/worktrees/main-finals-fixes` | `cf6f98c` 之後 W0 修正陸續 commit(T1–T3 已完成) | 新架構沒過時的退路;W0 修正 T1–T6 在這裡 | 以 `git log` 為準 |
| `main` | 專案根目錄 | `aeb618e` | 最後保底,沒動 | 已同步 |
| `origin/retrieval-optimization` | 無 | `e8404f7` | 組員的檢索來源 | 組員維護 |

| 項目 | 狀態 | 驗證 |
|---|---|---|
| R0 檢索搬入 | 完成,`7ae2d9d` | 離線 383 項、連網 11 項、CLI 實測、瀏覽器示範案 25/25 |
| W1 案件輸入與起訴前檢查 | 完成,`ca38d03` | 離線 427 項、2 項略過;瀏覽器走過建案與舊案,深淺色都看過 |
| W0 第二批修正實跑 | 完成,在 `main-finals-fixes` 跑(2026-11-02) | 依手冊判準通過;找到 9 項問題,T1–T6 由 Codex 在 `main-finals-fixes` 修,T7 再合併進本分支。見 `git show main-finals-fixes:docs/live-run-records/w0-2026-11-02.md` 與該分支 `docs/zh/w0-findings/README.md` |
| W2 起訴狀 v1 | 完成,`624fe8e` | 離線 451 項、2 項略過(新增 24 項);P1 實跑見 `docs/live-run-records/w2-2026-11-02.md` |
| W3–W11 | 未開始 | 無 |

**新流程只接上 P0、P1。** v2 案件走新的 `SKILL.md` Step 1–3:原告分析(新檢索指令)→ 撰狀 subagent 交 JSON → `main.py complaint` 檢查事實對應、由程式組成正文、查證後落地。Step 4 以後暫時借舊流程(`references/legacy-v1.md`),被告仍讀全部案件事實,W4 才改。UI 的「開始執行」還沒有「只跑到起訴狀」的選項(W3 的 `stop_after`)。

## 3. 下一步

### 3.1 W0:已完成

2026-11-02 在 `main-finals-fixes` 跑完,依手冊判準通過(11 分 54 秒、2.89 美元、分類器中止 0)。找到的問題在該分支 `docs/zh/w0-findings/`:T1–T6 由 Codex 修在 `main-finals-fixes`,T7 合併進本分支;T8(條文內容核對)、T9(最強論點選句)只修本分支。**本分支不要自己修 T1–T6**,等 T7 合併,避免衝突。

### 3.2 W2:起訴狀 v1(已完成,`624fe8e`)

做了什麼、和計畫不同的地方、實跑結果:計畫第 6 節 W2 列、[iteration-log.md](iteration-log.md)、`docs/live-run-records/w2-2026-11-02.md`。

- `retrieval-rules` 還沒有,`SKILL.md`「P1 檢索規則」一節是暫代的固定文字,組員做好後改成填指令輸出。
- 實跑沒有走 UI 按鈕:用 `LiveRunManager.start` 同一條程式路徑,只在 prompt 末尾加「只跑到 Step 3」(W3 才有 `stop_after`)。所以 UI 會把這次執行判為「不完整」(缺 Stage 2、3 等),這是預期的。
- W0 的 T1(資料庫環境變數)還沒合併:實跑時不要設 `LEGALDEBATE_DB_URL`,用 worktree 預設資料庫。

### 3.3 W3:關卡 1 與續跑(下一步)

照計畫 W3。W2 留下的接點:

- `resume_plan`、`pipeline_missing` 還把任一書狀當成 Step 9 完成;v2 案件在 P1 就有起訴狀,一定要依 `protocol` 分流(第 7 節陷阱)。
- `get_case_detail` 已依 `pleading_type` 只取起訴狀/答辯狀(`database/db.py` `is_main_pleading`);`server/live_run.py` 的 `_system_pleadings` 與 `pleading_materials` 還沒改。
- 起訴狀的結構化內容在 `PleadingDraft.structured_json`;畫面目前只顯示正文,事實缺口與律師附註在正文後的【本稿產出說明】。

### 3.4 之後

W3 關卡 1、W4 答辯狀、W5 爭點表、W6 準備書狀、W7 診斷與 v2、W8 全程實跑、W9 三劇本、W10 全文互看、W11 對外材料。每項的細節在計畫裡。

| 時間 | 判斷 |
|---|---|
| 11/3 晚 | W1–W7 沒完成就不做 W9、W10 |
| 11/4 中午 | W8 主線最晚時間 |
| 11/4 晚 | 依計畫第 5 節決定是否採用。沒過就用 `main-finals-fixes`,新架構講成下一版設計 |
| 11/5 晚 | 程式凍結 |
| 11/6 | 只演練 |

## 4. 常用指令

```bash
python -X utf8 -m pytest -q -m "not network" -p no:cacheprovider
```

```bash
python -X utf8 -m pytest -q -m network -p no:cacheprovider tests/test_verify.py tests/test_fjud.py tests/test_law_lookup.py tests/test_judgment_search.py
```

```bash
python main.py verify "最高法院105年度台簡上字第33號" "最高法院105年度台上字第99999號"
```

預期:離線約 4 分鐘,目前 451 項通過;連網 11 項通過;第三條前者 `published`、後者 `not_found`。

手動試用時要用暫存資料與快取,不要寫進真的資料庫:

| 環境變數 | 用途 |
|---|---|
| `LEGALDEBATE_DB_URL` | 暫存資料庫,例如 `sqlite:///<暫存資料夾>/check.db` |
| `LEGAL_DEBATE_RETRIEVAL_CACHE` | 暫存檢索快取 |

瀏覽器驗證:預覽工具讀主目錄的設定,worktree 要另開埠啟動再用網址連(我們用過 8123)。瀏覽器會快取 `app.js`,看不到新畫面時先強制重新載入。

## 5. 不能違反的事

- **誠實**:錄製內容要標示,查證失敗照實顯示,單案結果不講成統計。參賽資料不實會被取消資格。
- **不用中國機構開發的模型、API 或 MCP。**
- **事實不能編**:模型不得補寫案情、清算人姓名或證據。被告的推測只能標 `hypothetical`。
- **不代替模型或律師**:不手改模型 JSON 後說是模型產出,編排者不代寫被退回的內容。
- **公開 repo**:不 commit `database/legal_debate.db`、本機絕對路徑、語料全文、個資。`送件/` 不進 git。
- **不要 push、不要併 `main`**,除非使用者明確要求。後續項目 commit 前先問使用者。
- **不要併 `retrieval-optimization` 或 `role-separation-redesign`**。那兩條有 662 個紀錄檔、含本機路徑,路徑長度也會讓 Windows checkout 失敗。
- **組員負責的檔案不直接改**:`retrieval-interface.md` 第二節列的檢索模組、`verify.py` 查證部分與檢索指令。要新介面就提出來。
- **`server/live_run.py` 保留兩處**:`SNAPSHOT_ENV` 環境變數、`DISALLOWED_TOOLS` 的三條規則。
- **輸出欄位**:不用 `reasoning`、`thinking`、`trace`、`analysis`、`internal`、`scratch` 命名,見規格第 8 節。
- **檢查規則**:結構可以硬擋,自然語言只警告。同一份輸出最多退回 2 次。
- 回覆使用者用繁體中文。

## 6. 等別人的事

| 等誰 | 事項 | 現況 |
|---|---|---|
| 使用者 | 把分支 push 給組員 | 未 push,組員拿不到 |
| 使用者 | 把基準分支的決定告訴組員 | 不確定是否已傳 |
| 組員 | `retrieval-rules` 指令 | 尚未實作 |
| 組員 | `search-judgments` 排除來源裁判的參數 | 還沒提出。沒有時用檢索紀錄稽核 |
| 組員 | 本機未推的修正 | 對方交接文件提到有未提交的改動 |
| 組員 | 更新介面文件的基準分支,之後改在 `pleading-exchange` 維護檢索 | 還沒通知 |
| 組員與使用者 | 引用設計第七節 | 建議決賽前只採 `basis` |
| 律師 | 規格第 10 節的待確認項目 | 沒有律師看過 |

## 7. 已知陷阱

| 地方 | 問題 |
|---|---|
| `server/services.py` `get_case_detail` | `pleadings[side]` 取最後一筆系統版。有 v2 或準備書狀後要依書狀類型過濾 |
| `server/live_run.py` `resume_plan` | 把任一書狀當成 Step 9 完成。v2 在 P1 就有書狀,不分流會拒絕續跑 |
| `server/services.py` `_is_system` | 只認 `None`、`system`,新增 `system_revision` 時要處理 |
| `server/seed.py` `_TABLES` | 新資料表要加入,否則匯出示範資料會遺失 |
| `main.py check-judge` | 目前以 `questions` 判斷輸入類型,W5 要改 |
| `database/db.py` `pleading_materials` | 只給舊案補產書狀用 |
| 被告隔離 | 只靠提示與調度,程式擋不住 `case.json`。要用 `scripts/audit_run.py`(W4 新增)稽核,對外也要照實講 |
| 來源裁判 | 示範案的原判決查得到,可能被模型搜到,拿來講命中前要先查紀錄 |
| P4、P5 對手摘要 | 沿用舊 Step 4 從 `public-args` 摘對造 stage 1。v2 原告的 stage 1 是 P1 分析,公開段落仍有事實經過與沒列進起訴狀的證據;被告在 P4 讀到就破了 P2 的隔離。規格 5.6 已改成摘對造書狀,W6 照做 |
| P6 法官讀 `public-args` | 同上,原告分析等於間接給了事實經過,和 5.5「法官不讀 `facts_summary`」不一致。規格 5.7 已改成只給 stage 2、3,W7 照做 |
| 主 agent 上下文 | 舊流程 run-4 主 agent 112 輪,上下文從 3.1 萬 token 長到 19.3 萬,每輪都重讀,約佔全程輸入 token 八成(子 agent 每個最多約 5 萬)。不是單一大檔,而是每派一個 subagent 固定多約 1 萬:回覆 JSON 進來一次、主 agent 再 Write 成檔一次;另外第一次 Read 範本約 1 萬、`finalize` 約 8 千、自行 Read `main.py` 原始碼約 8 千、範本 PDF 約 1 萬。v2 的 subagent 比舊流程多(P1、P2 各拆成分析與撰狀,另有 v2 改寫與多次查證)。P1 已改成交接檔案(`SKILL.md`「派 subagent 與交接檔案」):`main.py prompt` 填好範本寫成檔、subagent 自己讀;範本用 `{OUTPUT_PATH}` 讓 subagent 自己寫輸出、只回路徑;`role-view`、`public-args` 加 `--out`。W4 起的新範本照同一套寫 |
| `demo/recorded_live_checks.json` | `checks` 是空的,斷網示範「查無字號」可能沒有錄製結果,W8 要確認 |
| 離線測試偶發失敗 | `tests/test_live_run.py` 的 `test_pleading_run_lands_only_the_chosen_document` 曾失敗一次,原因未查明 |
| 舊 worktree | `.claude/worktrees/ui-live-run-0f7cc8` 的資料庫有實跑 #1–#4,處理前不要清理 |

## 8. 決賽材料還沒做

這些不在 git,放在專案根目錄的 `送件/決賽/`,接手前先讀 `決賽前統整_2026-10-31.md`。

- 投影片仍有已查明不成立的說法,例如「1 筆捏造字號攔截」。
- 問卷結果本機還沒有,附件 3 承諾的「回饋→修正」還沒兌現。
- 新架構定案後,簡報、講稿、擬答要照計畫 W11 改。沒定案前不要動。
