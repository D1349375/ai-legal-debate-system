# T9 對手摘要的最強論點選句:`check-summary`

> 分支 `t9-check-summary`,基於 `pleading-exchange` 的 `ebe640a`(分支 `w6-brief` 的 HEAD)。2026-11-02 由組員以 Claude Code 實作純程式部分。
> 任務文件是 `main-finals-fixes` 的 `docs/zh/w0-findings/T9-strongest-point.md`。這份是那份任務的實作紀錄;**SKILL 的接線沒做**(組長的檔),建議文字在第 3 節。

## 1. 做了什麼

`python main.py check-summary --case-id <id> --json <摘要檔>`:檢查主 agent 寫給對手的摘要檔。**只警告**:警告逐行印到 stderr(`警告:…`),stdout 印 `摘要檢查:N 則警告`,結束碼 0。摘要檔讀不到、不是 JSON、格式錯誤或案件不存在時,印原因,結束碼 2。

新檔 `engine/summary_check.py`(純函數,不碰資料庫、不呼叫 LLM)、`main.py` 的 `cmd_check_summary`(加在 `main()` 前,子指令註冊加在最後一個子指令之後,用法說明加在用法清單最後),測試 `tests/test_check_summary.py`。沒有改組員或組長的既有模組,`admission_check.py` 只 import `_norm` 與 `_SOFT_RE`。

四項檢查:

| # | 檢查 | 警告條件 | 備註 |
|---|---|---|---|
| 1 | 最強論點是原句 | `strongest_point` 沒有逐字出現在該方該 stage 的公開論證(`public_arguments` 的 `position` 或 `argument`,已濾掉內部檢討) | 比對前先 NFKC(全形轉半形),再用 `_norm` 去空白與標點。內部檢討那段的句子選了,會警告不是原句 |
| 2 | 不是正面主張句 | 含 `_SOFT_RE` 的字詞(若、倘、如果、假設、縱使、除非、弱點、風險、不利、薄弱、待確認、待查、未載、資料未、尚未確認、未見);或補的連詞(即使、縱然、縱令、倘若、設若、假若、假使、如謂、若謂);或舉證責任分配(負舉證／反證／證明責任、舉證之責、舉證責任分配、「由…舉證／反證」) | 訊息分開列出「條件或讓步字樣」與「舉證責任分配」各抓到哪些字。**只靠字樣,見第 6 節** |
| 3 | v2 只取 stage 2 | 案件 `protocol == "v2"` 且摘要 `stage != 2`(規格 5.6) | 舊流程(protocol 為空)可以摘 stage 1、2,不警告 |
| 4 | 引用在清單內 | `cited_statutes`、`cited_precedents` 有項目不在該方該 stage 論證的引用清單(去空白與標點後比對,整串相等) | 摘要把「民法第184條第1項前段」縮成「民法第184條」也會警告。要的是照抄 |

另外:資料庫沒有該方該 stage 的公開論證時,警告一則並跳過檢查 1、4(沒東西可比);摘要標了 `no_clear_claim` 時跳過檢查 2,但警告「標了無明確主張句」,讓這件事進 Step 10。

## 2. 摘要檔格式的決定

W0 的摘要檔(`opp_s1_for_defendant.json` 等)在 `database/live_runs/`,依規定不讀、不複製,所以**沒有觀察 W0 實例的欄位**,格式照任務指示訂最小格式:

```json
{"side": "defendant", "stage": 2,
 "position": "…", "strongest_point": "…",
 "cited_statutes": ["…"], "cited_precedents": ["…"],
 "no_clear_claim": false}
```

- `side`:被摘要的那一方(不是讀摘要的那一方)。`plaintiff` 或 `defendant`。
- `stage`:被摘要的是哪一階段。1、2、3 的整數。
- `position`、`strongest_point`:非空字串。`strongest_point` 是一句,逐字從該方 `argument` 摘出。
- `cited_statutes`、`cited_precedents`:字串清單,可省略(當空清單)。
- `no_clear_claim`:**我加的選填欄位**,布林,預設 false。任務文件說「找不到符合的句子時,選最接近 position 的一句,並在摘要標『無明確主張句』」,摘要檔要有地方標。欄位名避開禁用字。
- 其他欄位忽略,不報錯(現有範本讀摘要檔的欄位組長可以再加)。
- `position` 沒有和資料庫比對(摘要可能刻意濃縮立場),只檢查是非空字串。

**與現行 SKILL/範本的關係(要組長確認)**:`stage2_prompt.txt`、`stage3_prompt.txt` 只說「結構化摘要(立場+最強論點+引用)」,路徑佔位符是 `{OPPONENT_STAGE2_SUMMARY_PATH}` 之類,沒有規定檔案欄位。這個格式要靠 SKILL 規定主 agent 照寫,範本讀的人(subagent)讀 JSON 沒有問題,但範本和 `check-summary` 的欄位名要一致由組長接線時對。

## 3. 給 SKILL 的建議文字(沒有改)

現在的 Step 4、Step 5、Step 10 在 `.claude/skills/legal-debate/references/legacy-v1.md`(`SKILL.md` 的 Step 4 以後指向它);v2 的 P5 對手摘要等 W6 接線時才有自己的步驟。以下依 `legacy-v1.md` 的位置寫,P5 步驟照用。

**Step 4(Stage 2 雙方應訊)**:在「最強論點要從對造 `argument` 逐字摘一句原文」之後加:

> 最強論點選該方**正面主張句**(主張某要件成立或不成立、某法律效果)。**不選**:條件句(若、倘、如果、縱使、即使開頭)、讓步句、舉證責任分配的說明(「負舉證責任」「負反證責任」「舉證之責」)、程序性說明、引用清單。找不到符合的句子時,選 `position` 最接近的一句,摘要檔寫 `"no_clear_claim": true`,不要改寫。原句本身帶的限定語(「若」「資料未載」「待確認」)照舊要留著,所以正面主張句裡有這類字時,`check-summary` 會警告,列入 Step 10 即可。
> 摘要檔寫成 JSON,欄位:`side`(被摘要的那一方)、`stage`、`position`、`strongest_point`、`cited_statutes`、`cited_precedents`,需要時加 `no_clear_claim`。
> 寫完摘要檔、交給角色之前,執行 `python main.py check-summary --case-id <case_id> --json <摘要檔>`。只警告,不擋;但警告中有「不是原句」或「不在引用清單」時,重新依 `public-args` 的輸出重摘一次(同一份摘要最多重摘 2 次,同共同規則第 6 點),其餘警告列入 Step 10。

**Step 5(Stage 3)**:「同 Step 4 的萃取方式」後加「(選句標準與 `check-summary` 同 Step 4)」。

**Step 10**:列項加一行:「`check-summary` 的警告(每份摘要幾則、內容原文);標了無明確主張句的摘要。」

**P5(v2)**:對手摘要只摘對造 stage 2;`check-summary` 在 v2 案件摘 stage 1 或 3 會警告(規格 5.6)。

「不通過就重摘」那句是我加的建議,任務文件寫「是否改成退回重選,等 W6 實跑結果再決定」,所以那句可以先不放,只列入 Step 10。**組長決定。**

## 4. 迭代過程

| # | 做了什麼 | 看到什麼 | 決定 |
|---|---|---|---|
| 1 | 讀任務文件、協作規則、規格 5.6、`admission_check.py`、`public_arguments`、`cmd_public_args`、`cmd_statute_claims`。基準測試 | 604 passed、2 skipped、13 deselected(3 分 48 秒)。目前 `SKILL.md` 的 Step 4 已搬到 `references/legacy-v1.md` | 建議文字寫成指向 `legacy-v1.md` |
| 2 | 先寫 46 個測試(`tests/test_check_summary.py`),跑一次 | 紅燈:`ModuleNotFoundError: engine.summary_check`(收集階段就失敗) | 開始實作 |
| 3 | 寫 `engine/summary_check.py` 與 `cmd_check_summary`,用腳本在 `main.py` 三處插入 | 2 個測試失敗:W0 那句的警告裡沒有「負反證責任」 | 看輸出找原因 |
| 4 | 把舉證責任的正規式從 `負…責` 改成 `負…責任?` | 仍失敗 | 看到比對結果是「由被告就更早知悉負反證」:「由…反證」那個選項在句中更前面,先被匹配,吃掉了「負反證責任」 |
| 5 | 舉證責任改成各選項分開的正規式,依序掃描,位置重疊的不重複列;訊息分成「條件或讓步字樣」「舉證責任分配」 | 46 passed。W0 句的訊息:「條件或讓步字樣:若;舉證責任分配:負反證責任」 | 採用 |
| 6 | 離線全套 | 650 passed、2 skipped、13 deselected(3 分 52 秒) | 通過數 = 基準 604 + 新增 46 |

我自己寫測試時有一行斷言寫得繞(用 `if False` 的三元式),執行前就發現,改成直接檢查 `「引用」` 有沒有出現在訊息裡,沒有送進 commit。

## 5. 測試

| 類別 | 測什麼 |
|---|---|
| `TestStrongestPoint` | W0 那句會警告,且分別指出「若」與「負反證責任」,不誤報不是原句;逐字出現的正面主張句不警告;全形標點與空白不影響逐字比對;句子只在 `position` 也算原句;8 種條件、讓步、舉證責任句式(倘、即使、縱使、如果、負舉證責任、負反證責任、舉證之責、風險)都警告;內部檢討的句子選了會警告不是原句;改寫過的警告;標 `no_clear_claim` 時不報字樣但仍列出提醒、改寫仍警告 |
| `TestProtocol` | v2 案件摘 stage 1、3 警告;摘 stage 2 不警告;舊流程摘 stage 1 不警告 |
| `TestCitations` | 法條、判例不在清單警告,清單內的不警告;別的 stage、別方的清單不算;該方該 stage 沒有公開論證時只警告一則 |
| `TestValidate` | 13 種格式錯誤(非物件、缺欄位、side/stage 錯、型別錯、空字串、布林當 stage)都拒絕;選填欄位省略時補預設 |
| `TestCli` | 乾淨摘要:結束碼 0、stderr 無警告;W0 句:結束碼 0、stderr 有警告;v2 案件摘 stage 1:0 並警告;資料庫內部檢討句不可選(CLI 走 `public_arguments`);壞 JSON、side 錯、最外層是陣列:結束碼 2 且印原因;檔案不存在、案件不存在:2 |

## 6. 沒驗證與限制

- **沒有用 W0 真實摘要檔跑過**(依規定沒讀 `database/live_runs/`)。W0 那一句是任務文件裡的原文,測試用它;實際摘要檔的欄位名可能和這份格式不同,W6 實跑時才知道。
- **字樣檢查會誤判兩個方向**。漏報:不含上述字樣的讓步句(例如「縱認」「姑不論」「退步言」,這幾個沒加進去)、程序說明句、引用清單句都檢查不到。誤報:正面主張句裡有「若」「不利」「未見」(例如「被告未見提出收據」)會警告;`_SOFT_RE` 是自承檢查的詞表,為了不分叉直接沿用,沒有為了降低誤報去改。
- **沒檢查是不是「一句」**。`strongest_point` 若是整段逐字貼上,檢查 1 會通過。要檢查可以加「句號數」,但引號內的句號會誤判,沒做。
- **沒檢查是不是「最強」**。這個程式只能擋 W0 那一類的選錯句,選的句子是不是該方最強的正面主張,要靠人看。
- **沒檢查 `side` 是不是「對造」**:摘要是給哪一方讀的,檔案裡沒有,程式不知道。
- 引用比對是整串相等(去空白與標點),沒有做簡稱或「第N條」與「第N條第1項」的模糊比對。
- 沒有在瀏覽器或實跑環境驗證,也沒有跑 `-m network` 的測試。
- 沒有 push。分支只在本機,commit 後等組長檢核。

## 7. 要組長確認

1. 摘要檔欄位名與範本佔位符的接法(第 2 節),以及 `no_clear_claim` 這個我加的欄位。
2. 警告是否改成退回重摘:建議文字裡「不是原句、不在引用清單」建議重摘,字樣警告只列 Step 10,這是我的判斷,任務文件說等 W6 實跑決定。
3. SKILL 與 v2 P5 步驟的接線(第 3 節)。

## 合併前(組員)

- 這項由組員開的 subagent 從 `ebe640a` 實作,組員檢核 diff 後 rebase 到 `w7-revision` 之上(`main.py` 兩處和 W7 的新增相鄰,兩邊都保留),重跑離線全套 708 通過、2 略過(W7 後的 662 + 新增 46)。
- 對組長要確認的事:Step 4、5、10 目前在 `references/legacy-v1.md`,v2 的 P5 步驟等 W6 接線;範本 `stage2_prompt.txt`、`stage3_prompt.txt` 的摘要欄位要和本文件的格式對齊;`no_clear_claim` 是否採用;「不是原句」「不在引用清單」要不要改成退回重摘(建議最多 2 次),等 W6 實跑再決定。
