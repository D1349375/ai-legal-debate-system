# LegalDebate UI 啟動說明

## 啟動(一條指令)

```bash
pip install -r requirements.txt      # 首次:fastapi / uvicorn / httpx / sqlalchemy
python main.py serve                 # 預設 http://127.0.0.1:8000,並自動開啟瀏覽器
```

選項:`--port 8080`、`--no-browser`、`--host 0.0.0.0`(預設只綁本機;改綁其他位址時即時執行會停用,見下)、
`--model`(即時執行的 Claude 模型,預設 `claude-sonnet-5-5`)、`--budget-usd`(每次即時執行的花費上限,預設 15 美元)。網址列 `#/<案件ID>/<分頁>` 可直接連到某案件的某分頁
(分頁:`overview` `parties` `debate` `aggregate` `verify` `verdict` `pleading`)。

## 這個 UI 做什麼、不做什麼

| 功能/分頁 | 性質 | 資料來源 |
|---|---|---|
| 案件總覽、攻防過程、爭點評估、訴狀骨架 | **錄製紀錄重播**或**本次即時生成**,逐筆標示 | 資料庫已落地的內容。落在 UI 即時執行期間的紀錄標「⚡ 本次即時生成・執行 #N」,其餘標「⏺ 錄製紀錄」 |
| ＋ 建立新案件 | **寫入資料庫** | 使用者輸入的案由、事實、請求與雙方當事人原樣寫入;有填統編者建立後立即做商工查核 |
| 即時執行 | **即時執行(Claude Code)** | 後端在本機啟動 Claude Code 跑 legal-debate skill,見下方「即時執行」 |
| 訴狀編輯 | **另存新版本** | 律師編輯版另存一列,系統產生的原稿不動;引用重新查證,未通過者不得匯出 |
| 機械彙整 | **即時執行** | 按鈕觸發後端當場呼叫 `engine/aggregate.py`(唯讀,不寫 DB) |
| 引用查證 | **即時執行** | 按鈕觸發後端當場查證(見下),通過者寫入 `citation_verifications`(同 CLI `verify`,可取消勾選) |
| 當事人查核 | **即時執行** | 依統編查經濟部商工開放資料；名稱搜尋只提供候選，須由使用者選定統編。每次查詢追加至 `party_checks`，不更動錄製論證或書狀本文 |

引擎本身不含 LLM 推理。LLM 只在使用者按下「即時執行」時,由本機的 Claude Code 呼叫(僅限 Anthropic Claude 模型)。
錄製案件(含 `demo/recorded_*.json` 匯入者)照常重播,不能重跑,也不需要網路或 Claude 帳號。

## 即時執行(Claude Code)

1. 先用「＋ 建立新案件」建立案件,再到案件總覽按「開始即時執行」。只有資料庫中**還沒有任何攻防或書狀紀錄**的案件可以執行;
   落地紀錄不可覆寫,所以跑過(含失敗或取消)的案件不能重跑,請用「以此案件內容建立新案件」再建一件。
2. 後端以無互動模式啟動 Claude Code(在專案目錄執行 `claude -p "/legal-debate <案件ID> …"`),權限只開到流程需要的範圍:
   `--permission-mode dontAsk`,允許 `Bash(python main.py *)`、`Skill(legal-debate *)`、Read、Grep、Glob、Agent,
   寫檔只限 `database/live_runs/` 之下;其他工具呼叫一律自動拒絕,不會停下來等人核准。
   Bash 的實際邊界(2026-10-28 以 Claude Code 2.1.312 實測):除 `python main.py …` 外,Claude Code 內建視為唯讀的指令(如 `ls`)也會放行,
   把輸出導向 `database/live_runs/` 之下的檔案(`python main.py finalize … > database/live_runs/run-N/anchor.json`)也會放行;
   shell 迴圈(`for … do python main.py …`)、`cd` 串接會被拒。導向寫到 `database/live_runs/` 以外會不會被拒沒有實測。另加
   `--setting-sources project --strict-mcp-config`,不載入使用者層設定與 MCP 伺服器。主 agent 與 subagent 都用 `--model` 指定的模型
   (subagent 以 `CLAUDE_CODE_SUBAGENT_MODEL` 指定),每次以 `--max-budget-usd` 限制花費。
3. 同一時間只跑一件。2026-10-28 實測(Pro 訂閱帳號)一件約 11 分鐘、Claude Code 估算約 2.5 美元,
   Claude 5 小時用量額度約用掉三成;此額度與同帳號其他 Claude Code 使用共用,用完時執行會以 HTTP 429 失敗(畫面會寫明)。
   進度依「資料庫已落地的階段」計算,另顯示 Claude Code 的步驟紀錄;
   各階段落地後畫面自動更新。執行中可取消(終止整個程序樹),已落地的階段保留。
4. 結束時依 Claude Code 的結果事件與資料庫實況判定:全部落地為「執行完成」;Claude Code 回報完成但資料庫仍缺階段為「流程不完整」;
   超過花費上限、程序異常結束、逾 120 分鐘為「執行失敗」,並寫出原因(含錯誤輸出末段);後端在執行途中重啟則標為「執行中斷」。
5. 每次執行的完整原始輸出(`stream.jsonl`)、畫面上的步驟紀錄(`events.jsonl`,結束或重啟後照原序號與時間重播)與暫存檔
   存在 `database/live_runs/run-<N>/`(已列入 `.gitignore`)。subagent 在背景執行時,主 agent 會分成多輪、stream 結尾有多筆結果事件;
   花費與 token 用量取最後一筆的累計值,權限拒絕次數則逐輪加總。
6. 已知限制:`--max-budget-usd` 是 Claude Code 用戶端的估算值,可能略為超出;官方文件沒有說明訂閱(OAuth)帳號是否同樣適用。
   Windows 上透過 `taskkill /T /F` 終止程序樹。

**安全**:即時執行會在這台電腦以使用者的 Claude 帳號執行有工具權限的程式,而本服務沒有登入驗證,所以:

- 只有綁定 `127.0.0.1`/`localhost` 時才啟用。以 `--host 0.0.0.0` 啟動時即時執行整個停用(畫面會寫出原因),
  區網內其他裝置只能看重播,不能觸發。
- 建立案件、即時執行、取消、訴狀另存與重新查證等寫入端點只接受本機連線,並檢查 `Host` 與 `Origin` 標頭,
  擋下其他網站(或 DNS rebinding)透過瀏覽器對本機 API 發出的請求。

## 訴狀版本與匯出

- 「✎ 編輯為新版本」以目前版本為底稿編輯,存檔時另存一列「律師編輯版」;系統產生版(經查證閘門落地的原稿)保留不動,
  預設顯示的仍是最新的系統產生版。
- 存檔時由版本文字找出所有引用:沿用原稿且已有通過紀錄者不重查;新增或改動的引用(及原本未通過者)當場重新查證(同「引用查證」分頁的規則)。
- 系統只辨識「法規名第N條」(民法、民事訴訟法等 8 部法規)與「最高法院N年度台X字第N號」;其他看起來像引用的寫法
  (如其他法規、下級審字號)標為「無法辨識,無法查證」,不放行。
- 有任何一條未通過的版本照實標示「未放行」,**不能匯出**;網路恢復後可按「重新查證未通過的引用」。
- 匯出為 UTF-8 純文字(`.txt`),正文之後附版本、來源(本次即時生成/錄製紀錄/律師編輯)、逐條查證結果與「須經律師審核」聲明。
  系統產生版匯出的是資料庫中的原文(含畫面上隱藏的系統備註)。

## 引用查證的順序與離線行為

1. **判例**:先比對本地判決語料庫(`corpus/judgments`,司法院開放資料)→ 未命中才即時查司法院 FJUD。
2. **法條**:即時查法務部全國法規資料庫;**逾時/連線失敗時退回本地法典快取**,但結果只標示為「◐ 僅本地快取,未比對官方」,
   不算通過、不寫入 DB。
3. 即時查詢逾時預設 6 秒(可選 3/6/12 秒)。批次查證中一旦偵測到網路不通,其餘引用自動略過即時查詢,整批約 3 秒內跑完。
4. 完全離線可選「離線:只比對本地」模式,絕不連網。
5. 每一列都會分開標示:**本次結果**、**資料庫先前紀錄**、**先前錄製的即時查證(`demo/recorded_live_checks.json`)**——三者不會混為一談。
   例如離線時捏造字號「最高法院105年度台簡上字第33號」顯示為「⏱ 無法完成查證」(不是「查無」,也不放行),
   並另列 2026-09-21 實際連線 FJUD 得到的「查無」紀錄。

## 資料來源與離線重現

- 案件/論證/判決/訴狀:`database/legal_debate.db`(本機 SQLite,被 `.gitignore` 排除)。
- **資料庫是空的時**(如剛 clone),`serve` 會自動由 `demo/recorded_cases.json` 匯入錄製紀錄(保留原始時間戳)。
- 重新匯出 fixture:`python main.py export-demo`;加 `--live-checks` 會另對「DB 無 published 紀錄」的引用實際連線查證並記錄(需網路)。
- `python main.py export-demo --party-checks` 只匯出先前成功的商工實際查詢至 `demo/recorded_party_checks.json`。即時查詢完全失敗時若有同統編錄製資料，UI 會清楚標示錄製時間與「非本次即時查詢」，不冒充即時結果。
- UI 不載入任何外部資源(無 CDN、無 Web Font),離線可完整運作;字型使用系統中文字型。

## 深/淺色模式

頂欄「切換為淺色/深色模式」按鈕。預設深色;選擇存在 `localStorage`(無法儲存時照常運作、只是不記憶)。
所有顏色都是 `ui/app.css` 開頭兩個主題區塊裡的 CSS 變數;`tests/test_theme_contrast.py` 會檢查兩組色票的 WCAG AA 對比,
並禁止在主題區塊外寫死顏色。狀態(通過/查無/未放行)一律同時有圖示與文字,不單靠顏色。

## API(`/api/docs` 有互動文件)

`GET /api/health` · `GET /api/cases` · `POST /api/cases` · `GET /api/cases/{id}` · `POST /api/cases/{id}/finalize` ·
`POST /api/cases/{id}/runs` · `GET /api/runs/{run_id}` · `POST /api/runs/{run_id}/cancel` ·
`POST /api/cases/{id}/pleadings` · `POST /api/cases/{id}/pleadings/{version}/reverify` · `GET /api/cases/{id}/pleadings/{version}/export` ·
`POST /api/verify` · `POST /api/party-check` · `GET /api/party-search`

仍然**沒有**直接寫入論證/判決的端點:論證、訊問、評估與系統訴狀只會由 Claude Code 的 subagent 經 `main.py record/verdict/pleading`
落地,查證閘門照舊。

## 測試

```bash
python -m pytest -q -m "not network"
```

即時執行的測試以 `tests/fake_claude.py` 模擬 Claude Code 的 stream-json 輸出,不呼叫任何模型、不花費;真實執行(實測約 11 分鐘、估算 2.5 美元)不在自動測試範圍。
