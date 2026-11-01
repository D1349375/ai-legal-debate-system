# 交給 Codex 的 prompt(照實作順序)

> 用法:照順序一次貼一則。每則做完後,把 Codex 的回報交給 Claude 檢核;通過後貼「檢核通過」那則讓 Codex commit,再貼下一則。不通過就貼「交回修正」那則。
> 路徑都是相對於專案根目錄(`LegalDebate/`)。Codex 要在指定的工作目錄啟動。

## 0. 開始前(使用者與 Claude)

- [ ] 讓 Claude 把本資料夾的文件與 W0 紀錄 commit 到 `main-finals-fixes`,讓 Codex 開工時工作目錄是乾淨的。
- [ ] 決定 README 第 4 節 D1–D5(建議都照建議)。

## 1. T1 資料庫設定傳給子程序

工作目錄:`.claude/worktrees/main-finals-fixes`

```text
你在 LegalDebate 專案的 main-finals-fixes 分支工作(工作目錄就是目前這個資料夾,不要切分支、不要 push)。回覆與寫文件一律用繁體中文。

先完整讀這三份,再開始:
1. docs/zh/w0-findings/README.md(特別是第 5 節共同規則與「實作紀錄怎麼寫」)
2. docs/zh/w0-findings/T1-db-url.md(本次任務)
3. docs/zh/main-finals-fix-list.md 開頭的「目前進度」

照 T1-db-url.md 做:先跑離線全套測試記基準(python -X utf8 -m pytest -q -m "not network" -p no:cacheprovider),先寫測試再實作。

紀錄要求:邊做邊把 T1-db-url.md 最後的「實作紀錄(Codex 填寫)」填起來,每一次嘗試(包括失敗、改錯又改回)都寫一列迭代過程;測試寫實際指令與數字。在 docs/zh/main-finals-fix-list.md 文末建立「## W0 後修正」段落(表格欄位:任務、commit、測試數字、結果),加 T1 這一列,commit 欄寫「未 commit」。

不要 commit。做完回報:改了哪些檔、測試數字、與任務文件不同的地方、沒驗證的事。
```

## 2. T2 機械彙整改由程式落地

工作目錄:`.claude/worktrees/main-finals-fixes`

```text
繼續在 main-finals-fixes 分支工作,不切分支、不 push。回覆與文件用繁體中文。

先讀 docs/zh/w0-findings/README.md 第 2 節 F2 與第 5 節,再讀 docs/zh/w0-findings/T2-mechanical-anchor.md(本次任務)。

照 T2 做。重點:
- main.py verdict 落地時自己呼叫 finalize_case 重算,不再用模型給的 mechanical_anchor_json。
- _anchor_check 改比全部欄位前,先用 demo/recorded_cases.json 匯入暫存資料庫量測哪些舊案會變不一致,量測表填進任務文件。舊案的差異要誠實顯示,不要藏,也不要說成竄改。
- 要看 UI 時用暫存資料庫另開一個沒用到的埠啟動,不要關掉別人開著的伺服器(8124 可能還開著)。
- database/legal_debate.db 只能複製到暫存位置後再讀,不能寫。

邊做邊填 T2 的實作紀錄與迭代過程;在 main-finals-fix-list.md「W0 後修正」加 T2 一列。不要 commit。做完回報改了哪些檔、測試數字、量測表重點、與任務文件不同之處、沒驗證的事。
```

## 3. T3 自承檢查補資料缺口詞

工作目錄:`.claude/worktrees/main-finals-fixes`

```text
繼續在 main-finals-fixes 分支,不切分支、不 push。繁體中文。

先讀 docs/zh/w0-findings/README.md 第 2 節 F3 與第 5 節,再讀 docs/zh/w0-findings/T3-admission-soft-terms.md。

照 T3 做。重點:
- 先寫量測工具(放在系統暫存資料夾,不進 git),用修改前與修改後的 admission_problems 跑現有紀錄,逐句列出新增被擋的句子並判斷該擋或誤擋。誤擋要是 0。
- 資料來源:demo/recorded_cases.json、database/legal_debate.db 的暫存複本。另一個 worktree 的資料庫(.claude/worktrees/ui-live-run-0f7cc8/database/legal_debate.db)要先問我同不同意才能讀。
- 「承認」要不要加進 ADMISSION_RE 只量測、寫建議,不要改。
- 不要加單字「不明」。

邊做邊填 T3 的實作紀錄(詞表每改一次就記一列);main-finals-fix-list.md「W0 後修正」加 T3 一列。不要 commit。做完回報。
```

## 4. T4 段落外自我檢討警告

工作目錄:`.claude/worktrees/main-finals-fixes`

```text
繼續在 main-finals-fixes 分支,不切分支、不 push。繁體中文。

先讀 docs/zh/w0-findings/README.md 第 2 節 F5 與第 5 節,再讀 docs/zh/w0-findings/T4-self-review-warnings.md。

照 T4 做。重點:
- 先量測再補詞;不要加單獨的「最弱」「備位」「風險」。量測表逐句判斷該警告或誤報。
- 維持只警告,不改成硬擋,不改 stage 範本,不新增 JSON 欄位。
- UI 要看得到警告次數:兩種做法(記進 live_runs.notes_json,或讀案件時用 review_warnings 重算)選一個,理由寫進紀錄。
- 用暫存資料庫另開埠看 UI,深淺色都看。

邊做邊填 T4 的實作紀錄;main-finals-fix-list.md「W0 後修正」加 T4 一列。不要 commit。做完回報。
```

## 5. T5 停用 PowerShell 工具

工作目錄:`.claude/worktrees/main-finals-fixes`

```text
繼續在 main-finals-fixes 分支,不切分支、不 push。繁體中文。

先讀 docs/zh/w0-findings/README.md 第 2 節 F7 與第 5 節,再讀 docs/zh/w0-findings/T5-windows-tools.md。

照 T5 做。重點:
- DISALLOWED_TOOLS 加 "PowerShell",既有項目不動、不放寬 ALLOWED_TOOLS、不改 SNAPSHOT_ENV。
- prompt 與 SKILL 的查證 subagent 指示寫明用 Bash 工具、一次一個 python main.py 指令。
- 用 claude --help 或官方文件確認 --disallowedTools 接受 PowerShell;不要跑 claude -p(會用額度)。查不到就寫「無法確認,待 C1」。

邊做邊填 T5 的實作紀錄;main-finals-fix-list.md「W0 後修正」加 T5 一列。不要 commit。做完回報。
```

## 6. T6 匯出與斷網重播(V39)

工作目錄:`.claude/worktrees/main-finals-fixes`

```text
繼續在 main-finals-fixes 分支,不切分支、不 push。繁體中文。

先讀 docs/zh/w0-findings/README.md 第 2 節 F9 與第 5 節,再讀 docs/zh/w0-findings/T6-export-replay.md。

照 T6 做。重點:
- export-demo 加 --out;有 case_id 欄位的表要擋孤兒列(不匯出、列出筆數),不刪資料庫的列。
- V39:資料庫先複製到暫存位置,匯出到暫存資料夾,另開一個暫存的乾淨 clone,斷網啟動並逐分頁看 W0 案件 live-2026-11-02-gcis-w0b,結果照實填表。
- 不覆寫 demo/ 任何檔(做完 git status 確認 demo/ 沒變);不跑要連網的 --live-checks,只寫建議。

邊做邊填 T6 的實作紀錄;main-finals-fix-list.md「W0 後修正」加 T6 一列。不要 commit。做完回報。
```

## 7. C1 修正後重跑(交給 Claude,不是 Codex)

T1–T5 都 commit 後,跟 Claude 說:「跑 C1」。Claude 照 [`C1-rerun.md`](C1-rerun.md) 跑,約 12 分鐘、CLI 帳號 5 小時額度約 25%。

## 8. T7 合併進 pleading-exchange

工作目錄:`.claude/worktrees/pleading-exchange`(注意換資料夾)

```text
你現在在 LegalDebate 專案的 pleading-exchange 分支工作(工作目錄就是目前這個資料夾,不要切分支、不要 push、不要併 main)。繁體中文。

先讀:
1. docs/zh/pleading-exchange-handoff.md(全文,特別是第 5 節不能違反的事、第 7 節已知陷阱)
2. main-finals-fixes 分支上的 docs/zh/w0-findings/README.md 與 T7-merge.md(可用 git show main-finals-fixes:docs/zh/w0-findings/T7-merge.md 讀)

照 T7 做:確認工作目錄乾淨(有未 commit 的檔就停下來回報,不要 stash),跑基準測試,git merge main-finals-fixes(一般 merge)。衝突逐一解,DISALLOWED_TOOLS 保留本分支既有規則再加 PowerShell,SNAPSHOT_ENV 不動,_anchor_check 把 T2 的邏輯套在本分支版本上。每個衝突怎麼解寫進 T7-merge.md 的「衝突與解法」。合併後在本分支重跑 T3、T4 的量測。更新 pleading-exchange-handoff.md 第 2 節、iteration-log.md、pleading-exchange-plan.md 的 W0 列。

merge 本身需要一個 merge commit:衝突解完、測試通過後先停下來回報,不要自己 commit,等我確認。
```

## 9. T8 條文內容核對

工作目錄:`.claude/worktrees/pleading-exchange`

```text
繼續在 pleading-exchange 分支,不切分支、不 push。繁體中文。

先讀 docs/zh/w0-findings/README.md 第 2 節 F6 與第 5 節、docs/zh/w0-findings/T8-statute-content-check.md、docs/zh/retrieval-interface.md 第二節(哪些檔是組員的,不能改)。

照 T8 做。重點:
- 只改 SKILL Step 8(加條文內容核對,用 python main.py article)與法官訊問指示的一句;不得放寬既有閘門,不得給編排者代為改寫的空間。
- 「找出要核對的引用」兩種做法選一個;若新增指令,放在我們自己的新檔,不要改 engine/verify.py、law_lookup.py 等組員的檔,先寫測試。
- 不要在 SKILL 或範本寫「正確條號」當例子。

邊做邊填 T8 的實作紀錄(含 SKILL 改動前後對照);handoff 第 2 節與 iteration-log.md 加一列。不要 commit。做完回報。
```

## 10. T9 最強論點選句(建議和 W6 一起)

工作目錄:`.claude/worktrees/pleading-exchange`

```text
繼續在 pleading-exchange 分支,不切分支、不 push。繁體中文。

先讀 docs/zh/w0-findings/README.md 第 2 節 F8 與第 5 節、docs/zh/w0-findings/T9-strongest-point.md、docs/zh/pleading-exchange-plan.md 的 W6。

照 T9 做。重點:
- SKILL Step 4、Step 5 加最強論點選句標準。
- 新增 python main.py check-summary(只警告、exit code 0),放在我們自己的檔。摘要格式先讀 main-finals-fixes 工作目錄 database/live_runs/run-1/ 的 opp_s*_for_*.json 實例(只讀,不複製進 git);格式不固定就在 SKILL 定最小格式,欄位名避開共同規則第 8 點的禁用字。
- 先寫測試,W0 那句讓步句要警告。

邊做邊填 T9 的實作紀錄;handoff 第 2 節與 iteration-log.md 加一列。不要 commit。做完回報。
```

## 共用:檢核通過後讓 Codex commit

```text
Claude 已檢核 <任務代號> 通過(檢核結果寫在 docs/zh/w0-findings/<任務檔名> 最後)。請把這項任務的改動 commit 成一個 commit:訊息用英文祈使句、說明做了什麼。commit 前 git status 確認沒有混入其他任務的檔、沒有資料庫或暫存檔。commit 後把 commit hash 填回任務文件的實作紀錄與 main-finals-fix-list.md(或 handoff)那一列,這個回填再單獨 commit 一次或併入同一個 commit 都可以,說明你怎麼做。不要 push。
```

## 共用:檢核沒過,交回修正

```text
Claude 檢核 <任務代號> 沒有通過,要改的地方寫在 docs/zh/w0-findings/<任務檔名> 最後的「檢核結果」。請逐項修正,每項修正都在實作紀錄的迭代過程加一列(對應哪一條檢核意見、怎麼改、測試結果)。改完重跑離線全套測試,不要 commit,回報每一條意見的處理結果。
```
