@echo off
rem 比賽示範用：全新資料庫 + 錄製案件，啟動後自動開 diagnosis 頁(見 scripts/run_demo.ps1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_demo.ps1" %*
pause
