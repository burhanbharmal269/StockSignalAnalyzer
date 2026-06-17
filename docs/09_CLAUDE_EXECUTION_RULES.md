# 09_CLAUDE_EXECUTION_RULES.md

# Claude Code Execution Rules

You are building a production-grade Indian Stock Market Trading Platform focused on:

* NSE Futures & Options (Phase 1)
* Swing Trading (Phase 2)
* Long-Term Investing (Phase 3)
* Multi-Asset Support (Future)

The system must be scalable, maintainable, observable, broker-agnostic, and suitable for institutional-grade development.

---

# PRIMARY OBJECTIVE

Build a deterministic, explainable, testable, and production-ready trading platform.

The platform must:

* Generate high-quality trade recommendations
* Support multiple brokers
* Support multiple asset classes
* Support multiple strategies
* Support future AI enhancements
* Support live trading and paper trading
* Support historical backtesting

The platform must never become tightly coupled to a broker, indicator, strategy, or AI provider.

---

# ARCHITECTURE PRINCIPLES

Always follow:

* SOLID Principles
* Clean Architecture
* Domain Driven Design (DDD)
* Dependency Injection
* Repository Pattern
* Event Driven Design
* Interface Driven Design
* Open Closed Principle
* Separation of Concerns

Never violate architecture for convenience.

---

# CLEAN ARCHITECTURE RULES

Dependencies must flow inward only.

Layers:

Presentation
↓
Application
↓
Domain
↓
Infrastructure

Rules:

* Domain must not depend on Infrastructure.
* Application must not depend on Frameworks.
* Infrastructure depends on Domain.
* Controllers must be thin.
* Business logic belongs inside Application and Domain layers.

---

# DEVELOPMENT RULES

Before writing code:

1. Read all files in /docs.
2. Understand current phase.
3. Verify acceptance criteria.
4. Explain architecture decisions.
5. Only then generate code.

Never jump to future phases.

Never generate unrelated functionality.

Always complete the current phase first.

---

# FORBIDDEN PRACTICES

Never:

* Hardcode configuration values
* Hardcode API keys
* Hardcode broker names
* Hardcode strategy names
* Use magic strings
* Use magic numbers
* Use global state
* Duplicate business logic
* Access database from controllers
* Call external APIs from domain entities
* Place business logic inside routes
* Mix infrastructure with domain logic

If duplication exists, refactor immediately.

---

# CONFIGURATION RULES

Everything must come from configuration.

Use:

* .env
* Settings Service
* Configuration Classes

Examples:

Broker Selection
Database URLs
API Keys
Risk Limits
Indicator Settings
Signal Weights

Must never be hardcoded.

---

# CODING STANDARDS

Mandatory:

* Python 3.12+
* Full Type Hints
* Dataclasses or Pydantic Models
* Async First Design
* Structured Logging
* Dependency Injection
* Unit Tests
* Integration Tests

Every public method must have:

* Type hints
* Docstrings
* Error handling

---

# TESTING RULES

Every implementation must include tests.

Required:

* Unit Tests
* Integration Tests

Target Coverage:

80%+

No feature is complete without tests.

---

# DATABASE RULES

Database Technology:

* PostgreSQL
* SQLAlchemy
* Alembic

Rules:

* Repository Pattern only
* No raw queries unless justified
* Migrations required
* Entities separate from ORM models

---

# LOGGING RULES

No silent failures.

Every exception must be logged.

Log:

* Requests
* Responses
* Signals
* Orders
* Broker Calls
* Risk Rejections
* AI Responses
* Exceptions

Use structured logging.

Preferred:

* structlog

---

# OBSERVABILITY RULES

System health must be visible.

Monitor:

* API Status
* Database Status
* Redis Status
* Broker Status
* OpenAI Status
* NSE Status
* WebSocket Status

All health checks exposed via dashboard.

---

# BROKER ABSTRACTION RULES

All broker communication must occur through:

IBroker

Required Methods:

* login()
* logout()
* get_profile()
* get_positions()
* get_holdings()
* place_order()
* modify_order()
* cancel_order()
* get_orderbook()
* get_trades()
* get_ltp()
* get_option_chain()

Current Broker:

* KiteBroker

Future Brokers:

* AngelBroker
* GrowwBroker
* UpstoxBroker
* FyersBroker
* DhanBroker

Rules:

* Strategy layer must never know broker type.
* No direct Kite API calls outside Kite adapter.
* All brokers must implement the same interface.

---

# MARKET DATA RULES

Create provider abstraction.

IDataProvider

Methods:

* get_ltp()
* get_candles()
* get_option_chain()
* get_market_depth()

Current Providers:

* NSE Provider
* Kite Provider

Future Providers:

* Groww Provider
* Angel Provider

Rules:

* Normalize all incoming data.
* Store raw data separately.
* Never mix raw and processed data.

---

# SIGNAL GENERATION RULES

Direct BUY/SELL generation is forbidden.

Signal generation must follow:

Market Data
↓
Feature Engineering
↓
Market Regime
↓
Strategies
↓
Scoring Engine
↓
Confidence Engine
↓
Risk Engine
↓
Signal Engine
↓
Recommendation

Strategies contribute scores only.

Strategies never create final signals.

---

# STRATEGY RULES

Every strategy must implement:

IStrategy

Method:

evaluate()

Current Strategies:

* Momentum
* Breakout
* Trend Following
* OI Analysis
* VWAP Analysis

Future strategies must be pluggable.

No strategy may depend on another strategy.

---

# SCORING ENGINE RULES

Combine:

* Trend Score
* OI Score
* Volume Score
* IV Score
* Price Action Score
* Sentiment Score
* Market Regime Score

Output:

0-100 score

Example:

Trend = 18
OI = 17
Volume = 12
IV = 8
Price Action = 14
Sentiment = 7
Regime = 8

Total = 84

No strategy can bypass scoring.

---

# CONFIDENCE ENGINE RULES

Score and Confidence are separate.

Inputs:

* Historical Accuracy
* Win Rate
* Regime Match
* Recent Performance

Output:

Confidence %

Example:

Score = 84
Confidence = 79

---

# RISK ENGINE RULES

Most critical component.

Every signal must pass Risk Engine.

Checks:

* Position Size
* Margin
* Daily Loss
* Weekly Loss
* Drawdown
* Exposure
* Risk Reward Ratio

Risk Engine can reject signals.

No signal may bypass Risk Engine.

---

# ORDER MANAGEMENT RULES

Order Flow:

Signal
↓
Risk Engine
↓
OMS
↓
Broker
↓
Exchange

Track:

* Pending
* Filled
* Rejected
* Cancelled
* Modified

Every order event must be logged.

---

# AI USAGE RULES

AI is an assistant layer only.

Allowed:

* News Summarization
* News Sentiment Analysis
* Market Commentary
* Trade Explanation
* Trade Journal Review
* End Of Day Reports
* Market Summary

Forbidden:

* Final Trade Decision
* Position Sizing
* Risk Calculation
* Order Placement
* Stoploss Calculation
* Margin Decisions

AI must never override deterministic trading logic.

---

# FUTURE SCALABILITY RULES

Design for future support of:

* Equity
* FnO
* Commodity
* Currency
* Crypto (optional)

Use:

AssetType Enum

Examples:

* EQUITY
* FNO
* COMMODITY
* CURRENCY

Never hardcode "Option Trading" into architecture.

---

# IMPLEMENTATION RESPONSE FORMAT

Before generating code always provide:

1. Phase Being Implemented
2. Objective
3. Files To Create
4. Files To Modify
5. Architecture Decisions
6. Acceptance Criteria

Only after approval proceed with implementation.

---

# COMPLETION CRITERIA

A phase is complete only if:

* Code Compiles
* Tests Pass
* Lint Passes
* Architecture Rules Followed
* No TODO Placeholders
* Documentation Updated

Never mark work complete if any of the above are missing.
