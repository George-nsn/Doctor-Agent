@echo off
@chcp 65001 >nul
echo ========================================================
echo   Doctor Agent ??? Agent ?? ????
echo ========================================================
echo.

cd /d "%~dp0"

echo [1/2] ????????? (?? 8000)...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr /r ":8000 .*LISTENING"') do (
    echo ???????? PID: %%a
    taskkill /F /PID %%a >nul 2>&1
)

echo [2/2] ????????? (?? 5173)...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr /r ":5173 .*LISTENING"') do (
    echo ???????? PID: %%a
    taskkill /F /PID %%a >nul 2>&1
)

echo.
echo ========================================================
echo   ?? Doctor Agent ???????????
echo ========================================================
echo.
pause
