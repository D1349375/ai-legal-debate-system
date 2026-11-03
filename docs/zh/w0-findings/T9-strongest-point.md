# T9 對手摘要的最強論點選句(F8)

- **分支 / 工作目錄**:`pleading-exchange` / `.claude/worktrees/pleading-exchange`
- **做的人**:Codex;Claude 在 W6 的實跑驗證。前提:T7 已完成。**建議和 W6 一起做**(W6 仍用對手摘要,見 `pleading-exchange-plan.md` 約第 207 行)。
- **調研**:[README 第 2 節 F8](README.md#f8-對手摘要的最強論點選到讓步句)

## 問題

W0 被告 Stage 2 被選為「最強論點」的是「被告若主張更早知悉,則由被告就更早知悉負反證責任。」,這是舉證責任的讓步句。原告隨後把它寫成被告「自承」(F4)。SKILL Step 4 只要求逐字摘一句(M14),沒規定怎麼選;摘要檔由主 agent 自己寫,沒有落地指令,程式沒有檢查點。

## 要做的

1. **SKILL Step 4、Step 5 加選句標準**:最強論點要選該方**正面主張**的句子(主張某要件成立或不成立、某法律效果),**不選**:條件句(若、倘、如果、縱使)、讓步句、舉證責任分配的說明、程序性說明、引用清單。找不到符合的句子時,選 `position` 最接近的一句,並在摘要標「無明確主張句」,不要改寫。
2. **新增 `python main.py check-summary --case-id <id> --json <摘要檔>`**(只警告,不擋):
   - 摘要檔格式照 SKILL 現在主 agent 寫的(W0 的 `opp_s1_for_defendant.json` 等;Codex 先讀 `database/live_runs/run-1/` 裡的實例,**只讀,不要複製進 git**)。若格式不固定,先在 SKILL 規定一個最小格式(`side`、`position`、`strongest_point`、`cited_statutes`、`cited_precedents`),欄位名照共同規則第 8 點避開禁用字。
   - 檢查:`strongest_point` 是否逐字出現在該方 `public-args` 的論證(用 `admission_check` 的 `_norm` 同樣方式比對);是否含 `_SOFT_RE` 的字詞或條件句開頭。
   - 結果印到 stderr,exit code 0;主 agent 依 SKILL 把警告列入 Step 10。是否改成退回重選,等 W6 實跑結果再決定。
   - 放在我們維護的檔,不要改組員的模組。
3. SKILL 規定主 agent 寫完摘要後執行 `check-summary`。

## 測試(先寫)

- W0 那句(條件句、讓步)會警告。
- 逐字出現的正面主張句不警告。
- 不是逐字(改寫過)的會警告。

## 完成定義

- 測試全過;離線全套通過數 = 基準 + 新增數。
- SKILL diff 只動 Step 4、Step 5 與 Step 10 的列項。

## 檢核方式(Claude)

- 讀 diff 與測試。
- W6 實跑時看:主 agent 有沒有跑 `check-summary`、警告數、選到的句子是不是正面主張。結果寫進該次實跑紀錄。

## 實作紀錄(Codex 填寫)

- 開始時間:
- 結束時間:
- 基準 commit:
- 基準測試(指令與數字):

### 迭代過程

| # | 做了什麼 | 看到什麼 | 決定 |
|---|---|---|---|
| 1 | | | |

### 摘要檔格式(實例觀察與決定)

### 結果

- 最後測試(指令與數字):
- 新增測試與各自測什麼:
- 改了的檔:
- 與本文件不同的做法與原因:
- 沒解決或沒驗證的事:

## 檢核結果(Claude 填寫)

- 日期:
- 結果:
- W6 實跑結果:
- 要改的地方:
