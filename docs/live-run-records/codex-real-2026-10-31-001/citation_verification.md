案件 real-2026-10-31-001｜Step 8 引用查核紀錄（2026-10-31）

引用內容查核通過：73 個原始引用字串，依法律引用身分去重為 65 項（60 個法條、5 件裁判）。5 件最終判例均已讀取本地全文，與所提供判決及 Stage 3 的限縮援引命題相符。

已執行 python -B main.py verify，73 個引用均以位置參數傳入，資料庫為 sqlite:///database/codex_runs.db。首次 72 項通過；民法第130條發生 SSL UNEXPECTED_EOF_WHILE_READING，對同一原始引用重試後通過，未改寫引用。完整官方條文及CLI結果見三份 mechanical_verification JSON。

已遞迴核對各階段 cited_statutes、cited_precedents、判決 citations_used，並掃描正文完整引用，沒有遺漏。未發現額外 legal_basis；程序錨點 issues 為空，不代表兩造程序身分已查核完成。

| 裁判 | 原文及可採命題 | 現有引用結論 |
| --- | --- | --- |
| 115台上65判決 | [全文第219行](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/corpus/judgments/TPSV,115,台上,65,20260304,1.txt:219)；有效減價後，對實際溢付價金依民法第179條請求返還。 | 通過。不能證明本案價金已付清、漏水造成永久貶值或任何確定減價比例。 |
| 115台上336判決 | [全文第175行](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/corpus/judgments/TPSV,115,台上,336,20260416,1.txt:175)；知情範圍須有證據，不得由已揭露的一種現象臆測買方知悉全部隱藏瑕疵。 | 通過。不能直接證明本案不知漏水；對民法第360條、第227條僅要求闡明原請求，未認定賠償成立。 |
| 115台上386裁定 | [全文第103行](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/corpus/judgments/TPSV,115,台上,386,20260319,1.txt:103)；僅提示瑕疵通知、形成權行使、受領代理權與表示到達應予區分。 | 通過。不得升格為最高法院實體判例規則，亦不能據此判定本案仲介無權、減價逾期或已及時生效。 |
| 115台上206判決 | [全文第185行](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/corpus/judgments/TPSV,115,台上,206,20260312,1.txt:185)；催告內容足以辨認給付標的即可，不應割裂函件與先前口頭通知觀察。 | 通過。仍須證明本案實際催告內容、到達與相應給付義務；催修不當然等於減價表示。 |
| 115台上561判決 | [全文第137行](C:/Users/berto/Desktop/my/personal/ai-legal-debate-system/corpus/judgments/TPSV,115,台上,561,20260422,1.txt:137)；民事訴訟法第222條第2項須先證明損害，且有客觀數額證明困難，酌定須有相關具體因素、計算標準及可受檢驗的說理。 | 通過。不能補足本案責任、損害存在、有效減價、付款或確定本金之證據。 |

資料庫覆核：65 個引用身分各有一筆紀錄，全部為 published，沒有遺漏、未發布或重複身分。判決的24個 citations_used 均可通過資料庫引用關卡。本案 verdicts 與 pleading_drafts 仍均為0筆，本回合僅完成查核。

獨立性紀錄：本回合未參與原論證或判決撰寫，從 Step 8 查證任務開始。環境沒有另啟 subagent 工具，故本回合未另啟巢狀代理；主流程是否已將本回合以獨立 subagent 啟動，仍須由主流程的啟動紀錄確認。引用內容通過不替代此結構性要求。

後續 Step 9 僅能在已核對命題範圍內採用上述判例；尚未提供的訴狀文字不在本報告範圍。新增引用、改變用途或編輯引用須重新查核，編輯引用依規則重置 draft。

原始引用、攻防及判決檔均未改寫。逐件案由、爭點、支持段落、全文 SHA-256 及查核結論詳見 verification_report.json。
