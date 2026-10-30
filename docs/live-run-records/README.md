# UI 即時執行實跑紀錄

2026-10-28、29 從 UI 按「開始即時執行」,由本機 Claude Code(`claude -p`,模型 `claude-sonnet-5-5`,Claude Pro 訂閱)跑 legal-debate 流程留下的原始紀錄。這是 `database/live_runs/` 的**複本**,原樣保存,之後不會更新;該資料夾本身仍不進 git。

案件都取材自最高法院 114 年度台上字第 1987 號(順昌導線工業有限公司,撤銷詐害債權,被告以甲、乙匿名)。

| 紀錄 | 案件 ID | 時間(UTC) | 歷時 | Claude Code 估算花費 | 結果 |
|---|---|---|---:|---:|---|
| `run-1` | `live-2026-10-28-gcis-001` | 10-28 07:18 | 12 分 03 秒 | 3.81 美元 | 失敗:Pro 5 小時額度用完(HTTP 429),尚缺原告與被告 Stage 3、爭點評估、訴狀 |
| `run-2` | `live-2026-10-28-gcis-002` | 10-28 11:58 | 10 分 51 秒 | 2.51 美元 | 成功(沒有填統編,未做商工查核) |
| `run-3` | `live-2026-10-28-gcis-003` | 10-28 12:44 | 3 分 49 秒 | 0.75 美元 | 流程不完整:原告 Stage 1 連續 3 次被安全分類器 `reasoning_extraction` 中止 |
| `run-4` | `live-2026-10-29-gcis-004` | 10-29 05:34 | 14 分 39 秒 | 3.25 美元 | 成功(統編 29112102);被告 Stage 1 被分類器中止 1 次,主 agent 重派後成功 |

想看一次完整流程,從 `run-4` 開始。

## 每個資料夾裡有什麼

各次的檔案不完全相同(檔名由當次的 Claude 決定)。`stderr.log` 四次都是空檔,且被 `.gitignore` 排除,沒有放進來。

| 檔案 | 內容 |
|---|---|
| `stream.jsonl` | Claude Code 的完整原始輸出(stream-json),含工具呼叫、subagent 回覆與結果事件 |
| `events.jsonl` | UI 上顯示的步驟紀錄(`run-1` 沒有,當時還沒有這個檔) |
| `case.json` | 這次的案件輸入與當事人 |
| `stance_terms.*`、`procedural_issues.json`(`run-2` 為 `issues.json`) | 立場驅動檢索詞、起訴審查產生的程序事項 |
| `run-1`:`stage1_*`、`stage2_*`、`summary_*`<br>`run-2`:`s1_*`、`s2_*`、`s3_*`<br>`run-4`:`p_s*`(原告)、`d_s*`(被告) | 雙方各階段論證;檔名含 `summary` 的是給對造看的結構化摘要 |
| `q*.json`、`judge_q*.json`、`judge_questions.json` | 法官訊問 |
| `anchor*.json` | 機械死穴彙整(finalize)的結果 |
| `verdict.json` | 法官爭點強弱評估 |
| `pleading_draft.txt`、`pleading_citations.json` | 訴狀骨架草稿與它引用的清單 |

## 閱讀時要注意

- 這些是當時的版本。當時流程只產原告起訴狀,**沒有被告答辯狀**;之後改動的內容(答辯狀、使用者自選書狀、從中斷處續跑)不在這裡。範本欄位也可能和現在不同。
- 花費是 Claude Code 的估算值,實際是占用訂閱額度,不是另外付費。
- 實跑時的詳細問題與修正記在 commit `e75c4c3`、`cea795e` 與 [`ui/README.md`](../../ui/README.md)。
- 內容是 AI 推演的攻防與骨架初稿,不是法律意見,也不是法院判決預測。
- `stream.jsonl` 含帳號當時的訂閱額度、session ID 與本機路徑,沒有金鑰或 email。
