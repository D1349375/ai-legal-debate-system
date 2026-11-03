# 兩件示範案的 v2 輸入(W8-1、W8-2)

> 組長不在時交給組員(Claude Code)的第 5 批。分支 `demo-v2-inputs`,從 `origin/pleading-exchange` `2989919` 開,只動 `data/cases/`(加上這份說明、iteration-log 一列與一個測試檔)。

## 1. 檔案

| 檔案 | 來源 | 說明 |
|---|---|---|
| `data/cases/test-2026-11-03-v2-gcis-001.json` | `test-2026-10-27-gcis-001.json`(取材 114 台上 1987 原審認定) | 事實、請求逐字沿用;原告順昌導線工業有限公司、統編 29112102,被告「甲、乙」不填統編(照 W2、P1 實跑時的輸入) |
| `data/cases/test-2026-11-03-v2-e2e-001.json` | `test-2026-08-09-e2e-001.json`(取材 114 台上 1547) | 事實只留原告主張那一段(逐字),被告方的說法整段刪掉;請求逐字沿用;當事人以甲、乙代稱 |

欄位照規格 5.1:`protocol`、`represented_side`、`case_type`、`parties`、`facts_summary`、`claims`、`claim_amount`、`evidence`、`opponent_known_responses`、`known_gaps`。舊檔不動,留作對照。

## 2. 缺口,不自己補

| | 商工解散案 | 消費借貸案 |
|---|---|---|
| `evidence` | 空。事實經過提到國稅局 104/2/10 裁處、112/10/12 調閱的登記謄本,原告是否持有、內容為何沒有資料,寫進 `known_gaps` | 空。借款交付、利率約定、清償紀錄都沒有資料 |
| `claim_amount` | 空(撤銷之訴,系爭房地價額沒有資料),寫進 `known_gaps` | 19,787,917:事實經過的三個數字相加(本金 1,000 萬、481 萬 3,529,利息 497 萬 4,388),不含 108/5/16 起的利息。這是算術,不是新資料;訴訟標的價額仍由法院核定 |
| `opponent_known_responses` | 空,寫進 `known_gaps` | 空,寫進 `known_gaps`。原始資料裡的被告抗辯是法院判決所載的,是對照答案,不能當成起訴前已知的反應 |
| 其他 `known_gaps` | 損害賠償請求權、名下無其他財產都只有「原告公司主張」;法定代理人丙待查明 | 「銀行利率」沒寫哪一種;已清償是哪幾筆沒寫;當事人身分沒寫 |

`known_gaps` 只寫「沒有什麼資料」,沒有寫可能的抗辯方向(例如時效、除斥期間),免得把答案帶給原告。

**甲證1–2(2026-11-03 更新,分支 `v2-wiring`)**:最初照「原始資料沒有的標缺口」沒有放證據清單。使用者決定照 P1 那次實跑(`docs/live-run-records/p1-handoff-2026-11-02.md`)放回甲證1(國稅局裁處書)、甲證2(系爭房地登記謄本):兩件都是事實經過提到的文件,名稱、日期、要證事實只取自事實經過,文件全文沒有,寫進 `known_gaps`「證據內容」一筆。這樣 P1 能把事實對到證據,P3 才有可追溯到證據的不爭執事項(X6)。消費借貸案照舊沒有證據清單。

## 3. 防污染(`demo_audit`)

每個檔多一個 `demo_audit` 鍵:`exclude`(給檢索指令的 `--exclude`)、`forbid`(給 `scripts/audit_run.py` 的 `--forbid`)。`main.py case` 只讀規格欄位,UI 建案也不讀這個檔,所以 `demo_audit` 不會進資料庫、角色檔或執行用的 `case.json`(測試有驗)。怎麼帶進執行,見第 3 批 `server/live_run.py` 的文件(A5)。

| | 商工解散案 | 消費借貸案 |
|---|---|---|
| `exclude` | 114年度台上字第1987號 | 114年度台上字第1547號 |
| `forbid` | 字號三種寫法(含語料檔名的「台上,1987」)、`corpus/judgments`、新舊兩個輸入檔、`docs/live-run-records`(先前實跑的輸出)、`demo/recorded_cases.json`(先前的錄製結果) | 字號三種寫法、`corpus/judgments`、`demo/recorded_cases.json`、`docs/zh/e2e-test-report-2026-08-09.md`、新舊兩個輸入檔、`docs/live-run-records`、`video/`(講稿提到真實抗辯) |

查到但沒有列進 `--forbid` 的:`.claude/skills/legal-debate/references/legacy-v1.md` 的已知限制一節寫了「取材114年度台上字第1547號」(只有字號,沒有抗辯內容)。v2 的主 agent 在過渡做法會讀這個檔;字號本身已在 `exclude`,讀到也拿不到全文。要不要刪這句由組長決定(該檔是組長的)。

`audit_run.py` 只看工具輸入,看不到結果(審查 W8-3):不帶路徑的 Grep、`grep -r` 搜到這些檔時抓不到,要人工看,對外只能說「工具呼叫紀錄未見讀取」。

## 4. 怎麼用

- CLI:`python main.py case --json data/cases/test-2026-11-03-v2-gcis-001.json`(指定資料庫時先設 `LEGALDEBATE_DB_URL`),再到 UI 開始執行。
- UI 建案:照檔案內容填表(證據、已知反應留空)。UI 建的案件 ID 不同,`demo_audit` 照樣適用。
- 稽核:`python scripts/audit_run.py <執行資料夾> --forbid <forbid 每一項>`;被告另加 `--agent 被告 --forbid case.json`(審查 W8-4)。

## 5. 實作紀錄

- 2026-11-03 12:20–12:40(組員,Claude Code)。基準 `2989919`。
- 先寫 `tests/test_demo_v2_inputs.py` 再定稿檔案。第一次跑 1 項失敗:e2e 檔的 `source_note` 引了「被告則抗辯」四個字(說明刪了哪段),改寫成「被告方的說法」。另外發現 `demo_audit.note` 初稿寫了抗辯的種類,等於把答案寫進檔案,刪掉。
- 新增測試 7 項:兩件都能用 `main.py case` 落地為 v2 且 `demo_audit` 不進案件;e2e 不含「被告則抗辯、抵償、時效、甲公司、每坪」,事實是舊檔開頭的逐字截取,金額是三數相加;商工案事實與請求和舊檔相同;證據與已知反應是空的且列在缺口;`--forbid` 有交辦的字號與檔案,檔名寫法對得上 `corpus/judgments/` 的實際檔名。
- 沒驗證:沒有實跑;沒有在 UI 建這兩件看畫面;法律上 `claim_amount` 該不該含起訴前利息沒有查(只影響程序類型提示,兩種算法都遠超過 50 萬)。

## 6. 測試數字

- 基準(`2989919`):離線全套 560 通過、2 略過(協作文件第 9 節的數字,本批沒有重跑基準)。
- 做完:離線全套 **567 通過、2 略過、13 未選**(多 7 項,都是新測試;沒有改既有測試)。
