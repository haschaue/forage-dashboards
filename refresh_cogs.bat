@echo off
echo ============================================
echo  Forage Kitchen - COGS Dashboard Refresh
echo ============================================
echo.
cd /d "%~dp0"
"C:\Users\ascha\AppData\Local\Python\bin\python.exe" cogs_dashboard.py
echo.
echo Opening dashboard...
start cogs_dashboard.html
echo.
pause
