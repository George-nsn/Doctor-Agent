@echo off
@chcp 65001 >nul
echo ========================================================
echo   Doctor Agent ??? Agent ?? ????
echo ========================================================
echo.

cd /d "%~dp0"

echo [1/3] ??????...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [??] ???? Python????? Python ???? PATH?
    pause
    exit /b 1
)

node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [??] ???? Node.js????? Node.js ???? PATH?
    pause
    exit /b 1
)

if not exist "%~dp0frontend\node_modules" (
    echo [??] ???????????? npm install...
    pushd "%~dp0frontend"
    call npm install
    popd
)

echo [2/3] ?????? (FastAPI / Uvicorn, ?? 8000)...
start "DoctorAgent-Backend" /min python -m uvicorn doctor_agent.api:app --host 127.0.0.1 --port 8000 --workers 1

echo [3/3] ?????? (Vue 3 / Vite, ?? 5173)...
start "DoctorAgent-Frontend" /D "%~dp0frontend" /min cmd /c "npm run dev"

echo.
echo ????????...
timeout /t 3 /nobreak >nul

echo ?????????...
start http://localhost:5173

echo.
echo ========================================================
echo   Doctor Agent ???????
echo   - ???????: http://localhost:5173
echo   - ?? API ??:  http://127.0.0.1:8000/docs
echo   - ?????????????? stop.bat
echo ========================================================
echo.
pause
