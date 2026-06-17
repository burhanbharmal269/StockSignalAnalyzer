# Startup Execution Report — Phase 3

**Date**: 2026-06-16

---

## What Starts Automatically at `uvicorn src.app:app`

### Lifespan Sequence (app.py)

```
1. load_dotenv()                          — .env → os.environ
2. FirstRunInitializer.run()              — create default admin user
3. KillSwitchService.startup_check()      — verify Redis connectivity; warn if KS active
4. [NEW] KillSwitchService.deactivate()   — auto-deactivate in PAPER mode
5. [NEW] AccountStateSeeder.seed_if_missing() — seed risk:account_state if absent
6. SessionExpiryWatcher.startup_validate() — invalidate expired Kite sessions
7. EventBus subscriptions:
   - SignalRiskApproved → PipelineEventHandler.handle_signal_risk_approved
   - OrderFilled        → PipelineEventHandler.handle_order_filled
8. BackgroundTaskRegistry.start() — launches 8 supervised asyncio tasks:
   ├── portfolio_monitor       (PortfolioMonitorService.run)
   ├── dead_mans_switch        (DeadMansSwitchService.run)
   ├── signal_expiry_worker    (SignalExpiryWorker.start)
   ├── broker_execution_monitor (2-second poll loop)
   ├── broker_reconciliation   (60-second loop)
   ├── auto_kill_switch        (AutoKillSwitchService.run)
   ├── session_expiry_watcher  (SessionExpiryWatcher.run)
   └── signal_scanner          (SignalScannerService.run) ← MAIN PIPELINE TRIGGER
9. LiveMarketFeedService.start()   — Kite WS or NSE polling fallback
10. subscribe(47 core symbols)     — NIFTY, BANKNIFTY, NIFTY50 stocks
```

### Background Task Intervals
| Task | Interval | Market Hours Only |
|------|----------|-------------------|
| `signal_scanner` | 5 minutes | ✅ (9:15–15:30 IST) |
| `broker_execution_monitor` | 2 seconds | No |
| `broker_reconciliation` | 60 seconds | No |
| `portfolio_monitor` | Self-managed | No |
| `dead_mans_switch` | Self-managed | No |
| `auto_kill_switch` | Self-managed | No |
| `session_expiry_watcher` | Self-managed | No |
| `signal_expiry_worker` | Self-managed | No |

---

## What Does NOT Start Automatically

| Service | Manual Trigger | Notes |
|---------|---------------|-------|
| `PaperTradingDaemon` | Not started anywhere | Registered in container but never added to registry |
| `MarketScannerService.scan_all()` | `GET /api/v1/opportunities/scan` | Opportunity ranking only |
| `BacktestService` | `POST /api/v1/backtest/*` | On-demand |
| `NewsAggregationService` | `GET /api/v1/news/*` | API endpoint |
| `StrategySelectorService` | `POST /api/v1/ai-insights/strategy-select` | AI-on-demand |

---

## Startup Validation Checklist

```
✅ Redis reachable        → kill switch state readable
✅ DB reachable           → UserRepository.find_by_username works
✅ Kill switch state      → logged at startup (ACTIVE/INACTIVE)
✅ Account state          → seeded if missing (NEW)
✅ Kite session           → validated / expired sessions cleared
✅ Event bus subscriptions → pipeline event handler wired
✅ Background tasks       → 8 tasks launched concurrently
✅ Live feed             → WS started (Kite) or polling (fallback)
```
