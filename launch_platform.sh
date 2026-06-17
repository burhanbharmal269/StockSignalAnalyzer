#!/usr/bin/env bash
# StockSignalAnalyzer — full platform launcher (macOS / Linux)
#
# Usage:
#   ./launch_platform.sh                   # full launch
#   ./launch_platform.sh --skip-docker     # skip Docker Compose
#   ./launch_platform.sh --skip-migration  # skip Alembic migrations
#   ./launch_platform.sh --frontend-only   # only start Next.js

set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$BACKEND_DIR/frontend"
SRC_DIR="$BACKEND_DIR/src"
ENV_FILE="$BACKEND_DIR/.env"

SKIP_DOCKER=false
SKIP_MIGRATION=false
FRONTEND_ONLY=false

for arg in "$@"; do
  case $arg in
    --skip-docker)      SKIP_DOCKER=true ;;
    --skip-migration)   SKIP_MIGRATION=true ;;
    --frontend-only)    FRONTEND_ONLY=true ;;
  esac
done

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

step() { echo -e "${CYAN}[STEP]${NC} $1"; }
ok()   { echo -e "${GREEN}[OK]${NC}   $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

echo ""
echo -e "${CYAN}=====================================================${NC}"
echo -e "${CYAN}   StockSignalAnalyzer — Platform Launcher (Unix)    ${NC}"
echo -e "${CYAN}=====================================================${NC}"
echo ""

# ------------------------------------------------------------------
# 1. Pre-flight checks
# ------------------------------------------------------------------
step "Running pre-flight checks..."

[ -f "$ENV_FILE" ] || fail ".env file not found at $ENV_FILE"
ok ".env file found"

if ! $FRONTEND_ONLY; then
  command -v python3 >/dev/null 2>&1 || fail "python3 not found. Install Python 3.11+."
  ok "Python: $(python3 --version)"

  if ! $SKIP_DOCKER; then
    if ! command -v docker >/dev/null 2>&1; then
      warn "docker not found — skipping Docker Compose."
      SKIP_DOCKER=true
    else
      ok "Docker: $(docker --version)"
    fi
  fi
fi

command -v node >/dev/null 2>&1 && ok "Node: $(node --version)" || warn "node not found — frontend startup will be skipped"

# ------------------------------------------------------------------
# 2. Docker Compose
# ------------------------------------------------------------------
if ! $FRONTEND_ONLY && ! $SKIP_DOCKER; then
  step "Starting Docker Compose services..."
  cd "$BACKEND_DIR"
  docker compose up -d --remove-orphans >/dev/null 2>&1 && ok "Docker Compose services started" || warn "docker compose failed — continuing"

  step "Waiting for PostgreSQL..."
  for i in $(seq 1 15); do
    docker compose exec -T db pg_isready -U postgres >/dev/null 2>&1 && break || sleep 2
  done
  docker compose exec -T db pg_isready -U postgres >/dev/null 2>&1 && ok "PostgreSQL ready" || warn "PostgreSQL not ready after 30s"

  step "Waiting for Redis..."
  for i in $(seq 1 15); do
    [[ "$(docker compose exec -T redis redis-cli ping 2>/dev/null)" == "PONG" ]] && break || sleep 1
  done
  [[ "$(docker compose exec -T redis redis-cli ping 2>/dev/null)" == "PONG" ]] && ok "Redis ready" || warn "Redis not ready"
fi

# ------------------------------------------------------------------
# 3. Alembic migrations
# ------------------------------------------------------------------
if ! $FRONTEND_ONLY && ! $SKIP_MIGRATION; then
  step "Running Alembic migrations..."
  cd "$BACKEND_DIR"
  python3 -m alembic upgrade head && ok "Migrations applied" || warn "Migration failed — continuing"
fi

# ------------------------------------------------------------------
# 4. Validate Python imports
# ------------------------------------------------------------------
if ! $FRONTEND_ONLY; then
  step "Validating Python application imports..."
  cd "$SRC_DIR"
  python3 -c "from container import ApplicationContainer; from app import create_app; print('imports OK')" \
    && ok "Python imports validated" || fail "Python import validation failed"
fi

# ------------------------------------------------------------------
# 5. Start backend
# ------------------------------------------------------------------
if ! $FRONTEND_ONLY; then
  step "Starting FastAPI backend on http://localhost:8000 ..."
  cd "$SRC_DIR"
  python3 -m uvicorn app:create_app --factory --host 0.0.0.0 --port 8000 --reload &
  BACKEND_PID=$!
  sleep 4

  # Health check
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    ok "Backend health check passed"
  else
    warn "Backend health check failed (may still be starting)"
  fi
  ok "Backend started (PID: $BACKEND_PID)"
fi

# ------------------------------------------------------------------
# 6. Start frontend
# ------------------------------------------------------------------
if [ -d "$FRONTEND_DIR" ] && command -v node >/dev/null 2>&1; then
  step "Starting Next.js frontend on http://localhost:3000 ..."
  cd "$FRONTEND_DIR"
  [ -d "node_modules" ] || npm install
  npm run dev &
  FRONTEND_PID=$!
  sleep 3
  ok "Frontend started (PID: $FRONTEND_PID)"
else
  warn "Frontend not started (node not found or frontend directory missing)"
fi

# ------------------------------------------------------------------
# 7. Summary
# ------------------------------------------------------------------
echo ""
echo -e "${GREEN}=====================================================${NC}"
echo -e "${GREEN}   Platform is starting up!                          ${NC}"
echo -e "${GREEN}=====================================================${NC}"
echo ""
echo -e "  Backend API:  ${CYAN}http://localhost:8000${NC}"
echo -e "  API Docs:     ${CYAN}http://localhost:8000/docs${NC}"
echo -e "  Frontend:     ${CYAN}http://localhost:3000${NC}"
echo ""
echo -e "  New dashboards:"
echo -e "    ${CYAN}http://localhost:3000/market-overview${NC}  — Market breadth & sentiment"
echo -e "    ${CYAN}http://localhost:3000/opportunities${NC}    — Ranked trading opportunities"
echo -e "    ${CYAN}http://localhost:3000/option-chain${NC}     — NSE option chain & PCR"
echo -e "    ${CYAN}http://localhost:3000/backtest${NC}         — Strategy backtesting"
echo -e "    ${CYAN}http://localhost:3000/ai-insights${NC}      — AI market analysis"
echo -e "    ${CYAN}http://localhost:3000/paper-daemon${NC}     — Paper trading daemon"
echo ""
echo -e "  Press ${YELLOW}Ctrl+C${RESET} to stop background processes."
echo ""

# Wait for background processes
wait
