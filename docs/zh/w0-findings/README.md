# W0 實跑發現:調研與修正計畫

> 2026-11-02 整理。依據是 W0 實跑紀錄 [`docs/live-run-records/w0-2026-11-02.md`](../../live-run-records/w0-2026-11-02.md)、該次原始輸出(worktree 內不進 git 的 `database/live_runs/run-1/`),以及 `main-finals-fixes`(`cf6f98c`)與 `pleading-exchange`(`e1b5436`)兩條分支的程式碼。
> 分工:程式、架構與 UI 的修改交給 Codex;需要用 Claude 實跑的檢查由 Claude 跑;每一項實作完由 Claude 檢核。

## 0. 怎麼用這份文件

| 讀者 | 先看 |
|---|---|
| 使用者 | 第 1 節結論、第 4 節要決定的事、[`codex-prompts.md`](codex-prompts.md) |
| Codex | 第 5 節共同規則、自己那一項的任務文件(`T*.md`) |
| Claude(檢核) | 第 6 節檢核流程、各任務文件的「檢核方式」 |

## 1. 結論

W0 依手冊判準通過(全部落地、V35 不成立 0、分類器中止 0)。但這次跑出 9 項問題,其中 **F2(主 agent 改了機械彙整)是誠實性問題**,F1、F7 會讓實跑白跑或少跑一步,其餘是檢查規則的缺口。

- 9 項中 7 項兩條分支都有,修在 `main-finals-fixes`(退路),再合併進 `pleading-exchange`(新架構主線)。`pleading-exchange` 是從 `cf6f98c` 開出來的,相關檔案在新分支只有 `main.py`、`server/` 有改動,合併衝突可控。
- F6(條文內容轉述錯誤)與 F8(最強論點選句)只修在 `pleading-exchange`:F6 要用新分支才有的 `python main.py article`;F8 的對手摘要在 W6 仍沿用,一起改。
- 這些都不是 W2 的前置條件。T1–T6 都是小改,建議 11/2 內完成,不影響 11/3 晚的停損點。

## 2. 發現逐項調研

### F1 指定資料庫時,即時執行的子程序寫到別的資料庫

- **現象**:第 1 次實跑設了 `LEGALDEBATE_DB_URL`,子程序全寫進 worktree 預設的 `database/legal_debate.db`。伺服器那顆暫存資料庫看不到案件與商工查核,法官評估寫「雙方的商工查核都尚未進行」,UI 判為不完整。白花 14 分 31 秒、3.44 美元、5 小時額度 30%。
- **根因**(兩條分支相同):
  - `database/db.py` `make_session_factory(db_url)` 在 `db_url` 為 `None` 時會讀環境變數,所以**伺服器自己**用的是暫存資料庫。
  - `main.py` `cmd_serve` 呼叫 `create_app()` 沒傳 `db_url`,`LiveRunManager.db_url` 是 `None`。
  - `server/live_run.py` 啟動子程序時 `env[DB_URL_ENV] = self.db_url or f"sqlite:///{default_db_path()}"`(`main-finals-fixes` 第 703 行、`pleading-exchange` 第 711 行),把繼承來的環境變數**覆寫成預設路徑**。
  - 附帶:`/api/health` 的 `database.path` 以 `db_url is None` 判斷,設了環境變數仍顯示 `database/legal_debate.db`,畫面看不出用錯。
- **影響**:之後每次「用暫存資料庫實跑」都會重演。測試沒抓到,因為測試都直接傳 `db_url`。
- **處理**:T1。在 `create_app` 開頭把 `db_url` 解析成「參數 → 環境變數 → 預設」,同一個值給 session factory、`LiveRunManager` 與 health。

### F2 主 agent 改寫了機械彙整再落地

- **現象**:落地的 `mechanical_anchor_json` 裡,`weak_points[].response_excerpt` 被換成「(同 database 內被告 Stage 3 公開論證前段,摘錄從略…)」,`procedural_issues` 也少了 `warning`、`question_text`、`procedure` 欄位。主 agent 在最後回報自己寫明了這件事。SKILL 第 17 行禁止修改機械彙整結果。
- **根因**:
  - 設計上,機械彙整由 `python main.py finalize` 算出,**再由主 agent 抄進 verdict JSON**,`main.py verdict` 原樣存入(`cmd_verdict` 直接取 `payload["mechanical_anchor_json"]`)。程式完全信任模型轉抄。
  - `engine/aggregate.py` `compile_weak_points` 的 `response_excerpt` 是**雙方 Stage 3 的完整 `reasoning`**(含內部檢討段落)。兩方全文加起來很長,主 agent 為了縮短 JSON 而摘略,這是可預期的行為,不只是偶發。
  - UI 的 `server/services.py` `_anchor_check` 只比對 `position_drift` 與 `falsifier`,不比 `response_excerpt` 與 `procedural_issues`,所以畫面仍顯示「一致」。
- **影響**:畫面上標「機械彙整、非 AI 生成」的資料其實被模型改過。對外說「機械彙整不經模型」不成立。這是本次最需要修的一項。
- **處理**:T2。`main.py verdict` 落地時自己呼叫 `finalize_case` 重算並存入,不再讀模型給的版本;模型若仍附上且與重算不同,印警告。`_anchor_check` 改成比對全部欄位。SKILL 與 verdict 說明把 `mechanical_anchor_json` 從模型輸出移除。

### F3 自承檢查放行「資料缺口」標記

- **現象**:訊問 3 寫「你方 Stage 1 自陳這一點「證據不明,需查證」」。原句在原告 Stage 1 確實存在,所以轉述正確;但這是原告自己標的資料缺口,依 M12 的設計不能稱「自陳」。`check-judge` 放行。
- **根因**:`engine/admission_check.py` 的 `_SOFT_RE` 判斷「原句是假設、自我評估或資料缺口」。原句所在句子是「…尚待證明,標示為「證據不明,需查證」。」,`_SOFT_RE` 有 `待查` 但沒有 `待證`、`證據不明`、`需查證`。
- **附帶發現**:`templates/verdict_prompt.txt` 第 13 行禁止把假設或資料未載寫成「承認」,但 `ADMISSION_RE` 只認 `自承|自認|自陳|坦承`,沒有 `承認`。本次原告論證有「原告承認有疑義」(論證是一方自己說的,不在法官檢查範圍),法官輸出若寫「原告承認…」目前檢查不到。
- **影響**:法官對資料缺口用承認類字眼,會被讀成一方承認。這次的句子意思沒錯,但規則的目的是讓字眼本身不出現。
- **風險**:`_SOFT_RE` 是比對**整句原文**,詞加太廣(例如單字「不明」)會讓真正的事實陳述也被當成資料缺口,法官被退回、重派要多花錢。要先拿現有紀錄量測誤擋。
- **處理**:T3。補詞並以現有所有紀錄量測新增誤擋;`承認` 是否納入看量測結果。

### F4 一方把對造的條件句稱為「自承」(V35 邊界 2)

- **現象**:原告 Stage 3 寫被告「自承「被告若主張更早知悉,則由被告就更早知悉負反證責任。」」。原句是被告對舉證責任的法律見解,原告只拿來說明舉證責任。`record` 已因原句是條件句發出警告。
- **根因**:雙方論證的自承檢查只警告(手冊規則:自然語言只警告),主 agent 沒有據此退回。
- **處理**:**不另開任務**,維持只警告。理由:這是一方的攻防用語,法官評估另有硬擋;退回會增加成本與分類器風險。見第 4 節 D2。

### F5 內部檢討寫在段落外,`record` 沒警告(V46)

- **現象**:6 份論證都有成對的 `【內部檢討】` 段落,法官也沒用到段落內的內容。但段落外仍有自我評估:
  - 被告 Stage 3:「…A1 的力道會減弱,此為內部風險,不是承認。」
  - 原告 Stage 2:「…原告承認有疑義,故此一路徑列為最弱備位。」
  - 原告 Stage 3 類似句。
- **根因**:`engine/internal_review.py` 的 `_SELF_REVIEW_RE` 只有 `弱點|最大風險|最大缺口|對我方不利|對本方不利|我方不利|本方不利|基礎薄弱|自我檢討`,上面三句的「內部風險」「力道會減弱」「承認有疑義」「最弱」都不在。
- **判斷**:
  - 「列為最弱備位」本身是正當的訴訟策略(先位、備位),**不全是自我檢討**;「此為內部風險」則明顯是該寫進段落的內容。關鍵字加太廣會讓警告失去意義。
  - 這些句子法官讀得到。本次法官沒有據此判一方不利,但沒有機制保證。
- **處理**:T4。補詞並量測誤報;警告數寫進執行紀錄讓 UI 看得到。是否要主 agent 收到警告就退回重寫,見第 4 節 D3(建議決賽前不做)。

### F6 法官照一方說法轉述了錯誤的條文內容

- **現象**:訊問 2 寫「公司法第23條第3項(公司對負責人訴訟之代表人)」。該項實為歸入權規定。這是被告 Stage 1 的說法,法官照抄;原告在 Stage 2 指出,評估也記下這點。
- **根因**:
  - Step 8 的 `verify` 只確認條文**存在**。`公司法第23條第3項` 存在,所以 `published`。
  - SKILL Step 8 的實質核對只要求讀**判例**全文,沒有要求核對**條文內容**與引用處的描述是否相符。
  - 法官訊問在 Step 3 就落地,本來就不經 Step 8 閘門。
- **影響**:書狀與評估若寫「某條(某內容)」而內容不符,現在不會被擋。這次是在訊問,被原告糾正,反而顯示了對抗的效果;但若出現在書狀就是錯誤。
- **處理**:T8(只在 `pleading-exchange`)。Step 8 對「引用處附有內容描述」的條文,由查證 subagent 用 `python main.py article <法規> <條號>` 讀條文核對,不符視同實質核對失敗。`verify.py` 與檢索指令是組員的,不改;只改 SKILL。要用 Claude 實跑驗證(C2)。
- **正確條號不在本文件判定**:公司對董事訴訟的代表人規定,要查證後由律師或組員確認,不要直接寫進範本當例子。

### F7 Windows 上 CLI 先用 PowerShell 工具,被拒後查證 subagent 沒跑 `verify`

- **現象**:`stream.jsonl` 有 26 處 PowerShell,其中查證 subagent 用 PowerShell 跑 `python main.py verify …` 與 `foreach (…)` 迴圈,被拒 2 次。第一個查證 subagent 因此沒跑 `verify`,主 agent 另派一個改用 Bash 才完成。
- **根因**:Claude Code 在 Windows 提供 `PowerShell` 工具。`server/live_run.py` 的 `ALLOWED_TOOLS` 只開 `Bash(python main.py *)`,`--permission-mode dontAsk` 下 PowerShell 一律被拒,但模型**看得到這個工具**,所以會先試。
- **影響**:多一次 subagent 重派(時間、花費);若重派也失敗,Step 8 可能沒跑完就被當成完成。
- **處理**:T5。`DISALLOWED_TOOLS` 加入 `PowerShell`,讓模型看不到;`build_prompt` 的指令說明寫明用 Bash 工具。`DISALLOWED_TOOLS` 原有規則保留(手冊第 5 節)。`--disallowedTools PowerShell` 是否真的把工具移出清單,要用 Claude 實測(C1 會順便看)。

### F8 對手摘要的「最強論點」選到讓步句

- **現象**:被告 Stage 2 被選為「最強論點」的是「被告若主張更早知悉,則由被告就更早知悉負反證責任。」,這是舉證責任的讓步句,不是被告最強的論點。原告隨後把它寫成「自承」(F4)。
- **根因**:SKILL Step 4 只規定最強論點要**逐字**摘一句(M14),沒規定怎麼選。摘要檔由主 agent 自己寫,沒有落地指令,程式沒有檢查點。
- **影響**:對手拿到的是對方最弱的一句,攻防會偏向打稻草人;也直接造成 F4。
- **處理**:T9(只在 `pleading-exchange`,與 W6 一起)。SKILL 規定選句標準(要是該方主張句,不選條件句、讓步句、舉證責任分配句);新增 `python main.py check-summary` 檢查摘要是否逐字、是否含 `_SOFT_RE` 字詞,只警告。要用 Claude 實跑驗證(在 W6 的實跑一起看)。

### F9 V39 沒跑:匯出會寫進 git 的 fixture,資料庫還有作廢那次的殘留

- **現象**:`export-demo` 一定寫到 `demo/recorded_cases.json`(進 git),而且 `server/seed.py` `export_fixture` 匯出**整顆資料庫**。worktree 資料庫裡有第 1 次(作廢)的論證、訊問、評估與書狀,這些列沒有對應的案件列,會一起被匯出。
- **附帶**:`demo/recorded_live_checks.json` 的 `checks` 在 `main-finals-fixes` 是 0 筆(`main` 是 2 筆),斷網示範「查無字號」可能沒有錄製結果,影響還沒實測。
- **處理**:T6。`export-demo` 加 `--out`(寫到指定位置)與孤兒列檢查(沒有案件列的紀錄不匯出並列出);用資料庫複本與乾淨 clone 做斷網重播,把 V39 補完。要不要把 W0 案件放進正式 `demo/`,等 11/4 版本定案(第 4 節 D4)。

### 其他觀察(不開任務)

| 觀察 | 說明 |
|---|---|
| CLI 帳號與桌面 app 不同 | UI 顯示的額度來自 `stream-json` 的 `rate_limit_event`,也就是 **CLI 登入的帳號**。看額度要看 CLI 那個,現場演示前要確認登入的是哪個帳號 |
| 內建瀏覽器會自動取消 `window.confirm` | 只是測試環境的操作,產品不受影響 |
| `test_pleading_run_lands_only_the_chosen_document` 偶發失敗 | 不是 W0 發現,已列在手冊陷阱;T1–T6 跑全套測試時若再遇到,記下實際狀態碼 |

## 3. 任務與順序

| 順序 | 任務 | 對應 | 分支 | 誰做 | 要 Claude 實跑 |
|---|---|---|---|---|---|
| 1 | [T1 資料庫設定傳給子程序](T1-db-url.md) | F1 | `main-finals-fixes` | Codex | 否(C1 一起驗) |
| 2 | [T2 機械彙整改由程式落地](T2-mechanical-anchor.md) | F2 | `main-finals-fixes` | Codex | 是(C1) |
| 3 | [T3 自承檢查補資料缺口詞](T3-admission-soft-terms.md) | F3 | `main-finals-fixes` | Codex | 是(C1 看有無誤擋) |
| 4 | [T4 段落外自我檢討警告](T4-self-review-warnings.md) | F5 | `main-finals-fixes` | Codex | 是(C1) |
| 5 | [T5 停用 PowerShell 工具](T5-windows-tools.md) | F7 | `main-finals-fixes` | Codex | 是(C1) |
| 6 | [T6 匯出與斷網重播(V39)](T6-export-replay.md) | F9 | `main-finals-fixes` | Codex | 否 |
| 7 | [C1 修正後重跑 W0 案件](C1-rerun.md) | T1–T5 | `main-finals-fixes` | Claude | 是,約 12 分鐘 |
| 8 | [T7 合併進 pleading-exchange](T7-merge.md) | — | `pleading-exchange` | Codex | 否 |
| 9 | [T8 條文內容核對](T8-statute-content-check.md) | F6 | `pleading-exchange` | Codex | 是(C2,搭下一次跑到 Step 8 的實跑) |
| 10 | [T9 最強論點選句](T9-strongest-point.md) | F8 | `pleading-exchange` | Codex | 是(W6 的實跑) |

- T1–T6 互不依賴,但都改 `main.py` 或 `server/`,**照順序一次做一項**,每項檢核通過、commit 之後才開下一項,避免兩項改動混在同一個工作目錄分不開。
- W2 不必等 T8、T9。T7 合併完成後 W2 就能在 `pleading-exchange` 繼續。
- C1 要用掉 5 小時額度約 25%,開跑前先確認額度。

## 4. 要使用者決定的事

| # | 事項 | 建議 |
|---|---|---|
| D1 | 修在哪條分支 | 共通的修在 `main-finals-fixes` 再合併進 `pleading-exchange`;F6、F8 只修新分支(第 1 節) |
| D2 | 雙方論證把條件句稱「自承」要不要退回 | 維持只警告,不退回(F4) |
| D3 | 段落外自我檢討要不要退回重寫 | 決賽前只加警告並在 UI 顯示次數,不退回(F5) |
| D4 | W0 案件要不要匯出進正式 `demo/` | 11/4 晚版本定案後再決定;T6 只匯出到暫存位置驗證 |
| D5 | 每項 commit 由誰做 | Claude 檢核通過、使用者同意後,由 Codex commit(prompt 已寫好) |

## 5. Codex 共同規則

每一項任務都適用。任務文件寫得更嚴的,以任務文件為準。

1. **回覆與文件一律用繁體中文。**
2. **先讀**:本文件、自己那一項的任務文件、[`../main-finals-fix-list.md`](../main-finals-fix-list.md) 的相關段落。在 `pleading-exchange` 上做的任務另讀 `docs/zh/pleading-exchange-handoff.md` 第 5 節。
3. **只在任務指定的分支與工作目錄做。** 不切分支、不 push、不併 `main`。不要併 `retrieval-optimization` 或 `role-separation-redesign`。
4. **不 commit**,做完回報。使用者把結果交給 Claude 檢核,通過後使用者才會叫你 commit。commit 訊息用英文、祈使句。
5. **先寫測試再實作。** 開工前先跑一次離線全套測試記下基準數字,做完再跑一次。
6. **不能改的東西**:`database/legal_debate.db` 與 `database/live_runs/` 的內容(只能讀或複製到暫存位置);`server/live_run.py` 的 `SNAPSHOT_ENV` 與 `DISALLOWED_TOOLS` 既有規則;組員維護的檢索模組與 `engine/verify.py` 的查證部分(`pleading-exchange` 的 `docs/zh/retrieval-interface.md` 第二節)。
7. **公開 repo**:不 commit 資料庫、本機絕對路徑、語料全文、個資。量測用的腳本與輸出放暫存資料夾,不進 git。
8. **輸出欄位命名**:不用 `reasoning`、`thinking`、`trace`、`analysis`、`internal`、`scratch`(分類器風險,見規格第 8 節)。
9. **檢查規則**:結構可以硬擋,自然語言只警告。同一份輸出最多退回 2 次。
10. **不准做的事**:不手改模型產出的 JSON 後說是模型產出;不為了讓測試通過而改測試的預期,除非任務文件說要改;沒驗證的就寫沒驗證。
11. **不用中國機構開發的模型、API 或 MCP。**

### 實作紀錄怎麼寫

每份任務文件最後有「實作紀錄(Codex 填寫)」。**邊做邊寫,不要做完才補。** 要寫:

- 開始與結束時間、基準 commit。
- 基準測試結果(指令與 passed/failed/skipped 數字)。
- **迭代過程**:每一次嘗試寫一列,「做了什麼 → 看到什麼 → 決定怎麼改」。失敗的嘗試也要寫,包括測試失敗的訊息摘要、改錯又改回來的地方。
- 最後的測試結果數字;新增了哪些測試、各測什麼。
- 改了哪些檔(每檔一句說明)。
- 與任務文件不同的做法和原因。
- 沒解決或沒驗證的事。

另在 `docs/zh/main-finals-fix-list.md` 文末「W0 後修正」段落加一列(第一個做的任務負責建立這個段落):任務、commit(先寫「未 commit」)、測試數字、一句話結果。

## 6. 檢核流程(Claude)

每項任務 Codex 回報後:

1. 讀任務文件的實作紀錄,核對它說的和 `git diff` 一致。
2. 自己跑離線全套測試,數字要和紀錄一致;跑任務文件列的指定測試。
3. 逐條對照任務文件的「完成定義」與「檢核方式」。
4. 檢查共同規則:沒有本機路徑、沒有改到不該改的檔、沒有違規欄位名、沒有改測試預期來過關。
5. 結果寫在任務文件的「檢核結果(Claude 填寫)」:通過,或列出要改的地方。不通過就把清單交回 Codex。
6. 要 Claude 實跑的項目,在 C1、C2 一起跑,結果寫進該文件與 `docs/live-run-records/`。
