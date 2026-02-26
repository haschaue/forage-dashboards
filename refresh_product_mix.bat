@echo off
echo ============================================
echo  Forage Kitchen - Product Mix Analysis
echo ============================================
cd /d "%~dp0"
py product_mix_analysis.py %*
echo.
echo Opening dashboard...
start product_mix_analysis.html
pause
