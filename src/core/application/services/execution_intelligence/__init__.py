"""Execution Intelligence package — Phase 23.

Provides analytics-only observability over every order execution:
  - Timeline: per-stage timestamps and durations
  - Latency: broker/exchange latency aggregations
  - Slippage: entry/exit slippage in points, pct, and rupees
  - Fill Quality: fill completeness score (0-100)
  - Retries: retry count, reason, and success tracking
  - Rejections: categorized rejection analytics
  - Broker Health: continuous API/WS health monitoring
  - Replay: full execution state for debugging
  - Alerts: informational threshold breach notifications
  - Historical: rolling stats (1D/7D/30D/90D)

All services are fail-open and never block the trading pipeline.
"""
