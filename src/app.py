"""FastAPI application factory.

Creates and configures the FastAPI application instance. All routers,
middleware, and startup/shutdown hooks are registered here.

Import pattern: always use create_app() — never import `app` directly.
This keeps the factory testable (each test call gets a fresh app).
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# Load .env into os.environ so EnvSecretsClient (and any other os.getenv callers)
# can read secrets that pydantic-settings would otherwise only load into config models.
from dotenv import load_dotenv as _load_dotenv
_load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env", override=False)

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from container import ApplicationContainer
from core.infrastructure.auth.first_run import FirstRunInitializer
from core.infrastructure.config.settings import AppSettings
from core.infrastructure.logging.setup import configure_logging, get_logger
from core.infrastructure.middleware.api_rate_limiter import ApiRateLimiterMiddleware
from core.infrastructure.middleware.error_handler import register_error_handlers
from core.infrastructure.middleware.request_logging import RequestLoggingMiddleware
from core.infrastructure.middleware.security_headers import SecurityHeadersMiddleware
from core.infrastructure.observability.metrics import get_metrics_output
import core.infrastructure.observability.trading_metrics  # noqa: F401 — registers metrics at import
from core.domain.events.order_events import OrderFilled
from core.domain.events.signal_events import SignalRiskApproved
from core.presentation.api.v1.routers.auth_router import router as auth_router
from core.presentation.api.v1.routers.broker_router import router as broker_router
from core.presentation.api.v1.routers.capital_allocation_router import router as capital_allocation_router
from core.presentation.api.v1.routers.effective_account_state_router import router as effective_account_state_router
from core.presentation.api.v1.routers.health import router as health_router
from core.presentation.api.v1.routers.instrument_router import router as instrument_router
from core.presentation.api.v1.routers.order_router import router as order_router
from core.presentation.api.v1.routers.portfolio_router import router as portfolio_router
from core.presentation.api.v1.routers.position_router import router as position_router
from core.presentation.api.v1.routers.regime_router import router as regime_router
from core.presentation.api.v1.routers.risk_profile_router import router as risk_profile_router
from core.presentation.api.v1.routers.signal_router import router as signal_router
from core.presentation.api.v1.routers.audit_router import router as audit_router
from core.presentation.api.v1.routers.reconciliation_router import router as reconciliation_router
from core.presentation.api.v1.routers.analytics_router import router as analytics_router
from core.presentation.api.v1.routers.trading_safety_router import router as trading_safety_router
from core.presentation.api.v1.routers.runbook_router import router as runbook_router
from core.presentation.api.v1.routers.ws_router import router as ws_router
from core.presentation.api.v1.routers.market_data_router import router as market_data_router
from core.presentation.api.v1.routers.option_chain_router import router as option_chain_router
from core.presentation.api.v1.routers.news_router import router as news_router
from core.presentation.api.v1.routers.opportunities_router import router as opportunities_router
from core.presentation.api.v1.routers.backtest_router import router as backtest_router
from core.presentation.api.v1.routers.ai_insights_router import router as ai_insights_router
from core.presentation.api.v1.routers.paper_daemon_router import router as paper_daemon_router
from core.presentation.api.v1.routers.signal_intelligence_router import router as signal_intelligence_router
from core.presentation.api.v1.routers.execution_router import router as execution_router

logger = get_logger(__name__)


def _configure_cors(app: FastAPI, settings: AppSettings) -> None:
    """Register CORS middleware.

    In development: allows all origins for local tooling convenience.
    In production: restrict to explicit allowed origins (Phase 2+).
    """
    if settings.is_development:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )


def create_app() -> FastAPI:
    """Create, configure, and return the FastAPI application.

    This is the single entry point for app construction. Tests call this
    to get a fresh application instance without side effects.
    """
    container = ApplicationContainer()
    settings: AppSettings = container.settings()

    configure_logging(
        log_level=settings.log_level.value,
        log_format=settings.log_format.value,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "application.startup",
            app_name=settings.app_name,
            version=settings.app_version,
            environment=settings.environment.value,
        )
        _app.state.container = container
        initializer = FirstRunInitializer(
            user_repository=container.user_repository(),
            password_service=container.password_service(),
        )
        await initializer.run()

        # Kill switch — startup health check (FAIL_CLOSED if Redis unreachable)
        kill_switch_service = container.kill_switch_service()
        await kill_switch_service.startup_check()

        # Always deactivate kill switch at startup. The kill switch is an emergency stop
        # only — normal execution gating is handled by ExecutionLockService.
        try:
            await kill_switch_service.deactivate(
                deactivated_by="startup_auto",
                note="Auto-deactivated at startup — use Execution Lock for order gating",
                override_loss_check=True,
            )
            logger.info("kill_switch.auto_deactivated_startup")
        except Exception:
            logger.warning("kill_switch.auto_deactivate_failed — emergency stop may be active")

        # Seed execution lock from signal config (only if Redis key absent).
        execution_lock_svc = container.execution_lock_service()
        signal_config_obj = container.signal_config()
        try:
            await execution_lock_svc.seed_on_startup(
                default_mode=signal_config_obj.execution_mode
            )
        except Exception:
            logger.warning("execution_lock.seed_failed — defaulting to MANUAL (orders blocked)")

        # Seed default account state in Redis so the Risk Engine can function
        # from the first scan cycle (before any AccountStatePoller writes live data).
        account_state_seeder = container.account_state_seeder()
        try:
            seeded = await account_state_seeder.seed_if_missing()
            if seeded:
                logger.info("account_state.seeded")
        except Exception:
            logger.warning("account_state.seed_failed — Risk Engine may reject signals")

        # Session lifecycle: validate stored Kite session on startup
        session_expiry_watcher = container.session_expiry_watcher()
        await session_expiry_watcher.startup_validate()

        # Phase 16.5: wire event subscriptions — SignalRiskApproved → OMS, OrderFilled → Position
        event_bus = container.event_bus()
        handler = container.pipeline_event_handler()
        await event_bus.subscribe(
            SignalRiskApproved,
            handler.handle_signal_risk_approved,
            consumer_group="oms.signal_risk_approved",
            consumer_name="pipeline_handler",
        )
        await event_bus.subscribe(
            OrderFilled,
            handler.handle_order_filled,
            consumer_group="oms.order_filled",
            consumer_name="pipeline_handler",
        )

        # Phase 13 + 16.5: launch supervised background tasks
        registry = container.background_task_registry()
        portfolio_monitor = container.portfolio_monitor_service()
        dead_mans_switch = container.dead_mans_switch_service()
        signal_expiry_worker = container.signal_expiry_worker()
        broker_execution_monitor = container.broker_execution_monitor_service()
        broker_reconciliation = container.broker_reconciliation_service()

        import asyncio as _asyncio

        async def _broker_exec_monitor_loop() -> None:
            """Poll paper broker for OMS order status every 2 seconds."""
            while True:
                try:
                    await broker_execution_monitor.poll_and_process(session=None)
                except Exception:
                    logger.exception("broker_execution_monitor.poll_and_process failed")
                await _asyncio.sleep(2.0)

        async def _broker_reconciliation_loop() -> None:
            """Run OMS reconciliation every 60 seconds."""
            while True:
                try:
                    await broker_reconciliation.run()
                except Exception:
                    logger.exception("broker_reconciliation.run failed")
                await _asyncio.sleep(60.0)

        auto_kill_switch = container.auto_kill_switch_service()

        signal_scanner  = container.signal_scanner_service()
        outcome_tracker = container.signal_outcome_tracker_service()

        registry.register("portfolio_monitor", portfolio_monitor.run)
        registry.register("dead_mans_switch", dead_mans_switch.run)
        registry.register("signal_expiry_worker", signal_expiry_worker.start)
        registry.register("broker_execution_monitor", _broker_exec_monitor_loop)
        registry.register("broker_reconciliation", _broker_reconciliation_loop)
        registry.register("auto_kill_switch", auto_kill_switch.run)
        registry.register("session_expiry_watcher", session_expiry_watcher.run)
        registry.register("signal_scanner", signal_scanner.run)
        registry.register("signal_outcome_tracker", outcome_tracker.run)
        await registry.start()

        # Start live market feed (Kite WS in live mode; NSE polling fallback otherwise)
        live_feed = container.live_feed_service()
        await live_feed.start()

        # Subscribe core index + NIFTY 50 symbols for live prices
        _CORE_SYMBOLS = [
            "NIFTY", "BANKNIFTY", "FINNIFTY",
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
            "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
            "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "BAJFINANCE",
            "WIPRO", "HCLTECH", "TECHM", "ULTRACEMCO",
            "TITAN", "BAJAJFINSV", "SUNPHARMA", "TATAMOTORS", "POWERGRID",
            "NTPC", "ONGC", "COALINDIA", "TATASTEEL", "JSWSTEEL",
            "M&M", "INDUSINDBK", "DIVISLAB", "CIPLA", "DRREDDY",
            "ADANIENT", "ADANIPORTS", "GRASIM", "EICHERMOT", "BPCL",
            "HEROMOTOCO", "BRITANNIA", "APOLLOHOSP", "TATACONSUM", "HINDALCO",
        ]
        await live_feed.subscribe(_CORE_SYMBOLS)
        logger.info("live_feed.startup_subscribed count=%d", len(_CORE_SYMBOLS))

        yield

        await live_feed.stop()

        await event_bus.close()
        await registry.shutdown()
        logger.info("application.shutdown", app_name=settings.app_name)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=("Institutional-grade NSE FnO trading platform. Phase 1 — Project Foundation."),
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
        debug=settings.is_debug,
    )

    from fastapi.staticfiles import StaticFiles
    from fastapi.openapi.docs import get_swagger_ui_html

    _static_dir = pathlib.Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui():
        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title=settings.app_name + " - Swagger UI",
            swagger_js_url="/static/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger-ui.css",
        )

    # Middleware registration order: last-added = outermost.
    # RequestLoggingMiddleware must be outermost so correlation IDs are
    # available in all inner layers (including route handlers and error handlers).
    _configure_cors(app, settings)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        SecurityHeadersMiddleware,
        https_only=settings.is_production,
    )
    app.add_middleware(
        ApiRateLimiterMiddleware,
        redis_client=container.redis_client(),
        requests_per_minute=120,
        enabled=True,
    )

    register_error_handlers(app, is_development=settings.is_development)

    container.wire(
        modules=[
            "core.presentation.api.v1.routers.health",
            "core.presentation.api.v1.routers.auth_router",
            "core.presentation.api.v1.routers.instrument_router",
            "core.presentation.api.v1.routers.regime_router",
            "core.presentation.api.v1.routers.risk_profile_router",
            "core.presentation.api.v1.routers.capital_allocation_router",
            "core.presentation.api.v1.routers.portfolio_router",
            "core.presentation.api.v1.routers.effective_account_state_router",
            "core.presentation.api.v1.routers.signal_router",
            "core.presentation.api.v1.routers.order_router",
            "core.presentation.api.v1.routers.position_router",
            "core.presentation.api.v1.routers.broker_router",
            "core.presentation.api.v1.routers.audit_router",
            "core.presentation.api.v1.routers.reconciliation_router",
            "core.presentation.api.v1.routers.analytics_router",
            "core.presentation.api.v1.routers.trading_safety_router",
            "core.presentation.api.v1.routers.runbook_router",
            "core.presentation.api.v1.dependencies.auth",
            "core.presentation.api.v1.dependencies.ip_allowlist",
            "core.presentation.api.v1.routers.market_data_router",
            "core.presentation.api.v1.routers.option_chain_router",
            "core.presentation.api.v1.routers.news_router",
            "core.presentation.api.v1.routers.opportunities_router",
            "core.presentation.api.v1.routers.backtest_router",
            "core.presentation.api.v1.routers.ai_insights_router",
            "core.presentation.api.v1.routers.paper_daemon_router",
            "core.presentation.api.v1.routers.signal_intelligence_router",
            "core.presentation.api.v1.routers.execution_router",
        ]
    )
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(instrument_router)
    app.include_router(regime_router)
    app.include_router(risk_profile_router)
    app.include_router(capital_allocation_router)
    app.include_router(portfolio_router)
    app.include_router(effective_account_state_router)
    app.include_router(signal_router)
    app.include_router(order_router)
    app.include_router(position_router)
    app.include_router(broker_router)
    app.include_router(audit_router)
    app.include_router(reconciliation_router)
    app.include_router(analytics_router)
    app.include_router(trading_safety_router)
    app.include_router(runbook_router)
    app.include_router(ws_router)
    app.include_router(market_data_router, prefix="/api/v1")
    app.include_router(option_chain_router, prefix="/api/v1")
    app.include_router(news_router, prefix="/api/v1")
    app.include_router(opportunities_router, prefix="/api/v1")
    app.include_router(backtest_router, prefix="/api/v1")
    app.include_router(ai_insights_router, prefix="/api/v1")
    app.include_router(paper_daemon_router, prefix="/api/v1")
    app.include_router(signal_intelligence_router)
    app.include_router(execution_router)

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint() -> Response:
        """Prometheus metrics scrape endpoint. Restrict at the network layer."""
        content, media_type = get_metrics_output()
        return Response(content=content, media_type=media_type)

    return app
