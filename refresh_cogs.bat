@echo off
echo ============================================
echo  Forage Kitchen - COGS Dashboard Refresh
echo ============================================
echo.
echo  Usage: refresh_cogs.bat [P#]
echo  Examples: refresh_cogs.bat       (current period)
echo            refresh_cogs.bat P2    (specific period)
echo.
cd /d "%~dp0"
if "%~1"=="" (
    py cogs_dashboard.py
) else (
    py cogs_dashboard.py %1
)
echo.
echo Encrypting dashboards...
py encrypt_dashboards.py
echo.
echo Publishing to GitHub Pages...
git add cogs_dashboard.html cogs_P*_FY*.html
git commit -m "Update COGS dashboard"
git pull --rebase origin master
git push
echo.
echo Opening dashboard...
start cogs_dashboard.html
echo.
pause
