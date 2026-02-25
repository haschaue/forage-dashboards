@echo off
echo ============================================
echo   Forage Kitchen - Daily Labor Report
echo   Refreshing dashboard...
echo ============================================
echo.

cd /d "%~dp0"
"C:\Users\ascha\AppData\Local\Python\bin\python.exe" labor_dashboard.py

echo.
echo Opening dashboard in browser...
start "" "labor_dashboard.html"
pause
