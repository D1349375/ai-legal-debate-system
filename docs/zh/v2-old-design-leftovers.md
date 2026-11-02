# 新流程裡還留著舊設計的地方(計畫沒涵蓋或只涵蓋一半)

> 2026-11-02 由組員整理，給組長決定要不要排進 W3–W8。基於 `v2-flow-fixes`(`pleading-exchange` 的 `dea9736` 加上 P1 修正)。
> 做法：拿規格 `pleading-exchange-spec.md`、計畫 `pleading-exchange-plan.md` 對照程式，針對舊流程的機制(自承檢查、機械彙整、起訴審查補正、UI 文字、續跑)搜尋。**不是逐檔逐行審**:範本、`server/services.py` 全檔、`server/pleading_export.py` 沒有看完，可能還有。
> 已經在 `v2-flow-fixes` 修掉或寫進規格的四項(自承來源、主 agent 上下文、P4–P6 對手資料、`build_prompt`)見 [v2-flow-fixes.md](v2-flow-fixes.md) 第 0 節，這裡不重複。

## 總表

| # | 地方 | 會怎樣 | 計畫 | 建議放在 |
|---|---|---|---|---|
| 1 | 自承檢查的來源沒有起訴狀與答辯狀 | P3 法官寫「被告於答辯狀自認」會被硬擋 | 沒涵蓋(W5 只寫沿用 M12) | W5;**組員已做,分支 `w5-issue-sheet`** |
| 2 | 機械彙整的引用清單差異比 stage 1 與 stage 3 | 新流程的 stage 1 是分析，不列判決，差異數字偏高，畫面照顯示 | 沒涵蓋(計畫寫 `aggregate.py` 不動) | W7 或 W8,要組長決定 |
| 3 | 起訴審查補正看原告 stage 1 | 新流程的補正寫在起訴狀，畫面看錯地方 | 沒涵蓋 | W8 |
| 4 | 攻防分頁、執行說明、補產按鈕都是舊流程文字 | 示範時畫面講的是舊流程 | 一半(W8 只寫時間軸與標模擬) | W8 |
| 5 | 續跑指示寫舊步驟編號 | 新 SKILL 沒有 Step 1.5,續跑時主 agent 照錯的步驟做 | 一半(W3 改 `resume_plan`,沒寫這段文字) | W3 |

第 1、2 項影響最大：第 1 項會讓 W5 實跑反覆退回，第 2 項會讓示範畫面出現錯的數字。

## 1. 自承檢查的來源沒有起訴狀與答辯狀

**現況**:`database/db.py` `admission_sources` 認定「某方說過的話」只有:

| 方 | 來源 |
|---|---|
| 原告 | 事實經過(v2 只算原告的話)、原告 stage 1–3 論證 |
| 被告 | 對方已知反應、被告 stage 1–3 論證 |

沒有 `PleadingDraft` 的起訴狀正文，也沒有答辯狀的 `responses`(逐點表態)與 `legal_argument`。

**問題**:P3 法官依規格 5.5 只讀起訴狀、答辯狀、逐點表態、證據清單。爭點整理很自然會寫「被告對 CF1 不爭執(自認)」「原告起訴狀自陳…」。原句在書狀裡，不在上面的來源裡，`check-judge` 會**硬擋**,法官 subagent 退回 2 次後停住。反過來，法官看不到的分析(stage 1)卻是合法來源。

**另一面**:模擬被告的 `admit` 是模擬的，不是被告本人的自認。法官寫「被告自認」時，畫面與 P6 要標明是模擬答辯的表態。這點規格 5.5 的「不爭執事項只能來自 `admit`」已涵蓋資料來源，但沒涵蓋用語。

**建議**(W5,和 `check-judge` 一起改):
- v2 案件的原告來源加入律師確認版起訴狀正文;被告來源加入答辯狀正文與 `responses` 的 `reason`。
- `admit` 的 CF 要不要算「被告的話」(CF 文字本身是原告寫的):建議算，但只限 `stance = admit` 的那幾點，`deny`、`to_confirm` 不算。
- 測試：法官引起訴狀原句寫「自陳」可過;引 `admit` 的 CF 寫「自認」可過;引 `deny` 的 CF 寫「自認」被擋。

## 2. 引用清單差異在新流程會失真

**現況**:`database/db.py` `finalize_case` 的 `position_drift` 呼叫 `engine/aggregate.py` `disagreement(stage1, stage3)`,用兩個階段引用集合的 Jaccard 距離衡量立場位移。UI(`ui/app.js` 約第 747 行)顯示「Stage 1 引用 N 條 → Stage 3 引用 M 條」,機械彙整也落地進評估。

**問題**:
- 舊流程的 stage 1 是一方的第一份論證;新流程的 stage 1 是 P1、P2 的**分析**,不是書狀。一方真正的起點是起訴狀(律師確認版)與答辯狀。
- `v2-flow-fixes` 為了省成本，讓分析只搜不讀全文，分析範本的 `cited_precedents` 給空陣列(P1 已改,P2 的檢索規則也已寫)。所以 stage 3 引用的每一份判決都會被算成「新增」,位移數字偏高。
- 給法官的 `finalize --for-judge` 不含這項，法官評估不受影響;受影響的是畫面與落地的機械彙整。

**要組長決定**(計畫寫 `aggregate.py` 不動):
- A. v2 案件改比「起訴狀/答辯狀的 `citations`」(在 `PleadingDraft.structured_json`,取律師確認版)與 stage 3。`aggregate.py` 的函數不用改，只改 `finalize_case` 傳進去的起點。
- B. v2 案件不算這項，畫面寫「新流程不適用」。
- 建議 A:改動小，也比較符合「書狀交換」的講法(書狀之後立場有沒有變)。

## 3. 起訴審查補正看原告 stage 1

**現況**:`server/services.py`(約第 526–543 行)用 `cured_in(stage 1 文字, 事項 id)` 判斷原告有沒有補正，畫面寫「原告已在 Stage 1 回應全部補正事項」(`ui/app.js` 約第 645–681 行)。

**問題**:新流程的補正對外是起訴狀的 `procedural_statements`(`engine/pleading_render.py` 有檢查，必須逐項回應)。分析裡的「程序補正(id)」段落仍要求，但它是內部文件，法官 P3 讀不到。畫面依據的是分析，不是法院會看到的起訴狀。

**建議**(W8):v2 案件改看起訴狀的 `procedural_statements`,文字改成「起訴狀已逐項說明」。分析的段落檢查保留。

## 4. UI 仍是舊流程的文字

`ui/app.js` 只有總覽分頁用 `isV2` 分流。下面這些沒有分流，新案件也照舊顯示:

| 位置(約略行號) | 舊文字 | 新流程應是 |
|---|---|---|
| 713 | 協議：起訴審查 → Stage 1 雙方獨立盲判 → 法官依 Stage 1 訊問 → Stage 2 訊問攻防 → Stage 3 辯論終結 | P0 → P1 起訴狀 → P2 模擬答辯 → P3 爭點整理 → P4 準備書狀 → P5 言詞辯論意旨狀 → P6 診斷 |
| 716–719 | Stage 1 爭點整理(雙方獨立盲判，互相看不到對方輸出)/ Stage 2 訊問攻防 / Stage 3 辯論終結 | 原告分析、被告防禦分析(被告只讀起訴狀)/ 準備書狀 / 言詞辯論意旨狀 |
| 632 | 訊問 — 基於雙方 Stage 1 | 依爭點整理表的闡明與訊問 |
| 747、772 | Stage 1 引用 → Stage 3 引用 | 見第 2 項 |
| 1605 | 執行說明：起訴審查 → Stage 1 → 法官訊問 → Stage 2 → Stage 3 → … → 你選的書狀骨架 | 新流程步驟;書狀由程式組成，不是選書狀骨架 |
| 1639 起 | 只補產書狀(Step 9C)按鈕 | 新案件的書狀由程式組成，這個按鈕不該出現 |

計畫 W8 寫「新增書狀時間軸，P2–P5 標模擬並預設收合」,沒寫上面這些要依 `protocol` 分流。示範會開攻防分頁時，畫面說的「互相看不到對方輸出」「依 Stage 1 訊問」和新架構的講法衝突，評審問到會很難回答。

## 5. 續跑指示寫舊步驟編號

**現況**:`server/live_run.py` `build_prompt` 的續跑段落(約第 142 行)寫「之前的步驟只做 Step 1 的檢索詞整理與 Step 1.5 的 `python main.py issues`」。這是舊流程(`stance_rag` 檢索詞、Step 1.5 程序事項)。新 `SKILL.md` 沒有 Step 1.5,也不再整理立場檢索詞。

**建議**(W3):`resume_plan` 依 `protocol` 分流時，這段文字一起分流;v2 續跑只需要重新產生角色檔(`role-view`)。

## 確認過沒有問題的

| 項目 | 結果 |
|---|---|
| 評估結論 `verdict_main_text` | 範本已寫成爭點強弱結論，不是判決主文，和「不給勝訴機率」一致 |
| 起訴狀的程序補正 | 有 `procedural_statements` 且逐項檢查(第 3 項只是畫面看錯地方) |
| 匯出 | `Case` 的新欄位會自動匯出;`IssueSheet` 要加進 `server/seed.py` `_TABLES`,計畫已寫 |
| `record` 的 stage 2、3 規則 | 只要求 falsifier,沒有綁「回應法官訊問」,新流程可以沿用 |

## 誰改

| # | 檔案 | 建議 |
|---|---|---|
| 1 | `database/db.py`、`main.py check-judge` | 組員可以先寫(和 W5 的 `issue-sheet` 一起),組長接範本 |
| 2 | `database/db.py` `finalize_case` | 組長決定 A 或 B 後，組員可以做 |
| 3、4 | `server/services.py`、`ui/app.js` | 組長(W8) |
| 5 | `server/live_run.py` | 組長(W3) |
