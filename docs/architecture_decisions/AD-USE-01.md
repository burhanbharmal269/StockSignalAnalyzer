# AD-USE-01: Universe Selection Engine

**Status:** Accepted — Future Implementation  
**Date:** 2026-06-14  
**Author:** Architecture Review  
**Applies to:** Pre-Signal-Engine pipeline (to be implemented before Signal Engine and OMS phases)

---

## Context

The current system targets two instruments: NIFTY and BANKNIFTY. The NSE FnO universe
contains approximately 180+ actively traded instruments at any given time. Scaling the
Signal Engine, Feature Engineering, and Strategy Framework to evaluate all 180+ instruments
on every market cycle would increase compute cost, latency, and Redis memory linearly.

A naïve approach — run every phase for every instrument — is infeasible:
- Feature Engineering for 180 instruments × every tick is prohibitively expensive.
- The Scoring Engine running 180 full evaluations per cycle adds unacceptable latency.
- The Risk Engine evaluating 180 candidates per cycle creates lock contention under the
  sequential evaluation invariant (D-1).

The Universe Selection Engine solves this by filtering the full NSE FnO universe down to
the **top N candidate instruments** before any signal-generation work begins. Only candidates
that pass all selection filters enter Feature Engineering. The downstream pipeline (Phases
11, 12, 13) remains unchanged.

---

## Decision

Introduce a **Universe Selection Engine** as a dedicated pre-pipeline stage that sits between
Market Data ingestion and Feature Engineering. It is responsible for reducing the active
instrument set from the full FnO universe to a bounded, config-driven candidate list.

### Pipeline Position

```
Market Data
    │
    ▼
Universe Selection Engine          ← NEW (AD-USE-01)
    │  Top N candidates only
    ▼
Feature Engineering
    │
    ▼
Strategy Framework
    │
    ▼
Scoring Engine (Phase 11)          ← UNCHANGED
    │
    ▼
Confidence Engine (Phase 12)       ← UNCHANGED
    │
    ▼
Risk Engine (Phase 13)             ← UNCHANGED
    │
    ▼
OMS
```

---

## Phase Compatibility Guarantees

The following phases are **explicitly unchanged** by this architecture decision:

| Phase | Component | Impact |
|-------|-----------|--------|
| Phase 11 | Scoring Engine | None. Receives the same `ScoreContext` as today. Input volume is bounded by `max_candidates`. |
| Phase 12 | Confidence Engine | None. Receives the same `ConfidenceContext` as today. |
| Phase 13 | Risk Engine | None. `RiskRequest` schema, `RiskLimitChecker`, `PositionSizer`, `KillSwitchService`, `PortfolioMonitorService`, `DeadMansSwitchService`, `RiskEngineService` are all unchanged. The sequential evaluation lock (D-1) is not affected — candidate count is bounded. |

No existing interface, domain model, domain event, repository, or application service is
modified by the Universe Selection Engine.

---

## Universe Selection Engine Responsibilities

The engine executes eight sequential filter stages. Each stage reduces the candidate set
further. All thresholds are config-driven — no hardcoded values.

### Stage 1 — Instrument Eligibility

Filters instruments that are not eligible for trading on the current session date:

- Instrument must exist in the instrument master (loaded from NSE FnO segment).
- Instrument must not be banned (SEBI F&O ban list, sourced daily).
- Instrument must have at least one active expiry within `max_dte_days` calendar days.
- Instrument class must be in the configured allowed set (e.g., `["OPTION", "FUTURE"]`).

**Output:** Eligible instrument list (typically 150–170 of 180+).

### Stage 2 — Liquidity Filter

Ensures sufficient market depth for clean entry and exit:

- Rolling 5-day average traded value (ATV) ≥ `min_liquidity_crores` (INR crore).
- At least `min_active_strikes` strikes with non-zero OI within 10% of spot.

**Output:** Liquid instruments only.

### Stage 3 — Volume Ranking

Ranks remaining instruments by intraday volume relative to their own 20-day average:

- Computes `volume_ratio = today_volume / avg_20d_volume`.
- Instruments with `volume_ratio < min_volume_ratio` are excluded.
- Remaining instruments ranked descending by `volume_ratio`.

**Output:** Volume-ranked list with exclusions applied.

### Stage 4 — Open Interest Ranking

Ranks by OI concentration in near-the-money strikes:

- Sums OI across strikes within `atm_oi_band_pct` of current spot.
- OI must exceed `min_oi_lots` (in lots).
- Instruments ranked descending by near-ATM OI.

**Output:** OI-ranked list with minimum OI filter applied.

### Stage 5 — Spread Filter

Rejects instruments with wide bid-ask spreads that would erode edge:

- Computed as `spread_pct = (ask - bid) / mid × 100` for the ATM strike.
- Instruments with `spread_pct > max_spread_pct` are excluded.

**Output:** Tightly-spread instruments only.

### Stage 6 — IV Filter

Selects instruments in a regime where options pricing is exploitable:

- Current IV (from options chain) must satisfy `min_iv_pct ≤ IV ≤ max_iv_pct`.
- IV Rank (IVR) must satisfy `min_ivr ≤ IVR ≤ max_ivr` if configured.

**Output:** Instruments in the target IV regime.

### Stage 7 — ATR Filter

Ensures sufficient intraday movement potential for the strategy to function:

- 14-period ATR as a percentage of spot must satisfy `min_atr_pct ≤ ATR% ≤ max_atr_pct`.
- ATR is sourced from the Feature Snapshot cache (same source as the Strategy Framework).

**Output:** Instruments with suitable volatility profile.

### Stage 8 — Candidate Ranking and Cap

Produces the final ranked candidate list:

- Scores each surviving instrument using a weighted composite:
  ```
  composite_score = (
      w_volume   × normalised_volume_ratio
    + w_oi       × normalised_atm_oi
    + w_spread   × (1 − normalised_spread_pct)   # lower spread is better
    + w_atr      × normalised_atr_pct
  )
  ```
  All weights are config-driven and must sum to 1.0.
- Takes the top `max_candidates` instruments by composite score.
- Emits a `UniverseSelected` domain event containing the selected set.

**Output:** Top N candidates — bounded list forwarded to Feature Engineering.

---

## Output Contract

The Universe Selection Engine emits a single output per evaluation cycle:

```
UniverseSelected (domain event):
    selected_at: datetime
    instruments: list[SelectedInstrument]
    total_eligible: int          — instruments that passed Stage 1
    total_filtered_out: int      — instruments eliminated across Stages 2–7
    evaluation_cycle_ms: int     — wall-clock time for full selection pass

SelectedInstrument (value object):
    instrument_token: int
    underlying: str
    instrument_class: str        — "OPTION" | "FUTURE"
    expiry_date: date
    composite_score: float
    rank: int                    — 1-indexed, 1 = highest priority
    filter_metadata: dict        — stage-by-stage pass/fail record for observability
```

Only instruments in `UniverseSelected.instruments` proceed to Feature Engineering.
The list is bounded to `max_candidates` entries. Feature Engineering, Strategy Framework,
Scoring Engine, Confidence Engine, Risk Engine, and OMS never see instruments that did not
pass universe selection.

---

## Configuration Schema

```yaml
universe:
  enabled: true
  evaluation_interval_seconds: 300     # re-evaluate every 5 minutes during market hours
  max_candidates: 20

  eligibility:
    allowed_instrument_classes:
      - "OPTION"
      - "FUTURE"
    max_dte_days: 30
    exclude_banned: true

  liquidity:
    min_liquidity_crores: 50.0         # 5-day average traded value
    min_active_strikes: 5

  volume:
    min_volume_ratio: 0.5              # today / 20d avg; below this = excluded
    weight: 0.30                       # composite score weight

  oi:
    min_oi_lots: 500
    atm_oi_band_pct: 10.0             # strikes within 10% of spot
    weight: 0.30

  spread:
    max_spread_pct: 0.50              # maximum bid-ask spread as % of mid
    weight: 0.20

  iv:
    min_iv_pct: 10.0
    max_iv_pct: 80.0
    min_ivr: 20.0
    max_ivr: 90.0

  atr:
    min_atr_pct: 0.30                 # ATR as % of spot
    max_atr_pct: 5.00
    weight: 0.20
```

All numeric thresholds are configurable. The four weights (`volume`, `oi`, `spread`, `atr`)
must sum to 1.0; the engine validates this at startup.

---

## Data Sources

| Data Item | Source | Staleness Tolerance |
|-----------|--------|-------------------|
| Instrument eligibility | Instrument Master (Phase 13) | Daily refresh |
| F&O ban list | NSE website scraper (Phase 16+) | Daily before market open |
| Traded volume | Market Data feed (intraday) | 1 candle lag acceptable |
| Open interest | Market Data feed (intraday) | 1 candle lag acceptable |
| Bid-ask spread | Market Data feed (live) | Must be live; stale spread = exclusion |
| IV | Options chain snapshot (Phase 16+) | 5-minute lag acceptable |
| ATR | Feature Snapshot cache (Redis) | Same as Strategy Framework |

---

## Redis Key Usage

The Universe Selection Engine introduces two new Redis key namespaces:

| Key | Type | TTL | Description |
|-----|------|-----|-------------|
| `universe:selected` | String (JSON) | `evaluation_interval_seconds` + 60s buffer | Current selected candidate list |
| `universe:metadata:{instrument_token}` | Hash | Same as above | Per-instrument filter stage results |

All keys are written by the Universe Selection Engine only. Feature Engineering reads
`universe:selected` at the start of each evaluation cycle to obtain the active instrument
list.

---

## Failure Modes

| Failure | Behaviour |
|---------|-----------|
| Universe selection completes with 0 candidates | Log CRITICAL; do NOT forward to Feature Engineering; existing open positions continue to be managed by Risk Engine |
| Universe selection times out | Use previous cycle's cached `universe:selected` if age ≤ `stale_universe_max_age_seconds` (config); otherwise 0 candidates |
| F&O ban list unavailable | Proceed without ban filter; log WARNING |
| IV data unavailable | Skip IV filter stage; log WARNING; proceed with remaining stages |
| ATR data unavailable for an instrument | Exclude that instrument from the final set; log WARNING per instrument |

The Universe Selection Engine is **non-blocking** for the Risk Engine. The Risk Engine
evaluates signals only for instruments that have already passed universe selection in the
current cycle. If the universe is stale or empty, the Risk Engine simply receives no new
signals — it does not need to be aware of the Universe Selection Engine.

---

## Scaling Properties

| Universe Size | max_candidates | Downstream Evaluations |
|---------------|----------------|------------------------|
| 2 (current: NIFTY + BANKNIFTY) | N/A | 2 |
| 20 (config default) | 20 | ≤ 20 |
| 50 (expanded) | 50 | ≤ 50 |
| 180+ (full FnO) | 20 | ≤ 20 |

The downstream pipeline workload is bounded by `max_candidates`, **not** by the size of
the NSE FnO universe. Adding 170 new instruments increases universe selection compute cost,
but does not increase Scoring Engine, Confidence Engine, or Risk Engine workload.

---

## Implementation Order Constraint

The Universe Selection Engine **must be implemented before**:

1. Signal Engine (which requires a bounded candidate list as input)
2. OMS (which must never receive orders for instruments not in the selected universe)

The Universe Selection Engine **may be implemented after**:

1. Phase 13 (Risk Engine) — already complete
2. Phase 11 (Scoring Engine) — already complete
3. Phase 12 (Confidence Engine) — already complete

The recommended implementation slot is **between Phase 13 and the Signal Engine phase**
(Phase 21 per the development roadmap).

---

## Alternatives Considered

### Alternative 1: Filter inside the Scoring Engine

Apply eligibility and liquidity filters at the start of the Scoring Engine evaluation loop.

**Rejected:** The Scoring Engine is a domain service with no I/O. Injecting market data
reads into the Scoring Engine violates the clean architecture boundary and couples scoring
logic to data availability concerns.

### Alternative 2: Static instrument list in config

Maintain a manually-curated list of allowed instruments in `config/instruments.yaml`.

**Rejected:** Does not scale. Manual curation becomes a daily operational burden at 20+
instruments and is error-prone. The F&O ban list changes daily; a static list cannot
reflect real-time eligibility.

### Alternative 3: Filter at Market Data ingestion

Only ingest data for pre-approved instruments, never storing data for the full universe.

**Rejected:** Requires knowing the selected universe before data is available to make the
selection. Creates a circular dependency. Also prevents opportunistic instrument addition
when market conditions change intraday.

### Alternative 4: Parallel evaluation of all instruments

Run Feature Engineering and Strategy Framework for all 180+ instruments in parallel;
forward all results to Scoring Engine; Risk Engine applies position limits.

**Rejected:** The Risk Engine's sequential evaluation invariant (D-1, `asyncio.Lock`)
means 180 concurrent `evaluate()` calls queue serially. At 50ms per evaluation, a full
universe pass would take 9 seconds — far beyond acceptable pre-trade latency. The Risk
Engine is designed for bounded throughput, not for universe-level filtering.

---

## Consequences

### What this enables

- The NSE FnO universe can grow from 2 to 180+ instruments without modifying any existing
  phase (11, 12, 13).
- Scoring Engine latency remains bounded regardless of universe size.
- Risk Engine throughput is protected by `max_candidates` — sequential lock contention
  cannot grow unboundedly.
- Each filter stage produces structured metadata, enabling observability dashboards
  showing why specific instruments were excluded from a given cycle.
- `max_candidates` can be tuned at runtime via config without code changes.

### What this does not change

- The Risk Engine's 15-check evaluation pipeline.
- The Scoring Engine's 10-component scoring formula.
- The Confidence Engine's calculation logic.
- Any existing domain event, interface, or repository from Phases 11–13.
- The sequential evaluation invariant (D-1) in `RiskEngineService`.

### Known limitations

- The composite score ranking (Stage 8) is a heuristic, not a forecasted alpha signal.
  Instruments ranked 1st may not produce the best signal quality. The Scoring Engine
  handles signal quality; the Universe Selection Engine handles tradability pre-conditions.
- IV filtering depends on options chain data not available until Phase 16+. The IV filter
  stage is designed to be safely skipped when IV data is absent (logs WARNING, proceeds).
- The 5-minute re-evaluation interval means an instrument banned intraday may remain in
  the candidate list for up to 5 minutes. Mitigation: reduce
  `evaluation_interval_seconds` during high-volatility sessions.
