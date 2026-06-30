# EXPERIMENTS.md — Phase 25 Experiment Registry

This file is the human-readable record of all A/B experiments conducted on the StockSignalAnalyzer platform.
The machine-authoritative source is the `experiments` table in PostgreSQL.

## How to Use

1. **Create** via `POST /api/v1/experiments` or the Experiments UI at `/experiments`
2. **Activate** by patching status to `ACTIVE` — triggers A/B signal routing (10% treatment)
3. **Monitor** via `GET /api/v1/experiments/{id}/validation` for live statistical results
4. **Govern** via `GET /api/v1/experiments/{id}/governance` — all 7 gates must pass before deployment
5. **Conclude** by patching status to `COMPLETED` or `REJECTED` and writing a conclusion

## Governance Gates (all 7 required)

| Gate | Requirement |
|---|---|
| MIN_TRADES | ≥ 200 completed trades across control + treatment |
| WALK_FORWARD | Passing walk-forward backtest result on record |
| PAPER_VALIDATION | Passing paper trading validation on record |
| STATISTICAL_SIGNIFICANCE | p-value < 0.05 on two-proportion Z-test |
| ROLLBACK_PLAN | Rollback plan documented (>10 chars) |
| IMPACT_DOCUMENTED | Impact description in experiment record (>20 chars) |
| HUMAN_APPROVAL | Manually approved by an admin user |

## Platform Freeze Policy

**ARCHITECTURE_STATUS = FROZEN** (as of Phase 25, 2026-06-30)

No changes to the following until ≥ 500 completed trades AND all 7 governance gates pass:
- Indicators, score components, score weights
- Confidence, target, stop, position sizing logic
- Regime, option selection, signal generation logic
- Overlays, filters

---

## Experiment Log

### No experiments yet.

*Experiments will be logged here as they are created and completed.*

---

*Auto-generated header — append experiment entries below as they are concluded.*
