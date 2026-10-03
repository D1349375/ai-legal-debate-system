# LegalDebate UI 啟動說明

## 啟動(一條指令)

```bash
pip install -r requirements.txt      # 首次:fastapi / uvicorn / httpx / sqlalchemy
python main.py serve                 # 預設 http://127.0.0.1:8000,並自動開啟瀏覽器
```

選項:`--port 8080`、`--no-browser`、`--host 0.0.0.0`(預設只綁本機)。網址列 `#/<案件ID>/<分頁>` 可直接連到某案件的某分頁
(分頁:`overview` `parties` `debate` `aggregate` `verify` `verdict` `pleading`)。

## 這個 UI 做什麼、不做什麼

| 分頁 | 性質 | 資料來源 |
|---|---|---|
| 案件總覽、攻防過程、爭點評估、訴狀骨架 | **錄製紀錄重播** | 資料庫已落地的內容。論證由 Claude Code subagent 產生後經 `main.py record` 寫入,**不是即時生成** |
| 機械彙整 | **即時執行** | 按鈕觸發後端當場呼叫 `engine/aggregate.py`(唯讀,不寫 DB) |
| 引用查證 | **即時執行** | 按鈕觸發後端當場查證(見下),通過者寫入 `citation_verifications`(同 CLI `verify`,可取消勾選) |
| 當事人查核 | **即時執行** | 依統編查經濟部商工開放資料；名稱搜尋只提供候選，須由使用者選定統編。每次查詢追加至 `party_checks`，不更動錄製論證或書狀本文 |

第一階段**不會**呼叫任何 LLM;引擎本身不含 LLM 推理。「＋建立新案件」為停用狀態(需 LLM,第二階段)。

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

`GET /api/health` · `GET /api/cases` · `GET /api/cases/{id}` · `POST /api/cases/{id}/finalize` · `POST /api/verify` · `POST /api/party-check` · `GET /api/party-search`

刻意**沒有**任何寫入論證/判決的端點。

## 測試

```bash
python -m pytest tests/ -v
```
