# v2 實跑驗收清單

> 給執行與檢查實跑的 agent。以計畫 [pleading-exchange-plan.md](pleading-exchange-plan.md) 第 3 節的 X1–X10 為底，把每一項寫成「查哪裡、怎樣算過」。2026-11-03 起草，第一次用在工程案 `test-2026-11-03-v2-construction-001`。
>
> 實跑 agent 讀不到 `docs/`(讀檔白名單)，這份清單只給開跑前與跑完後檢查的人或 agent 用。

## 怎麼用

**先跑腳本**。程式判斷得了的項目由 `scripts/acceptance_v2.py` 一次跑完，人工項目會列出候選：

```
python scripts/acceptance_v2.py --case-id <案件 ID> --case-file data/cases/<輸入檔>.json \
    --db-url sqlite:///<資料庫> --answers <答案字串清單(repo 以外)>
```

- 結束碼 0:程式檢查的硬性項目全部通過，畫面(X10a)與斷網重播(X10b)仍要人工做。1:有項目不過，或少給 `--answers` 沒檢查。2:讀不到案件。
- 腳本檢查：X1、X1b、X2、X4、X5、X6、X8a–X8c、X8e、X8f、X9、X9b、X11(硬性);X3、X3b、X7b、X8d(記錄);X7 列出「自承、自認、自陳」每一處給人對照。
- 腳本不檢查：一、開跑前;X4b、X7 的判斷、X12、X10、七、律師角度。
- 加 `--json` 輸出結構化結果，給 agent 寫紀錄用。

- 每一項標了等級：
  - **硬性**:不過，這次實跑就不算通過，照實寫進紀錄，不能用人工修正後再說通過。
  - **記錄**:沒有通過門檻，照實記數字或觀察。
  - **人工**:要讀內容判斷。agent 可以先列出候選，最後由人確認；agent 不能自己判定「通過」。
- 結果寫進 `docs/zh/v2-wiring.md` 第 3 節的實跑表與 `docs/zh/iteration-log.md`,格式見最後一節。
- 下面的 `<id>` 是案件 ID,`run-N` 是這次執行的資料夾(`database/live_runs/run-N/`),`D` 是 `GET /api/cases/<id>` 的回應。
- 只看到工具呼叫、看不到模型讀到什麼，這是稽核的限制，寫結論時要一起寫。

## 一、開跑前(全部要過才開跑)

| # | 檢查 | 怎麼查 | 通過 |
|---|---|---|---|
| P1 | 程式是最新的 | `git status`、`git log -1`;伺服器在最後一個 commit 之後重啟 | 伺服器啟動時間晚於最後一次改 `server/`、`ui/`、`.claude/skills/` |
| P2 | 離線全套 | `python -m pytest -q -m "not network" --basetemp <暫存>` | 0 失敗(記下通過數) |
| P3 | 排除清單有帶進伺服器 | 伺服器啟動指令與啟動時印的「即時執行排除的裁判:N 件」 | 案件檔 `demo_audit.exclude` 的每一個字號都有對應的 `--exclude`,N 等於清單長度 |
| P4 | 排除寫法認得來源字號 | `python main.py judgment <來源字號> --exclude <來源字號>` | 回 `excluded`(確認字號寫法能被比對到；實跑時同一份清單由伺服器用環境變數交給檢索指令) |
| P5 | 案件輸入不含答案 | 讀案件檔的 `facts_summary`、`evidence`、`opponent_known_responses`、`known_gaps` | 沒有法院認定的事實、被告在訴訟中才提出的抗辯或反訴、請求權基礎(人工) |
| P6 | 答案字串清單已準備 | 從來源判決挑出「只有讀過判決才會寫出來」的字串(鑑定數字、法院採用的計算方式、判決才出現的抗辯名稱) | 清單存在 repo 以外(例如 scratchpad),跑完才用;不要寫進 repo,也不要給實跑 agent |
| P7 | 商工查核 | 建案後 `D.party_checks` | 兩方都 `query_status == "ok"`;記下公司狀態與法定代理人 |
| P8 | 額度與預算 | UI 的訂閱額度提示、`/api/health` 的 `budget_usd` | 5 小時額度剩餘足夠(上次全程最多約 9 美元);同帳號沒有其他大量工作在跑 |
| P9 | 決定關卡 1 的走法 | 和使用者確認 | 寫明這次是「自動通過」還是「停在起訴狀 → 律師確認 → 續跑」 |

## 二、執行中(碰到就停，不要硬跑完)

| 狀況 | 怎麼做 |
|---|---|
| 同一角色同一步驟被安全分類器中止 3 次(X2) | 取消執行，紀錄寫失敗 |
| 帳號用量上限(HTTP 429) | 等重置後從斷點續跑；紀錄寫「中斷後續跑」,不算一次跑完 |
| 讀取被拒(白名單擋下) | 不中止；跑完列出被拒路徑，判斷是白名單漏放還是 agent 亂讀 |
| 花費接近上限 | 讓上限自然中止，不要調高上限重跑同一段 |
| 有人想手動改落地的 JSON 或資料庫讓它過 | 不准。改範本或程式後另開新案件重跑 |

## 三、跑完後：流程(X1–X3)

| # | 等級 | 檢查 | 怎麼查 | 通過 |
|---|---|---|---|---|
| X1 | 硬性 | 全部步驟落地，沒有人工修改 | `D.progress`;`git diff database/`(資料庫不進版控，改看 `run-N/` 有沒有人工寫入的檔) | `progress` 中 `case`、`analysis`、`complaint`、`gate1`、`defense`、`answer`、`issue_sheet`、`stage2`、`brief`、`stage3`、`closing`、`verdict`、`revision` 都是 `done`;最後一次執行 `status == "succeeded"` |
| X1b | 硬性 | 全部書狀放行 | `D.pleading_versions` | 每一份系統產生的版本 `exportable == true`、`blocked_count == 0` |
| X2 | 硬性 | 安全分類器中止 | `D.live_runs[-1].safety_stops` | 沒有同角色同步驟 3 次；記下總次數與是誰 |
| X2b | 記錄 | 退回次數 | `run-N/events.jsonl` 中各 `--check` 失敗後重派的次數 | 逐步驟列出(起訴狀 v1、答辯狀、爭點整理表、兩輪、診斷、v2) |
| X3 | 記錄 | 時間、花費、token | `D.live_runs[-1]` 的 `started_at`、`ended_at`、`cost_usd`、`tokens` | 照實寫，對照 #5(14 分、2.79 美元)與 #4;單次結果不寫成平均 |
| X3b | 記錄 | 實際用的模型 | `tokens.by_model` | 寫實際模型，不寫派工參數上的模型 |

## 四、跑完後：書狀內容(X4–X7、X9)

| # | 等級 | 檢查 | 怎麼查 | 通過 |
|---|---|---|---|---|
| X4 | 硬性 | 起訴狀 v1、v2 沒有流程用語 | `pleading_versions` 中起訴狀的 `lint_warnings` | 空陣列 |
| X4b | 人工 | 起訴狀 v1 沒有被告的主張 | 讀起訴狀 v1 正文，對照 `opponent_known_responses` | 被告的說法只出現在原告引述對方已知反應的地方，且有標出處 |
| X5 | 硬性 | 逐點表態涵蓋全部 CF | `D.pleadings.defendant.structured.responses` 的 `fact_id` 與 `D.pleadings.defendant.complaint_facts` 的鍵 | 兩個集合相等 |
| X6 | 硬性 | 不爭執事項都追溯得到 `admit` | `D.issue_sheet.sheet.undisputed[].source` 對 `responses` | 每一項的來源 CF 在答辯狀都是 `stance == "admit"`;0 項時寫「0 項，答辯狀沒有 admit」(這不算失敗，但要寫) |
| X7 | 人工 | 自承類用語 | 在全部書狀與爭點整理表搜尋「自承」「自認」「自陳」(腳本會列出;「承認」多半是「並非承認」這類否認句，不列) | 每一處後面緊接被引述的原句，且原句真的在對方書狀裡；不成立數為 0 |
| X7b | 記錄 | 轉述警告 | `D.questions[].attribution_warning_count`、`D.verdict.attribution_warning_count`、`issue-sheet --check` 的轉述警告 | 列出每一則，人工判斷是否成立 |
| X9 | 硬性 | 程序事項與當事人資料沒有編造 | 起訴狀當事人欄對 `D.party_checks` | 公司名稱、統編、法定代理人與商工登記一致；登記沒有的寫「待查明」,不自己補名字 |
| X9b | 硬性 | 程序條文與裁判分開引用 | 起訴狀「四、程序事項」 | 民事訴訟法第 249 條與裁判字號不在同一個括號(沿用 X9 原意);沒有程序事項時寫「不適用」 |
| X11 | 硬性 | 不給勝訴機率 | `check-judge` 的警告、`D.verdict` 全文 | 沒有勝訴機率類字樣(程式只警告，這裡算硬性) |
| X12 | 人工 | 引用真的支持論點 | 抽查：每份書狀至少一則判決，對照 `precedent_notes` 的 `quote` 與全文 | 抽到的都支持；不支持的列出來 |

## 五、跑完後：隔離與污染(X8)

| # | 等級 | 檢查 | 怎麼查 | 通過 |
|---|---|---|---|---|
| X8a | 硬性 | 沒有 agent 碰到禁用清單 | `python scripts/audit_run.py database/live_runs/run-N --forbid <案件檔 demo_audit.forbid 的每一項>` | 結束碼 0 |
| X8b | 硬性 | 模擬被告沒讀原告的資料 | `python scripts/audit_run.py database/live_runs/run-N --agent 被告 --forbid case.json --forbid plaintiff_view --forbid p1_analysis --forbid complaint.json` | 結束碼 0;「對手摘要」那種本來就要讀對方書狀的 agent 若命中，逐筆說明 |
| X8c | 硬性 | 法官只讀法官角色檔 | 同上，`--agent 法官`,禁用 `case.json`、`plaintiff_view`、`defendant_view` | 結束碼 0 |
| X8d | 記錄 | 讀取被拒 | `audit_run.py` 輸出的每個 agent 的被拒次數(`--json` 的 `denied`) | 列出 agent 與次數；0 最好，有的話對照 stream 找出路徑 |
| X8e | 硬性 | 產出裡沒有答案字串 | 用一-P6 的答案字串清單，搜尋 `D` 的全部文字(書狀、論證、爭點整理表、診斷) | 0 命中。命中時逐筆判斷是自己推出來的還是看過答案，不能判斷就算失敗 |
| X8f | 硬性 | 產出裡沒有來源字號 | 搜尋 `D` 的全部文字找來源字號與二審案號 | 0 命中 |

稽核只看工具輸入，看不到模型讀到的內容；X8e、X8f 補的是產出這一端。兩端都過，也只能說「沒有看到污染的跡象」。

## 六、跑完後：畫面與重播(X10)

| # | 等級 | 檢查 | 怎麼查 | 通過 |
|---|---|---|---|---|
| X10a | 硬性 | 新 UI 每個分頁都畫得出來 | 瀏覽器逐一開 v2 的 8 個分頁，深色、淺色各一次 | 沒有「畫面繪製失敗」,console 沒有錯誤 |
| X10b | 硬性 | 匯出可以斷網重播 | 照 `v2-wiring.md` 第 3 節的斷網重播做法 | 0 次對外連線；這件案件的書狀全部可匯出 |
| X10c | 記錄 | 截圖 | 總覽進度軌、答辯狀逐點表、爭點整理表、診斷、v1/v2 差異 | 存在 repo 以外，給簡報用 |

## 七、跑完後：律師角度(不決定通過與否，但要寫)

| # | 檢查 |
|---|---|
| L1 | 對照來源判決，列出模擬被告的抗辯「命中、漏掉、多出」。只看方向，不是統計 |
| L2 | 診斷的爭點強弱和法院最後的結論方向是否一致；不一致時寫原因(資料不足、推測錯、真的判斷錯) |
| L3 | 起訴狀 v2 比 v1 好在哪、壞在哪(人工) |
| L4 | 待補證據清單裡，有沒有律師起訴前真的拿得到的東西 |

L1、L2 會用到來源判決，只能在跑完、X8 檢查完之後做。

## 八、紀錄格式

寫進 `v2-wiring.md` 第 3 節實跑表一列，另附一段：

```
執行 #N(<案件>,<新案件一次跑完 / 中斷後續跑>,關卡 1:<自動通過 / 律師確認>)
- 結果：<通過 / 不通過>;不通過的項目：<編號與一句原因>
- X1 … X12:逐項寫「過 / 不過 / 不適用」和依據(數字、指令結束碼)
- 人工項目：誰看的、看了哪些
- 限制：稽核只看工具輸入；單次結果
```

「通過」只能在所有硬性項目都過時寫。有一項沒過，就寫「不通過」並列出原因。
