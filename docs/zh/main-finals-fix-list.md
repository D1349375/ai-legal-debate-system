# main 決賽前修改紀錄與驗證清單

> 2026-11-01 建立,基準 commit `aeb618e`。這是我們自己修 `main` 的工作紀錄,**不用組員處理**。
> 組員版本的修正清單另外在 `role-separation-redesign` 的 `docs/zh/role-separation-fix-list.md`。
> 分支:`main-finals-fixes`。完成後開 PR 到 `main`,不要直接 push `main`。
> 行號以 `aeb618e` 為準。估時是判斷,不是量測。

## 目前進度(2026-11-01)

- **第一批 M1–M8 已實作。** 離線測試 `239 passed, 1 skipped, 13 deselected`(基準 208),瀏覽器實測示範案 25/25、彙整頁改名、舊評估說明、答辯狀標示與字樣警告都正常,console 無錯誤。
- **第二批 M9–M11 還沒開始,也還沒用 Claude 實跑。**
- 與下文不同的做法:字樣檢查放在 `server/pleading_export.py`,因為它要用同檔的 `split_draft_note`;攻防分頁的說明用通用提示。`土地法第34條之1` 這類不支援法規的狀態從 `unparseable` 變成 `unknown_law`,仍然不放行。
- 還沒驗:真的斷網、乾淨 clone、深色模式、在瀏覽器裡用律師編輯加入不存在字號(目前只有 API 與 mock 測試)。
- 併入 `main` 後,本機資料庫要再跑一次 `python main.py verify "最高法院105年度台簡上字第33號"`。已有資料的資料庫不會重新匯入 fixture。

## 目的與範圍

`main` 是決賽的保底版本。這份清單只放**不依賴職責分離新流程**的修正。

| 批次 | 內容 | 驗證方式 | 期限 |
|---|---|---|---|
| 第一批 | M1–M8:查證、字樣檢查、標示、改名 | 離線測試加連網測試,不跑模型 | 11/2 |
| 第二批 | M9–M11:法官與雙方的範本 | **必須用 Claude Sonnet 5.5 實跑一件** | 程式 11/2,實跑 11/3 前 |
| 凍結 | 全部併入 `main` | 第 5 節驗證清單 | 11/5 晚上 |

第二批沒跑過就不能算完成。實跑失敗時,第二批不併,第一批照併,簡報照實講成下一版設計。

`role-separation-redesign` 不在本清單範圍。本清單併入 `main` 後,再把 `main` 併進深化分支。該分支的 `verify.py` 改動較多,預期要手動解衝突。

## 不要做的事

- 不要在 `main` 引入主張編號、內部備註、三欄事實、代理方欄位、程式摘要、參考等級。這些都屬於新流程。
- 不要改資料庫欄位名稱。`weak_points`、`position_drift`、`falsifier` 已存在錄製紀錄裡,只改顯示文字。
- 不要改 `verification_failed` 這個狀態名。`server/services.py`、`server/seed.py`、`ui/app.js` 都依賴它。
- 不要用 Codex 的結果當第二批驗收,現場跑的是 Claude。
- 範本的輸出 JSON 不要新增欄位,欄位名也不要含 `reasoning`。這個字樣曾和 `reasoning_extraction` 分類器中止同時出現;改名後實跑 #4 跑完,但仍被擋過一次。因果未證實,分類器也無法根治。
- 這個 repo 是公開的。不要 commit `database/legal_debate.db`、本機絕對路徑、學校或個人資料。

---

## 第一批:不跑模型

### M1. 修 FJUD 搜尋只讀第一頁(最優先)

**位置**:`engine/verify.py:134-170` `_fjud_search`。

**現況與證據(2026-11-01 實測)**:
- 搜尋「105年度台簡上字第33號」共 50 筆,分 3 頁(每頁 20 筆)。目標在第 3 頁,JID 是 `TPSV,105,台簡上,33,20161026`。
- 程式只讀第一頁,所以回報 `not_found`。這筆判決**不是捏造**。
- 下一頁連結在 `id="hlNext"` 的 `href`,格式 `/FJUD/qryresultlst.aspx?q=<token>&sort=DS&page=2`。
- 加 `&sort=LG`(法院層級大到小)時,這筆會出現在第 1 頁。

**改法**:
1. 取得 token 後,用同一個 opener 讀 `qryresultlst.aspx?q=<token>&sort=LG`,讓最高法院排在前面。實作時確認這個請求要帶的 Referer。
2. 逐頁讀 `hlNext`,每頁間隔 1.5 秒(沿用現有延遲)。找到符合 `_jid_matches` 的 JID 就停止。
3. 頁數設上限(建議 10 頁)。**到上限還沒看完時不可回 `not_found`**,要回 `verification_failed`,並在 `note` 寫明沒有查完。沒查完不等於查無。
4. 沒有 result token 目前一律當成沒有結果。不存在的字號確實沒有 token(`105年度台上字第99999號` 實測如此),但頁面異常也會走到這裡。至少檢查首頁的 `__VIEWSTATE` 取得成功,取不到就回 `verification_failed`。
5. 修改 `_fjud_search` 的回傳或新增內部函式時,`verify_judgment_citation` 回傳的 `fjud_raw_hits` 仍要保留,`server/services.py:886` 會用到。

**驗收**:V1、V2、V3。

### M2. 更新所有把這筆判決當捏造的地方

M1 完成後才做。

| 位置 | 現況 | 改法 |
|---|---|---|
| 本機 DB 與 `demo/recorded_live_checks.json` | 記錄為 `not_found` | 跑 `python main.py verify "最高法院105年度台簡上字第33號"`,再跑 `python main.py export-demo --live-checks`。匯出前確認 diff 只有預期變動 |
| `demo/recorded_cases.json` | `citation_verifications` 少這筆 | 同上。示範案 `test-2026-08-09-e2e-001` 應從 24/25 變 25/25 |
| `ui/README.md:112` | 「捏造字號」當離線範例 | 改用「不存在的字號」範例 `最高法院105年度台上字第99999號` |
| `tests/test_server.py:16`、`tests/test_pleading_versions.py:13` | 常數 `FABRICATED` 指向這筆 | 改成 99999 這筆,常數改名 `NONEXISTENT`。相關 mock 一起改 |
| `docs/zh/e2e-test-report-2026-08-09.md` | 第 22–24、44 行寫查無、三層機制一致 | 歷史紀錄不改內文,檔案開頭加一段更正:該筆實際存在,是查證程式只讀第一頁造成漏判,三層都沒有抓到真實狀態 |

**注意**:`export-demo` 會匯出你本機的整個 DB。如果本機有測試案件,先確認不會一起進 fixture。

**驗收**:V4。

### M3. 補法規白名單,不支援的法律不再顯示「無法解析」

**現況**:
- `main` 已經分得出 `not_found`、`verification_failed`、`unknown_law`、`unparseable`,**不需要新增連線錯誤狀態**。
- 缺口是 `STATUTE_CITATION_RE`(`engine/verify.py:57`)寫死法律名稱,所以 `銀行法第29條` 解析成 `unknown`,顯示「無法解析」,`unknown_law` 分支實際上走不到。
- `verify_statute_citation`(:112)、`verify_judgment_citation`(:195)只接三種例外。`ssl.SSLError` 已是 `OSError` 的子類,但沒有被列入;`http.client.IncompleteRead` 這類例外也會直接拋出,讓 `main.py verify` 中斷。

**改法**:
1. `STATUTE_PCODES` 補三部,pcode 已對全國法規資料庫實查標題:
   - `銀行法`:`G0380001`
   - `民法債編施行法`:`B0000003`
   - `民事訴訟法施行法`:`B0010002`
2. `STATUTE_CITATION_RE` 改由 `STATUTE_PCODES` 組成,依長度由長到短排序。
3. 新增 `UNSUPPORTED_STATUTE_RE`,比對其他「…法/條例/規則/辦法/通則第N條」。`parse_citation` 依序比對:白名單法條 → 判決字號 → 不支援法律。後者回傳 `type: statute`,讓既有 `unknown_law` 分支生效。
4. 兩處 `except` 改成接 `(OSError, http.client.HTTPException)`,都回 `verification_failed`。
5. 確認 `server/services.py:295`、`:319-342` 的引用抽取在新正則下仍正常,特別是律師自由編輯的情況。

**驗收**:V5。

### M4. 舊版條文標「版本未查證」

**現況**:`108年民法第205條`、`修正前民法第205條` 都解析成 `民法第205條`,查到現行條文就通過,等於驗錯版本。`_citation_key` 也把它們視為同一筆,所以 `_assert_all_published` 會被現行條文的紀錄放行(`database/db.py:270-279`)。

**改法**:
1. `engine/verify.py` 新增 `is_historical_statute(citation_text)`。可參考 `role-separation-redesign` 的 `_historical_version`,但這裡只需判斷引用字串本身。
2. `verify_citations` 與 `server/services.py` `verify_one` 對法條先檢查,命中就回新狀態 `version_unverified`,不連網,不放行。
3. `server/services.py:45` `STATUSES` 加入;`ui/app.js:43` 附近加標籤「版本未查證」;`ui/app.js:845` 的統計納入。
4. `database/db.py` `_assert_all_published`:`citations_used` 中的舊版條文一律視為未通過,不能借現行條文的紀錄。
5. `server/services.py` 書狀引用檢查(:319-404)也要遵守。書狀文字改成「108年民法第205條」時不可被當成已通過的「民法第205條」。

**誤判基準**:本機 5 案、98 個不重複引用,目前命中 0 筆。改完應維持 0 筆。

**驗收**:V6。

### M5. 同字號多份文件時提示

**現況**:`engine/verify.py:185` 取 `candidates[0]`。語料有 19 個字號對應多份文件,例如 `114台上1945` 有 20260304 與 20260513 兩份。已錄製引用中只有 `最高法院115年度台上字第192號` 受影響,兩個示範案都沒有。

**改法**:
- 維持 `published`,**決賽前不擋**。舊範本沒有裁判日期欄位,擋下會讓舊流程跑不完。
- 回傳加 `candidates`(檔名與日期)。`verify_one` 的 `note` 寫明「此字號有 N 份文件,僅確認字號存在,請律師確認引用的是哪一份」。
- `ui/app.js` 查證列顯示提醒。
- SKILL Step 8 第二項任務補一句:多份文件時每份都要讀,再判斷是否支持論點。

**驗收**:V7。

### M6. 書狀字樣檢查(只警告,不擋)

**現況**:模擬用語會混進書狀正文。下表是 `split_draft_note` 切掉系統補充說明後,正文的命中數:

| 草稿 | 方 | 命中 |
|---|---|---|
| `08-08-001` | 原告 | Stage ×1 |
| `08-08-002` | 原告 | Stage ×1、被告主張 ×2、被告自承 ×2 |
| `08-08-003` | 原告 | Stage ×1、本方 ×1 |
| `e2e-001`、`gcis-001` | 原告 | 0 |
| `gcis-001` | 被告 | Stage ×19 |

`gcis-001` 答辯狀的 19 筆應主要來自 SKILL 9B 第 5.2 點規定的「(被告 Stage 3 未表示意見,待律師補充)」。實作時確認,並把 SKILL 改掉。

**改法**:
1. 新增純函數 `engine/pleading_lint.py`:`lint_pleading(text, side)`,回傳命中詞與次數,只檢查正文。
   - 原告:`被告主張|被告抗辯|被告自承|被告或將|本方|對造|stage|輪次|前輪|法官訊問|訊問攻防`
   - 被告:只查流程用語 `stage|輪次|前輪|法官訊問|訊問攻防|本方|對造`。「原告主張」是答辯狀的正常內容。
2. `main.py pleading` 命中時把警告印到 stderr,**仍落地、exit 0**。
3. `server/services.py` 書狀版本資料帶 `lint_warnings`,`ui/app.js` `pleadingPanel`(:1113)顯示警告。**不要**阻擋匯出。
4. 不用硬擋的原因:起訴狀可能合法引述被告在存證信函的說法。律師自己要判斷。
5. SKILL 9B 第 5.2 點改成「(被告未表示意見,待律師補充)」。

**驗收**:V8。

### M7. 模擬標示

**現況**:答辯狀針對的是 AI 模擬的原告,不是實際起訴狀,畫面與匯出都沒有寫。`main` 沒有代理方欄位,**不能標「對方預測」**,改成全案通用的說明。

**改法**:
1. `ui/app.js:19` `DOCUMENT.defendant.lede` 加「模擬答辯:回應的是系統模擬的原告主張,不是實際起訴狀,只能用來預想防禦。」
2. `server/pleading_export.py:30`、`:53-63`:答辯狀匯出的副標加「模擬答辯,非針對實際起訴狀」。檔案開頭規定兩邊規則要一起改,`ui/app.js` 的 `pleadingDoc` 同步。
3. `ui/app.js` 攻防過程分頁頂端加一句:「雙方論證都是 AI 依輸入資料模擬,不是當事人或對方律師的實際主張。」

**驗收**:V9。

### M8. 彙整頁改名與文案

**理由**:`engine/aggregate.py` 的 `compile_weak_points` 沒有計算弱點,只是抄錄雙方自己寫的讓步條件;本機 5 件評估都是雙方各一筆,分不出誰弱。`disagreement` 算的是引用集合的 Jaccard 距離,不是立場。法官曾把這些數字寫成「被告立場波動程度高於原告」「攻防拉鋸」。

| 位置 | 改成 |
|---|---|
| `ui/app.js:702` 標題 | 「讓步條件與引用清單差異」 |
| `ui/app.js:703` 說明 | 「本頁不呼叫 AI。讓步條件是雙方自己寫的假設句,原樣列出,不代表系統判定弱點。引用清單差異只比較前後階段引用的法條與判決,不代表立場變化。」**刪掉「法官的評估不得偏離」** |
| `ui/app.js:707`、`:718`、`:725`、`:730`、`:918-929` | 弱點 → 讓步條件;立場位移 → 引用清單差異 |
| `ui/app.js:945-946`、`server/pleading_export.py:18-19` | `position_drift` → 引用清單差異;`weak_points` → 雙方讓步條件(兩邊同步) |
| `server/services.py:268`、`:494` | 「立場位移度」→「引用清單差異」;「機械死穴彙整」→「機械彙整」。`tests/test_server.py:148` 一起改 |
| `server/services.py:740`、`main.py:9`、`:281` | 說明文字同步 |

分頁名稱「機械彙整」保留,因為它確實不呼叫 AI。

**舊評估標示**:
- `main.py:35` `PROTOCOL_VERSION` 改成 `v1.1-2026-11-02`,但**第一批先不改值**,第二批才改。
- `ui/app.js` `verdictPanel`(:882)在 `protocol_version` 為 `v1-2026-08-07` 時顯示:「這份評估在舊規則下產生,當時要求法官不得偏離彙整結果。文中的『錨點』『自承』不代表系統判定,請對照原文。」
- 5 份錄製評估都是舊版,都會顯示這段。

**驗收**:V10。

---

## 第二批:範本修改,必須實跑

所有範本都在 `.claude/skills/legal-debate/templates/`。`tests/test_live_run.py`、`tests/fake_claude.py` 有引用流程內容,改完要跑。

### M9. 法官評估不再受錨點方向約束

**新增程式**:`main.py finalize --for-judge` 輸出給法官的版本,只含:

```json
{"concession_conditions": [{"side": "plaintiff", "condition": "falsifier 原文"}], "procedural_issues": {}}
```

不含 `position_drift`、`response_excerpt`。完整 `finalize` 輸出照舊用於 `verdict --json` 的 `mechanical_anchor_json`,`anchor_check` 才不會壞。UI 無人值守只允許單一 `python main.py` 指令,不要用管線。

**`verdict_prompt.txt`**:

第 5 行改成:
> 3. 用 Read 讀取雙方讓步條件與程序事項:{MECHANICAL_ANCHOR_JSON_PATH}(程式原樣彙整,非 LLM 產出)

第 12 行整段換成:
> **讓步條件的讀法(硬性)**:`concession_conditions` 是雙方自己寫的「若出現 X,我方會改變評估」假設句,不是已發生的事實,不是承認,也不是系統判定的弱點。你要逐條回應:依現有紀錄,該條件已滿足、未滿足,或仍待確認,並可以不同意它的重要性。沒有任何方向是預先決定的。
> **不得**把假設句或「資料未載」寫成「自認」「自承」「承認」「坦承」。只有該方在紀錄中對事實作出明確陳述時才能這樣寫,而且要引述原句。多個論點若來自同一則事實,不得寫成「相互印證」。資料沒寫的事項寫「待確認」,不得寫成有或沒有。引用清單的增減不是立場變化;要說立場改變,必須並列該方前後兩輪的原文。

第 14–19 行程序事項**不動**。`procedural_issues` 來自官方登記加固定規則,維持優先處理。

### M10. 雙方與法官訊問的資料紀律

**新增段落**,加到 `stage1_prompt.txt` 第 25 行前、`stage2_prompt.txt` 第 25 行前、`stage3_prompt.txt` 第 21 行前:

> **資料紀律(三輪都適用)**:
> - 案件資料沒寫的事一律寫「待確認」,不得寫成有,也不得寫成沒有。資料未載不等於不存在,也不等於對方承認。
> - 你是代理人。未經當事人同意,不得代當事人承認事實、接受金額或放棄主張。
> - 不得以「資料不足」「日期未載」「沒有當事人事實」為由撤回主張或抗辯。撤回只能因案件資料直接否定,或對方法律論點確實成立,並寫明依據。資料不足時保留並標「待確認」。
> - 對方沒提到的事,不得寫成對方「不爭執」「自認」「自承」。

**`stage2_prompt.txt`**:
- 第 25–30 行五準則換成三準則:
  > 回應紀律(三準則):1. 不重複 Stage 1 已講過的論述。2. 開新的法律角度,但不得補案件資料沒有的事實。3. 直接回應法官對你方的訊問與對造的最新主張。需要依據才引用,不必為了增加引用而另找判決。
- 第 40 行「(`based_on` 對應到的主張你必須認,不得說「這不是我方主張」)」改成:
  > (法官若誤述你方主張,要明確更正並指出你方原話,不得因法官這樣問就承認)
- 第 41 行改成:
  > (b) 給出 falsifier:什麼具體證據出現,會讓你改變評估。這是假設條件,不是承認。

**`stage3_prompt.txt`**:
- 第 21 行改成三準則,保留「收斂到最終立場」。**加一句**:收斂只針對已主張的項目,待確認的抗辯要保留。
- 第 32 行比照 stage2 第 41 行。
- 第 33 行刪掉「這會被機械彙整…不得偏離…」,改成:「(c) 輸出你方的最終立場與最終引用清單,要反映你方真正站得住腳的版本,不是為了辯論效果誇大的版本。」

**`judge_question_prompt.txt`**:
- 第 16 行「(雙方陳述一致或其中一方未爭執的部分)」改成:
  > (雙方都明確提出且內容一致的部分。只有一方提到不算沒有爭議;第一輪雙方互相看不到,不得寫成「未回應」「未爭執」)
- 第 20 行後加:
  > 不得把假設句或「資料未載」轉述成對方已承認。除非 `based_on` 引述該方對事實的明確陳述,`question_text` 不得使用「自承」「自認」「坦承」。

### M11. SKILL 同步

`SKILL.md`:
- 第 5 行描述:機械死穴彙整 → 機械彙整。
- 第 17 行:改成「禁止修改機械彙整結果;法官要逐條回應讓步條件,可以不同意」。
- 第 65–73 行 Step 6、7:Step 6 同時跑 `finalize` 與 `finalize --for-judge`;法官只拿後者;拿掉「不得違背」「受錨點約束」。落地 `verdict` 用前者。
- 第 97 行共同紀律 1 與 9A 第 2 點:起訴狀素材只用原告自己的請求與依據,不放對被告的反駁、不寫被告主張,不寫 Stage、輪次等流程用語;移除「本段直接取自 Stage3」這類說明。9B 維持直接套用。
- 第 150–151 行:改成「雙方讓步條件」「引用清單差異(不代表立場變化)」。

完成後把 `main.py:35` 改成 `v1.1-2026-11-02`。

### 第二批實跑

用 UI 或 `claude -p` 跑**一件全新的商工解散案**,統編 `29112102`,模型 Claude Sonnet 5.5,兩份書狀都產。11/2 額度重置後再跑。記錄下列數字,寫進 `docs/live-run-records/`,**不要把語料全文或本機路徑一起 commit**。

---

## 驗證清單

先跑基準。2026-10-31 在 `main` 實跑結果:`208 passed, 1 skipped, 8 deselected`。

```bash
python -m pytest -q -m "not network"
```

### 第一批

| ID | 項目 | 操作 | 預期 |
|---|---|---|---|
| V1 | 漏判回歸(離線) | 新增測試,用三份假頁面 mock 分頁,目標放第 3 頁 | 回 `published`,JID 正確 |
| V1a | 上限 | mock 超過頁數上限且沒有命中 | 回 `verification_failed`,不是 `not_found` |
| V1b | 異常頁面 | mock 首頁取不到 `__VIEWSTATE` | 回 `verification_failed` |
| V2 | 漏判回歸(連網,標 `network`) | `python engine/verify.py "最高法院105年度台簡上字第33號"` | `published`,`jid` 為 `TPSV,105,台簡上,33,20161026` |
| V3 | 真的不存在(連網) | `python engine/verify.py "最高法院105年度台上字第99999號"` | `not_found` |
| V4 | 示範案 | 乾淨 DB 匯入 fixture,開 `test-2026-08-09-e2e-001`,按逐條查證 | 25/25 通過;斷網時該筆顯示先前錄製結果,不冒充本次通過 |
| V5 | 白名單 | `銀行法第29條`、`民法債編施行法第10條之1`、`民事訴訟法施行法第2條` | 解析正確且 `published` |
| V5a | 不支援 | `消費者債務清理條例第3條` | `unknown_law`,不是 `unparseable` |
| V5b | 連線例外 | mock 拋 `ssl.SSLError`、`http.client.IncompleteRead` | `verification_failed`,不中斷批次 |
| V5c | 舊格式 | `民法第191條之2`、`民法第129條第1項第2款` | 行為不變 |
| V6 | 舊版條文 | `108年民法第205條`、`修正前民法第205條` | `version_unverified`,不連網 |
| V6a | 閘門 | DB 有現行 `民法第205條` 為 published,`record_verdict`、`record_pleading` 引用 `108年民法第205條` | 拒絕落地 |
| V6b | 書狀編輯 | 律師版本把現行條文改成舊版寫法 | 未放行,不能匯出 |
| V6c | 誤判 | 掃本機 98 個引用 | 0 筆標成舊版 |
| V7 | 多份文件 | 查 `最高法院114年度台上字第1945號` | `published`,`candidates` 有 2 份,畫面有提醒 |
| V8 | 字樣檢查 | 用第 M6 節的六份草稿跑 `lint_pleading` | 命中數與表格相符;SKILL 改完後新答辯狀不再因「被告未表示意見」命中 Stage |
| V8a | 不阻擋 | `main.py pleading` 用含「被告主張」的草稿 | 落地成功、exit 0、stderr 有警告 |
| V8b | 匯出 | UI 顯示警告的版本 | 仍可匯出 |
| V9 | 標示 | 打開答辯狀、匯出 `.txt`、看攻防分頁 | 三處都有模擬說明 |
| V10 | 改名 | `grep -n "立場位移\|死穴\|弱點" ui/app.js server/*.py` | 使用者會看到的文字沒有這些詞;錄製內文除外 |
| V10a | 重算比對 | 開評估分頁,看 `anchor_check` | 既有 5 案仍一致,`weak_points` 等 JSON 鍵未變 |
| V10b | 舊評估標示 | 打開 5 件評估 | 都顯示舊規則說明 |
| V11 | 全部回歸 | 離線測試全套 | 全過;數字記下來,上台要講 |
| V12 | 瀏覽器 | `python main.py serve`,切換所有分頁 | console 無錯誤;深淺色都正常 |

### 第二批

| ID | 項目 | 操作 | 預期 |
|---|---|---|---|
| V20 | 法官輸入 | `python main.py finalize --for-judge --case-id <案件>` | 不含 `position_drift`、`response_excerpt` |
| V21 | 落地相容 | 用完整 `finalize` 輸出落地 `verdict` | 成功,`anchor_check` 一致 |
| V22 | 假 Claude | `tests/test_live_run.py` | 全過 |
| V23 | 舊案不受影響 | 開 5 件錄製案 | 內容與顯示不變(除 M7、M8 的文字) |

### 第二批實跑(Claude Sonnet 5.5)

| ID | 檢查 | 判準 |
|---|---|---|
| V30 | 流程跑完 | Stage 1–3、法官訊問、評估、查證、兩份書狀全部落地 |
| V31 | 分類器 | 記錄每次中止的角色、階段、次數與是否重派成功。同角色同階段 3 次都中止就算失敗 |
| V32 | 時間與花費 | 記錄實際數字,和實跑 #4(14 分 39 秒、估 3.25 美元)對照 |
| V33 | 程序事項 | 評估仍先處理程序;未補正不寫成已解決;不編造清算人;第 249 條與 115 台抗 105 不放同一括號 |
| V34 | 評估不再服從錨點 | 全文沒有「依錨點」「不推翻」「與錨點相符」;有逐條回應讓步條件 |
| V35 | 自承類用語 | 逐句列出「自承、自認、坦承、不爭執、相互印證」,人工對照原文,記錄總數與不成立數。**不成立數必須是 0** |
| V36 | 資料未載 | 找出資料沒寫的事項,確認標「待確認」,沒有變成有或沒有 |
| V37 | 撤回 | 沒有以資料不足為理由的撤回 |
| V38 | 書狀字樣 | 原告起訴狀 `lint_pleading` 為 0;命中要逐筆說明 |
| V39 | 匯出 | 新案件用 `export-demo` 匯出後,乾淨 clone 斷網可重播 |

V35–V37 是人工判斷,單案只能看方向,不能當統計結論。

---

## 完成後的回報格式

開 PR 時附上:
1. 每個 M 項目的狀態:完成、部分完成、未做,部分完成要寫缺什麼。
2. 驗證清單每列的結果。**沒跑的寫沒跑**,不要因為相關測試通過就勾。
3. 離線與連網測試的實際輸出數字。
4. 第二批實跑的紀錄位置與 V31、V32、V35 的數字。
5. 和本文件不同的做法與理由。

## 簡報與講稿的連動

`送件/` 不在 git 裡。簡報與講稿等版本定案後再改,下表是各項完成後才能使用的講法:

| 完成項目 | 解鎖的講法 |
|---|---|
| M1、M2、V2、V4 | 示範案 25/25;可以說「漏判已修並補回歸測試」 |
| V3 | 可用不存在的字號示範閘門 |
| M4、V6 | 可以說舊版條文不會被當成已查證 |
| M8、V10 | 畫面用語改成讓步條件、引用清單差異 |
| V30–V38 | 可以說「法官評估已不受錨點方向約束」,並用新案件示範 |
| V11 | 上台講的測試數字 |

第二批沒有實跑通過時,「法官評估已不受錨點方向約束」只能講成下一版設計。
