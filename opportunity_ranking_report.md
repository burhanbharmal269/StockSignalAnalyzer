# Opportunity Ranking Report — Phase 9

**Date**: 2026-06-16

---

## Ranking Pipeline

```
MarketScannerService.scan_all()
    ↓ fetches candles for all F&O symbols
    ↓ runs 5 scanners per symbol:
    ├── Breakout scanner (closes > 20-bar high + volume > 1.5x)
    ├── Breakdown scanner (closes < 20-bar low + volume > 1.5x)
    ├── Momentum scanner (RSI > 60 + volume > 1.2x)
    ├── Volume spike scanner (vol_ratio > 2.0x)
    └── Gap scanner (gap > 1% on open)
    ↓
OpportunityRankingService
    ↓ gets sentiment from SentimentService (AI-based)
    ↓ computes total_score = technical_score + sentiment_score
    ↓ saves to opportunity_repository (DB)
    ↓ returns top-ranked opportunities
```

## Scoring Per Scanner

| Scanner | Score Range | Direction |
|---------|-----------|-----------|
| Breakout | 70 + vol_ratio×5 (max 100) | LONG |
| Breakdown | 65 + vol_ratio×5 (max 90) | SHORT |
| Momentum (RSI>60) | (RSI-50)×2 (max 40) | LONG |
| Volume Spike | vol_ratio×20 (max 90) | LONG or SHORT |
| Gap Up (≥1%) | gap_pct×10 (max 80) | LONG |
| Gap Down (≤-1%) | -gap_pct×10 (max 80) | SHORT |

## API Endpoints (Phase 9)
- `GET /api/v1/opportunities/` — list ranked opportunities
- `POST /api/v1/opportunities/scan` — trigger full scan
- `GET /api/v1/opportunities/{id}` — detail

## Status
- ✅ OpportunityRankingService wired in container
- ✅ MarketScannerService wired in container
- ⚠️ NOT in background task loop — manual trigger only
- ✅ 49k candles available for scanning (50 symbols × 60 days × 15m)
- ✅ Opportunities stored in DB (opportunity table)
