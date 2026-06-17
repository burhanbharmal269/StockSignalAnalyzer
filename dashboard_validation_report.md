# Dashboard Validation Report — Phase 13

**Date**: 2026-06-16

---

## Page Status

| Page | Route | Data Source | Empty State | Error State | Real Data |
|------|-------|------------|-------------|-------------|----------|
| Broker | `/broker` | `GET /api/v1/broker/status` | N/A | Shows "No broker data" | ✅ |
| Signals | `/signals` | `GET /api/v1/signals/` | ✅ "No signals yet" | ✅ | ⚠️ 0 (will populate after restart) |
| Orders | `/orders` | `GET /api/v1/orders/` | ✅ "No orders" | ✅ | ⚠️ 0 |
| Positions | `/positions` | `GET /api/v1/positions/` | ✅ "No open positions" | ✅ | ⚠️ 0 |
| Analytics | `/analytics` | `GET /api/v1/analytics/` | ✅ | ✅ | ⚠️ Empty P&L |
| AI Insights | `/ai-insights` | Multiple AI endpoints | ✅ | ✅ | ✅ |
| Market | `/market` | `GET /api/v1/market/universe` | N/A | N/A | ✅ 167 symbols |
| System Health | `/health` | `GET /api/v1/health` | N/A | N/A | ✅ |

---

## Universe Page
- ✅ 167 symbols loaded
- ✅ 142 F&O stocks with sector/token/lot_size from Kite sync
- ⚠️ Some symbols missing sector (25 symbols not matched from Kite instruments)

## Broker Page (Fixed)
- ✅ Shows CONNECTED status (Kite session active)
- ✅ Authenticated user shown
- ✅ Kill switch controls working
- ✅ Trading mode switch working
- ✅ **null session bug fixed** (broker-view.tsx:216)

## Signals Page (Pending Data)
- ✅ Renders correctly when empty
- ✅ Manual scan button works (POST /api/v1/signals/scan)
- ⏳ Signals will appear after backend restart (kill switch + account state fixes applied)

## Signal Scan Results

Run `POST /api/v1/signals/scan` after restart to verify.

Expected log output:
```
signal_scanner.universe_loaded total=167 fo_stocks=142 scanning=20
signal_scanner.features symbol=RELIANCE adx=22.1 vol_ratio=1.38 ...
signal_scanner.regime symbol=RELIANCE regime=TRENDING_BULLISH strategy=DIRECTIONAL
signal_scanner.engine_start symbol=RELIANCE
scoring_engine.complete direction=LONG conviction=0.92 raw_score=41.2 adjusted_score=33.5
signal_scanner.SIGNAL_ACCEPTED symbol=RELIANCE ...
signal_scanner.cycle_summary accepted=3 rejected=17 errors=0 candidates=20
```

---

## Action Items

1. **Restart backend** → apply all config changes (ADX gate, min_score, account state seeder)
2. **Dashboard kill switch** → should show INACTIVE (auto-deactivated in paper mode)
3. **Click "Scan Signals"** → should generate signals for trending F&O stocks
4. **Paper broker** → signals approved by risk engine → orders created automatically
5. **Orders page** → should show paper orders within 30 seconds of signal generation
