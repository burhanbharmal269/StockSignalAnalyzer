#!/usr/bin/env pwsh
<#
.SYNOPSIS
    StockSignalAnalyzer — full platform launcher (Windows/PowerShell)

.DESCRIPTION
    Validates environment, runs Alembic migrations, starts Docker Compose services,
    waits for health checks, then launches the frontend dev server.

.PARAMETER SkipDocker
    Skip Docker Compose startup (use if services are already running).

.PARAMETER SkipMigration
    Skip Alembic migration step.

.PARAMETER FrontendOnly
    Only start the frontend dev server.
#>
param(
    [switch]$SkipDocker,
    [switch]$SkipMigration,
    [switch]$FrontendOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$BACKEND_DIR = $PSScriptRoot
$FRONTEND_DIR = Join-Path $BACKEND_DIR "frontend"
$SRC_DIR = Join-Path $BACKEND_DIR "src"
$ENV_FILE = Join-Path $BACKEND_DIR ".env"

$GREEN  = "`e[32m"
$YELLOW = "`e[33m"
$RED    = "`e[31m"
$CYAN   = "`e[36m"
$RESET  = "`e[0m"

function Write-Step($msg) { Write-Host "${CYAN}[STEP]${RESET} $msg" }
function Write-OK($msg)   { Write-Host "${GREEN}[OK]${RESET}   $msg" }
function Write-Warn($msg) { Write-Host "${YELLOW}[WARN]${RESET} $msg" }
function Write-Fail($msg) { Write-Host "${RED}[FAIL]${RESET} $msg"; exit 1 }

Write-Host ""
Write-Host "${CYAN}=====================================================${RESET}"
Write-Host "${CYAN}   StockSignalAnalyzer — Platform Launcher (Win)     ${RESET}"
Write-Host "${CYAN}=====================================================${RESET}"
Write-Host ""

# ------------------------------------------------------------------
# 1. Pre-flight checks
# ------------------------------------------------------------------
Write-Step "Running pre-flight checks..."

if (-not (Test-Path $ENV_FILE)) {
    Write-Fail ".env file not found at $ENV_FILE. Copy .env.example and fill in values."
}
Write-OK ".env file found"

if (-not $FrontendOnly) {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Fail "python not found in PATH. Please install Python 3.11+."
    }
    $pyVersion = python --version 2>&1
    Write-OK "Python: $pyVersion"

    if (-not $SkipDocker) {
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            Write-Warn "docker not found — skipping Docker Compose startup."
            $SkipDocker = $true
        } else {
            Write-OK "Docker: $(docker --version)"
        }
    }
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Warn "node not found — frontend startup will be skipped."
} else {
    Write-OK "Node: $(node --version)"
}

# ------------------------------------------------------------------
# 2. Docker Compose (PostgreSQL + Redis + TimescaleDB)
# ------------------------------------------------------------------
if (-not $FrontendOnly -and -not $SkipDocker) {
    Write-Step "Starting Docker Compose services..."
    Push-Location $BACKEND_DIR
    try {
        docker compose up -d --remove-orphans 2>&1 | Out-Null
        Write-OK "Docker Compose services started"
    } catch {
        Write-Warn "docker compose failed: $_. Continuing anyway."
    }
    Pop-Location

    # Wait for PostgreSQL
    Write-Step "Waiting for PostgreSQL..."
    $retries = 0
    do {
        Start-Sleep -Seconds 2
        $retries++
        $pgOk = docker compose exec -T db pg_isready -U postgres 2>$null
    } while ($LASTEXITCODE -ne 0 -and $retries -lt 15)

    if ($LASTEXITCODE -eq 0) {
        Write-OK "PostgreSQL is ready"
    } else {
        Write-Warn "PostgreSQL not ready after 30s — proceeding anyway"
    }

    # Wait for Redis
    Write-Step "Waiting for Redis..."
    $retries = 0
    do {
        Start-Sleep -Seconds 1
        $retries++
        $redisOk = docker compose exec -T redis redis-cli ping 2>$null
    } while ($redisOk -ne "PONG" -and $retries -lt 15)

    if ($redisOk -eq "PONG") {
        Write-OK "Redis is ready"
    } else {
        Write-Warn "Redis not ready after 15s — proceeding anyway"
    }
}

# ------------------------------------------------------------------
# 3. Alembic migrations
# ------------------------------------------------------------------
if (-not $FrontendOnly -and -not $SkipMigration) {
    Write-Step "Running Alembic migrations..."
    Push-Location $BACKEND_DIR
    try {
        python -m alembic upgrade head 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-OK "Migrations applied successfully"
        } else {
            Write-Warn "Migration returned non-zero exit code. Check alembic output above."
        }
    } catch {
        Write-Warn "Migration failed: $_. Continuing."
    }
    Pop-Location
}

# ------------------------------------------------------------------
# 4. Validate Python imports
# ------------------------------------------------------------------
if (-not $FrontendOnly) {
    Write-Step "Validating Python application imports..."
    Push-Location $SRC_DIR
    try {
        python -c "from container import ApplicationContainer; from app import create_app; print('imports OK')" 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-OK "Python imports validated"
        } else {
            Write-Fail "Python import validation failed. Check errors above."
        }
    } finally {
        Pop-Location
    }
}

# ------------------------------------------------------------------
# 5. Start backend API server
# ------------------------------------------------------------------
if (-not $FrontendOnly) {
    Write-Step "Starting FastAPI backend on http://localhost:8000 ..."
    $backendJob = Start-Job -ScriptBlock {
        param($srcDir)
        Set-Location $srcDir
        python -m uvicorn app:create_app --factory --host 0.0.0.0 --port 8000 --reload 2>&1
    } -ArgumentList $SRC_DIR

    # Give the backend a moment to start
    Start-Sleep -Seconds 4

    # Quick health check
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 5 -ErrorAction Stop
        Write-OK "Backend health: $($health.status)"
    } catch {
        Write-Warn "Backend health check failed (may still be starting): $_"
    }

    Write-OK "Backend API job started (job ID: $($backendJob.Id))"
}

# ------------------------------------------------------------------
# 6. Install frontend deps + start dev server
# ------------------------------------------------------------------
if (Test-Path $FRONTEND_DIR) {
    Write-Step "Starting Next.js frontend on http://localhost:3000 ..."
    $frontendJob = Start-Job -ScriptBlock {
        param($dir)
        Set-Location $dir
        if (-not (Test-Path "node_modules")) {
            npm install 2>&1
        }
        npm run dev 2>&1
    } -ArgumentList $FRONTEND_DIR

    Start-Sleep -Seconds 5
    Write-OK "Frontend job started (job ID: $($frontendJob.Id))"
} else {
    Write-Warn "Frontend directory not found at $FRONTEND_DIR"
}

# ------------------------------------------------------------------
# 7. Summary
# ------------------------------------------------------------------
Write-Host ""
Write-Host "${GREEN}=====================================================${RESET}"
Write-Host "${GREEN}   Platform is starting up!                          ${RESET}"
Write-Host "${GREEN}=====================================================${RESET}"
Write-Host ""
Write-Host "  Backend API:  ${CYAN}http://localhost:8000${RESET}"
Write-Host "  API Docs:     ${CYAN}http://localhost:8000/docs${RESET}"
Write-Host "  Frontend:     ${CYAN}http://localhost:3000${RESET}"
Write-Host ""
Write-Host "  New dashboards:"
Write-Host "    ${CYAN}http://localhost:3000/market-overview${RESET}  — Market breadth & sentiment"
Write-Host "    ${CYAN}http://localhost:3000/opportunities${RESET}    — Ranked trading opportunities"
Write-Host "    ${CYAN}http://localhost:3000/option-chain${RESET}     — NSE option chain & PCR"
Write-Host "    ${CYAN}http://localhost:3000/backtest${RESET}         — Strategy backtesting"
Write-Host "    ${CYAN}http://localhost:3000/ai-insights${RESET}      — AI market analysis"
Write-Host "    ${CYAN}http://localhost:3000/paper-daemon${RESET}     — Paper trading daemon"
Write-Host ""
Write-Host "  Press ${YELLOW}Ctrl+C${RESET} to stop (background jobs will keep running)."
Write-Host "  To stop all jobs: ${YELLOW}Get-Job | Stop-Job | Remove-Job${RESET}"
Write-Host ""
