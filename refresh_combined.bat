@echo off
echo ============================================================
echo   Forage Kitchen - Refreshing Combined Location Dashboard...
echo ============================================================
echo.
cd /d "C:\Users\ascha\OneDrive\Desktop\forage-data"
"C:\Users\ascha\AppData\Local\Python\bin\python.exe" location_dashboard.py
echo.
echo Encrypting dashboards...
"C:\Users\ascha\AppData\Local\Python\bin\python.exe" encrypt_dashboards.py
echo.
echo Publishing to GitHub Pages...
git add combined_dashboard.html combined_summary.json combined_findings.json
git commit -m "Update combined location dashboard"
git pull --rebase origin master
git push
echo.
echo Opening dashboard in browser...
start "" "combined_dashboard.html"
echo.
echo Press any key to close...
pause >nul
