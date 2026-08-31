@echo off
echo ============================================================
echo   Forage Kitchen - Refreshing SEO Dashboard...
echo ============================================================
echo.
cd /d "C:\Users\ascha\OneDrive\Desktop\forage-data"
"C:\Users\ascha\AppData\Local\Python\bin\python.exe" seo_loop.py run
echo.
echo Encrypting dashboards...
"C:\Users\ascha\AppData\Local\Python\bin\python.exe" encrypt_dashboards.py
echo.
echo Publishing to GitHub Pages...
git add seo_dashboard.html seo_summary.json seo_recommendations.json seo_history
git commit -m "Update SEO dashboard"
git pull --rebase origin master
git push
echo.
echo Opening dashboard in browser...
start "" "seo_dashboard.html"
echo.
echo Press any key to close...
pause >nul
