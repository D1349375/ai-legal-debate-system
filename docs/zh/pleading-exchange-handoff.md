# 書狀交換改版:接手文件

> 更新於 2026-11-02。給下一個接手的 agent 或組員。每完成一項就更新第 2、3 節。
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
| `pleading-exchange` | `.claude/worktrees/pleading-exchange` | `ca38d03` 之後的文件 commit | 新架構主線 | **沒有 push** |
| `main-finals-fixes` | `.claude/worktrees/main-finals-fixes` | `cf6f98c` | 新架構沒過時的退路 | 比遠端多 2 個 commit,沒有 push |
| `main` | 專案根目錄 | `aeb618e` | 最後保底,沒動 | 已同步 |
| `origin/retrieval-optimization` | 無 | `e8404f7` | 組員的檢索來源 | 組員維護 |

| 項目 | 狀態 | 驗證 |
|---|---|---|
| R0 檢索搬入 | 完成,`7ae2d9d` | 離線 383 項、連網 11 項、CLI 實測、瀏覽器示範案 25/25 |
| W1 案件輸入與起訴前檢查 | 完成,`ca38d03` | 離線 427 項、2 項略過;瀏覽器走過建案與舊案,深淺色都看過 |
| W0 第二批修正實跑 | **下一步,還沒跑** | 無 |
| W2–W11 | 未開始 | 無 |

**新流程還沒真正運作。** 新建案件會標 `protocol=v2`、存進新欄位,但 `SKILL.md` 與範本還是舊流程,模型還讀不到證據清單,也還沒用新檢索指令。W2 起才接上。目前也還沒有任何 Claude 實跑紀錄。

## 3. 下一步

### 3.1 W0:第二批修正實跑

在 `main-finals-fixes` 跑,不是新分支。目的是先有基準,之後出錯才分得清是新架構還是第二批。

1. 確認訂閱額度。一次約 15 分鐘,實跑 #4 用掉 5 小時視窗約 27%(單次數字)。
2. 在 `.claude/worktrees/main-finals-fixes` 啟動:

   ```bash
   python main.py serve --port 8124 --no-browser
   ```

3. 瀏覽器開 `http://127.0.0.1:8124`,建新案件:
   - 案由、事實、請求:照 `data/cases/test-2026-10-27-gcis-001.json`。
   - 原告統編 `29112102`,被告是自然人,不填統編。
   - 書狀選「兩份都產」,按開始執行。
4. 跑完依 `main-finals-fix-list.md` 的 V30–V46 檢查。V35–V37 要人工逐句對照。
5. 把時間、花費、分類器中止次數寫進 `docs/live-run-records/` 與該文件。不要 commit 語料全文或本機路徑。
6. 判斷:
   - 全部落地、V35 不成立數為 0:W0 通過。
   - 法官被自承檢查一直擋:照該文件文末的分級流程。
   - 分類器中止明顯變多:照規格第 8 節,把 `【內部檢討】` 改成結果型欄位。
7. 更新第 2 節與 `iteration-log.md`。

### 3.2 W2:起訴狀 v1

照計畫 W2 做。W0 沒有結果前不要開始。

- `retrieval-rules` 如果還沒有,先把 `retrieval-interface.md` 第八節的規則寫進 `SKILL.md`,範本照放 `{RETRIEVAL_RULES}`,組員做好再換。
- 先寫測試 T2.1–T2.7,再實作。
- 只跑到 P1,用商工解散案,一次約 5–8 分鐘(估計)。
- 完成後才進 W3。

### 3.3 之後

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

預期:離線約 3 分鐘,目前 427 項通過;連網 11 項通過;第三條前者 `published`、後者 `not_found`。

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
| `demo/recorded_live_checks.json` | `checks` 是空的,斷網示範「查無字號」可能沒有錄製結果,W8 要確認 |
| 離線測試偶發失敗 | `tests/test_live_run.py` 的 `test_pleading_run_lands_only_the_chosen_document` 曾失敗一次,原因未查明 |
| 舊 worktree | `.claude/worktrees/ui-live-run-0f7cc8` 的資料庫有實跑 #1–#4,處理前不要清理 |

## 8. 決賽材料還沒做

這些不在 git,放在專案根目錄的 `送件/決賽/`,接手前先讀 `決賽前統整_2026-10-31.md`。

- 投影片仍有已查明不成立的說法,例如「1 筆捏造字號攔截」。
- 問卷結果本機還沒有,附件 3 承諾的「回饋→修正」還沒兌現。
- 新架構定案後,簡報、講稿、擬答要照計畫 W11 改。沒定案前不要動。
