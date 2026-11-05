# 比賽／示範用啟動：每次都用一個全新的專用資料庫，從 demo/recorded_cases.json 匯入錄製案件。
# 不碰平常的資料庫(只有空資料庫才會自動匯入，所以不能直接用預設的)。
# 用法：雙擊專案根目錄的 demo.bat，或  powershell -File scripts/run_demo.ps1 [-Port 8178]
param([int]$Port = 8178, [string]$CaseId = "v2-2026-11-04-construction", [string]$Tab = "diagnosis")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$db = Join-Path $root "demo\demo.db"
Remove-Item $db -Force -ErrorAction SilentlyContinue
$env:LEGALDEBATE_DB_URL = "sqlite:///" + ($db -replace "\\", "/")

# 同一個 port 已有舊的伺服器就先停掉，否則瀏覽器會連到舊資料
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

$url = "http://127.0.0.1:$Port/legal_workspace_ui.html?demo=1#/$CaseId/$Tab"

# 伺服器起來後再開瀏覽器
Start-Job -ArgumentList $Port, $url -ScriptBlock {
  param($p, $u)
  for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$p/api/cases" -TimeoutSec 2 | Out-Null; Start-Process $u; return }
    catch { Start-Sleep -Seconds 1 }
  }
} | Out-Null

Write-Host "示範網址：$url"
Write-Host "關閉這個視窗即停止伺服器。"
python main.py serve --port $Port --no-browser
