# PowerShell 一键关闭 Doctor Agent 前后端服务
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

Write-Host "========================================================" -ForegroundColor Yellow
Write-Host "  Doctor Agent 医疗多 Agent 系统 一键停止 (PowerShell)  " -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Yellow

# 1. 尝试从 PID 记录文件终止
$pidFile = Join-Path $root '.cache\services.pids'
if (Test-Path -LiteralPath $pidFile) {
    $lines = Get-Content -LiteralPath $pidFile
    foreach ($line in $lines) {
        if ($line -match '^(\d+),(.*)$') {
            $pidToStop = [int]$matches[1]
            $role = $matches[2]
            try {
                $proc = Get-Process -Id $pidToStop -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Host "正在终止 $role 进程 (PID: $pidToStop)..." -ForegroundColor Gray
                    Stop-Process -Id $pidToStop -Force -ErrorAction SilentlyContinue
                }
            } catch {}
        }
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

# 2. 检查 8000 与 5173 端口占用，确保无遗留
$ports = @(8000, 5173)
foreach ($port in $ports) {
    try {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($conn in $conns) {
            $ownerPid = $conn.OwningProcess
            if ($ownerPid -gt 0) {
                Write-Host "清理端口 $port 占用进程 (PID: $ownerPid)..." -ForegroundColor Gray
                Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {}
}

Write-Host "========================================================" -ForegroundColor Green
Write-Host "  所有 Doctor Agent 前后端服务已完全停止！" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
