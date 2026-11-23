@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo ==========================================
echo  Credit Card Automation - manual run
echo  (ignores the "only on the 21st" check)
echo ==========================================
echo.

"%~dp0venv\Scripts\python.exe" "%~dp0run_monthly.py" --force

echo.
echo Done. Logs are in: %~dp0logs
echo.
pause
