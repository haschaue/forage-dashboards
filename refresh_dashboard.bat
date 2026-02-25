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
echo Publishing to GitHub Pages...
copy /Y "C:\Users\ascha\OneDrive\Desktop\forage-data\daily_dashboard.html" "C:\Users\ascha\OneDrive\Desktop\forage-dashboards\daily_dashboard.html"
cd /d "C:\Users\ascha\OneDrive\Desktop\forage-dashboards"
git add daily_dashboard.html
git commit -m "Update daily dashboard"
git push
cd /d "C:\Users\ascha\OneDrive\Desktop\forage-data"
echo.
echo Opening dashboard in browser...
start "" "daily_dashboard.html"
echo.
echo Press any key to close...
pause >nul
