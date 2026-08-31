@echo off
echo ============================================================
echo   Forage Kitchen - Refreshing Daily Sales Dashboard...
echo ============================================================
echo.
cd /d "C:\Users\ascha\OneDrive\Desktop\forage-data"
"C:\Users\ascha\AppData\Local\Python\bin\python.exe" daily_dashboard.py
echo.
echo Emailing dashboard...
"C:\Users\ascha\AppData\Local\Python\bin\python.exe" email_dashboard.py
echo.
echo Encrypting dashboards...
"C:\Users\ascha\AppData\Local\Python\bin\python.exe" encrypt_dashboards.py
echo.
echo Publishing to GitHub Pages...
git add dashboard.html labor_dashboard.html cogs_dashboard.html cogs_P3_FY2026.html daily_dashboard.html
git commit -m "Update dashboards"
git pull --rebase origin master
git push
echo.
echo Opening dashboard in browser...
start "" "daily_dashboard.html"
echo.
echo Press any key to close...
pause >nul
