# PowerShell 一键启动 Doctor Agent 前后端服务
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Doctor Agent 医疗多 Agent 系统 一键启动 (PowerShell)  " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# 1. 检查 node 与 python
$null = Get-Command python -ErrorAction Stop
$null = Get-Command node -ErrorAction Stop
$null = Get-Command npm -ErrorAction Stop

if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend\node_modules'))) {
    Write-Host "[提示] 前端依赖未安装，正在执行 npm install..." -ForegroundColor Yellow
    Set-Location -LiteralPath (Join-Path $root 'frontend')
    npm install
    Set-Location -LiteralPath $root
}

# 2. 检查 .cache 目录
$cacheDir = Join-Path $root '.cache'
if (-not (Test-Path -LiteralPath $cacheDir)) {
    New-Item -ItemType Directory -Path $cacheDir | Out-Null
}
$pidFile = Join-Path $cacheDir 'services.pids'

# 3. 启动后端
Write-Host "[1/3] 正在启动后端服务 (FastAPI / 端口 8000)..." -ForegroundColor Green
$backendProc = Start-Process -FilePath "python" -ArgumentList "-m uvicorn doctor_agent.api:app --host 127.0.0.1 --port 8000 --workers 1" -WindowStyle Hidden -PassThru

# 4. 启动前端
Write-Host "[2/3] 正在启动前端开发服务 (Vite / 端口 5173)..." -ForegroundColor Green
$frontendProc = Start-Process -FilePath "npm.cmd" -ArgumentList "run dev" -WorkingDirectory (Join-Path $root 'frontend') -WindowStyle Hidden -PassThru

# 记录 PID
"$($backendProc.Id),backend`n$($frontendProc.Id),frontend" | Set-Content -LiteralPath $pidFile -Encoding utf8

Write-Host "[3/3] 等待服务初始化就绪..." -ForegroundColor Cyan
Start-Sleep -Seconds 4

Write-Host "正在打开前端控制台..." -ForegroundColor Green
Start-Process "http://localhost:5173"

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Doctor Agent 启动完成！" -ForegroundColor Green
Write-Host "  前端地址: http://localhost:5173" -ForegroundColor White
Write-Host "  API 地址:  http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host "  停止服务请运行: .\scripts\stop.ps1 或 .\stop.bat" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Cyan
