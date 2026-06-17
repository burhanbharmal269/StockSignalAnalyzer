# StockSignalAnalyzer -- Environment Verification Script
# Usage: .\scripts\verify_environment.ps1

$ERRORS = @()
$WARNINGS = @()

function Check {
    param([string]$Label, [bool]$Pass, [string]$Detail, [bool]$IsWarning = $false)
    $status = if ($Pass) { "PASS" } elseif ($IsWarning) { "WARN" } else { "FAIL" }
    $color  = if ($Pass) { "Green" } elseif ($IsWarning) { "Yellow" } else { "Red" }
    Write-Host "[$status] $Label" -ForegroundColor $color
    if ($Detail) { Write-Host "       $Detail" -ForegroundColor DarkGray }
    if (-not $Pass -and -not $IsWarning) { $script:ERRORS += $Label }
    if (-not $Pass -and $IsWarning)      { $script:WARNINGS += $Label }
}

Write-Host "`n=== StockSignalAnalyzer -- Environment Check ===" -ForegroundColor Cyan
Write-Host "Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n"

# Python
try {
    $pyVer = python --version 2>&1
    $pyOk  = $pyVer -match "Python 3\.(1[0-9]|[2-9][0-9])"
    Check "Python 3.10+" $pyOk "$pyVer"
} catch { Check "Python" $false "not found" }

# Node.js
try {
    $nodeVer = node --version 2>&1
    $nodeOk  = $nodeVer -match "^v(1[89]|[2-9][0-9])\."
    Check "Node.js 18+" $nodeOk "$nodeVer"
} catch { Check "Node.js" $false "not found" }

# asyncpg
try {
    $asyncpg = python -c "import asyncpg; print(asyncpg.__version__)" 2>&1
    Check "asyncpg" ($asyncpg -match "\d") "asyncpg $asyncpg"
} catch { Check "asyncpg" $false "not installed" }

# Redis (async, protocol=2)
try {
    $redisOk = python -c @"
import asyncio
from redis.asyncio import Redis
async def chk():
    r = Redis.from_url('redis://localhost:6379/0', protocol=2, decode_responses=True)
    try:
        ok = await r.ping()
        print('ok' if ok else 'fail')
    finally:
        await r.aclose()
asyncio.run(chk())
"@ 2>&1
    Check "Redis (async)" ($redisOk.Trim() -eq "ok") "localhost:6379 protocol=2"
} catch { Check "Redis" $false "connection failed" }

# PostgreSQL
try {
    $pgBin = "$env:USERPROFILE\scoop\apps\postgresql\current\bin"
    $pgVer = (& "$pgBin\psql.exe" -U postgres -t -c "SELECT version();") | Where-Object { $_ -match "PostgreSQL" }
    Check "PostgreSQL" ($null -ne $pgVer) "$pgVer"
} catch { Check "PostgreSQL" $false "not running or not installed" }

# Database tables
try {
    $pgBin  = "$env:USERPROFILE\scoop\apps\postgresql\current\bin"
    $tCount = (& "$pgBin\psql.exe" -U postgres -d trading -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';") -join "" | ForEach-Object { $_.Trim() }
    $n      = [int]$tCount
    Check "DB Tables (trading)" ($n -ge 29) "$n tables (expected 29+)"
} catch { Check "DB Tables" $false "cannot query: $_" }

# Alembic head
try {
    $pgBin   = "$env:USERPROFILE\scoop\apps\postgresql\current\bin"
    $headRev = ((& "$pgBin\psql.exe" -U postgres -d trading -t -c "SELECT version_num FROM alembic_version;") -join "").Trim()
    Check "Alembic revision" ($headRev -eq "009_fix_broker_sessions") "$headRev"
} catch { Check "Alembic" $false "cannot query: $_" }

# Backend
try {
    $resp = Invoke-WebRequest "http://localhost:8000/api/v1/health" -UseBasicParsing -TimeoutSec 3
    $data = $resp.Content | ConvertFrom-Json
    Check "Backend API" ($data.status -eq "ok") "http://localhost:8000 status=$($data.status)"
} catch { Check "Backend API" $false "not running -- start with scripts\start_backend.ps1" }

# Frontend
try {
    $resp = Invoke-WebRequest "http://localhost:3000" -UseBasicParsing -TimeoutSec 5
    Check "Frontend" ($resp.StatusCode -eq 200) "http://localhost:3000"
} catch { Check "Frontend" $false "not running -- cd frontend && npm run dev" }

# .env file
Check ".env file" (Test-Path "D:\StockSignalAnalyzer\.env") "D:\StockSignalAnalyzer\.env"

Write-Host ""
if ($ERRORS.Count -eq 0) {
    Write-Host "All required checks passed." -ForegroundColor Green
    if ($WARNINGS.Count -gt 0) {
        Write-Host "Warnings: $($WARNINGS -join ', ')" -ForegroundColor Yellow
    }
} else {
    Write-Host "FAILED checks: $($ERRORS -join ', ')" -ForegroundColor Red
    exit 1
}
