"""Dependency Injection container (IoC).

Wires all application dependencies. Routes and services receive
dependencies via this container — never by instantiating them directly.

Usage in FastAPI endpoints:
    from dependency_injector.wiring import inject, Provide
    from container import ApplicationContainer

    @router.get("/example")
    @inject
    async def example(
        settings: AppSettings = Depends(Provide[ApplicationContainer.settings]),
    ) -> ...:
        ...

Reference: docs/09_CLAUDE_EXECUTION_RULES.md (Dependency Injection)
"""

from dependency_injector import containers, providers
from redis.asyncio import Redis

from core.application.services.broker.broker_execution_monitor_service import (
    BrokerExecutionMonitorService,
)
from core.application.services.broker.broker_health_service import BrokerHealthService
from core.application.services.broker.broker_reconciliation_service import (
    BrokerReconciliationService,
)
from core.application.services.broker.execution_guard_service import ExecutionGuardService
from core.application.services.broker.session_expiry_watcher import SessionExpiryWatcher
from core.application.services.calibration_service import CalibrationService
from core.application.services.confidence_engine_service import ConfidenceEngineService
from core.application.services.instrument_service import InstrumentService
from core.application.services.oms.execution_monitor_service import ExecutionMonitorService
from core.application.services.oms.exit_manager_service import ExitManagerService
from core.application.services.oms.order_management_service import OrderManagementService
from core.application.services.oms.order_router_service import OrderRouterService
from core.application.services.oms.position_manager_service import PositionManagerService
from core.application.services.oms.reconciliation_service import ReconciliationService
from core.application.services.capital_allocation_service import CapitalAllocationService
from core.application.services.effective_account_state_service import EffectiveAccountStateService
from core.application.services.pipeline_event_handler import PipelineEventHandler
from core.application.services.portfolio_service import PortfolioService
from core.application.services.regime_engine_service import MarketRegimeService
from core.application.services.risk_profile_service import RiskProfileService
from core.application.services.scoring_engine_service import ScoringEngineService
from core.application.services.signal.signal_deduplication_service import (
    SignalDeduplicationService,
)
from core.application.services.signal.signal_expiration_service import SignalExpirationService
from core.application.services.signal.signal_explanation_builder import SignalExplanationBuilder
from core.application.services.signal_dedup_service import SignalDedupService
from core.application.services.signal_engine_service import SignalEngineService
from core.application.services.signal_scanner_service import SignalScannerService
from core.application.services.account_state_seeder import AccountStateSeeder
from core.application.services.expired_trade_intelligence_service import ExpiredTradeIntelligenceService
from core.application.services.experiment_service import ExperimentService
from core.application.services.change_governance_service import ChangeGovernanceService
from core.application.services.weekly_research_review_service import WeeklyResearchReviewService
from core.application.services.market_close_exit_service import MarketCloseExitService
from core.application.services.signal_expiry_worker import SignalExpiryWorker
from core.application.services.universe_filter_service import UniverseFilterService
from core.application.use_cases.instrument_lookup_use_case import InstrumentLookupUseCase
from core.application.use_cases.instrument_sync_use_case import InstrumentSyncUseCase
from core.application.use_cases.regime_evaluation_use_case import RegimeEvaluationUseCase
from core.domain.confidence.confidence_calculator import (
    ConfidenceCalculator as SignalConfidenceCalculator,
)
from core.domain.confidence.confidence_explanation_builder import (
    ConfidenceExplanationBuilder as SignalConfidenceExplanationBuilder,
)
from core.domain.regime.confidence_calculator import ConfidenceCalculator
from core.domain.regime.regime_resolver import RegimeResolver
from core.domain.regime.regime_smoother import RegimeSmoother
from core.domain.regime.trend_layer import TrendLayer
from core.domain.regime.volatility_layer import VolatilityLayer
from core.domain.scoring.score_calculator import ScoreCalculator
from core.domain.strategy.iv_analysis_component import IVAnalysisComponent
from core.domain.strategy.oi_buildup_component import OIBuildupComponent
from core.domain.strategy.option_chain_component import OptionChainComponent
from core.domain.strategy.sentiment_component import SentimentComponent
from core.domain.strategy.trend_component import TrendComponent
from core.domain.strategy.volume_component import VolumeComponent
from core.domain.strategy.vwap_component import VWAPComponent
from core.infrastructure.auth.jwt_service import JWTService
from core.infrastructure.auth.password_service import PasswordService
from core.infrastructure.auth.rate_limiter import LoginRateLimiter
from core.infrastructure.broker.broker_session_manager import BrokerSessionManager
from core.infrastructure.broker.kite_broker import KiteBroker
from core.infrastructure.broker.kite_order_router import KiteOrderRouter
from core.infrastructure.broker.paper_broker import PaperBrokerAdapter
from core.infrastructure.broker.paper_order_router import PaperOrderRouter
from core.infrastructure.broker.token_encryptor import TokenEncryptor
from core.infrastructure.cache.greeks_repository import RedisGreeksRepository
from core.infrastructure.cache.order_cache_repository import RedisOrderCacheRepository
from core.infrastructure.cache.signal_cache_repository import RedisSignalCacheRepository
from core.infrastructure.cache.universe_repository import RedisUniverseRepository
from core.infrastructure.config.oms_config import OmsConfig, load_oms_config  # noqa: F401
from core.infrastructure.config.signal_config import SignalConfig, load_signal_config  # noqa: F401
from core.infrastructure.config.universe_config import UniverseConfig, load_universe_config  # noqa: F401
from core.infrastructure.database.repositories.capital_allocation_repository import (
    SqlAlchemyCapitalAllocationRepository,
)
from core.infrastructure.database.repositories.execution_repository import (
    SqlAlchemyExecutionRepository,
)
from core.infrastructure.database.repositories.portfolio_repository import (
    SqlAlchemyPortfolioRepository,
)
from core.infrastructure.database.repositories.risk_profile_repository import (
    SqlAlchemyRiskProfileRepository,
)
from core.application.services.futures_oi_service import FuturesOIService
from core.infrastructure.config.ai_config import AIConfig
from core.infrastructure.config.broker_config import BrokerConfig
from core.infrastructure.config.futures_oi_config import FuturesOIConfig
from core.infrastructure.config.confidence_config import ConfidenceConfig, load_confidence_config
from core.infrastructure.config.database_config import DatabaseConfig
from core.infrastructure.config.redis_config import RedisConfig
from core.infrastructure.config.regime_config import RegimeConfig, load_regime_config
from core.infrastructure.config.risk_config import RiskConfig, load_risk_config
from core.infrastructure.config.scoring_config import ScoringConfig, load_scoring_config
from core.infrastructure.config.security_config import SecurityConfig
from core.infrastructure.config.settings import AppSettings
from core.infrastructure.config.strategy_config import StrategyConfig, load_strategy_config
from core.infrastructure.config.websocket_config import WebSocketConfig
from core.infrastructure.data.candle_aggregator import CandleAggregatorService
from core.infrastructure.data.expiry_calendar import ExpiryCalendar
from core.infrastructure.data.instrument_master_service import InstrumentMasterService
from core.infrastructure.data.kite_data_provider import KiteInstrumentProvider
from core.infrastructure.data.option_chain_poller import OptionChainPoller
from core.infrastructure.database.connection import (
    build_read_engine,
    build_session_factory,
    build_write_engine,
)
from core.infrastructure.database.repositories.broker_session_repository import (
    SqlAlchemyBrokerSessionRepository,
)
from core.infrastructure.database.repositories.instrument_repository import (
    SqlAlchemyInstrumentRepository,
)
from core.infrastructure.database.repositories.order_repository import SqlAlchemyOrderRepository
from core.infrastructure.database.repositories.position_repository import (
    SqlAlchemyPositionRepository,
)
from core.infrastructure.database.repositories.regime_repository import (
    SqlAlchemyRegimeRepository,
)
from core.infrastructure.database.repositories.signal_performance_repository import (
    SqlAlchemySignalPerformanceRepository,
)
from core.infrastructure.database.repositories.signal_repository import (
    SqlAlchemySignalRepository,
)
from core.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository
from core.application.services.background_task_registry import BackgroundTaskRegistry
from core.application.services.dead_mans_switch_service import DeadMansSwitchService
from core.application.services.kill_switch_service import KillSwitchService
from core.application.services.portfolio_monitor_service import PortfolioMonitorService
from core.application.services.risk_engine_service import RiskEngineService
from core.infrastructure.cache.account_state_repository import RedisAccountStateRepository
from core.infrastructure.cache.correlation_repository import RedisCorrelationRepository
from core.infrastructure.cache.margin_service import RedisMarginService
from core.infrastructure.cache.portfolio_state_repository import RedisPortfolioStateRepository
from core.infrastructure.database.repositories.kill_switch_events_repository import (
    SqlAlchemyKillSwitchEventsRepository,
)
from core.infrastructure.database.repositories.risk_decision_repository import (
    SqlAlchemyRiskDecisionRepository,
)
from core.infrastructure.cache.kill_switch_repository import RedisKillSwitchRepository  # noqa: F811
from core.infrastructure.cache.execution_lock_repository import RedisExecutionLockRepository
from core.application.services.execution_lock_service import ExecutionLockService
from core.infrastructure.events.redis_event_bus import RedisStreamEventBus
from core.infrastructure.providers.neutral_sentiment_provider import NeutralSentimentProvider
from core.infrastructure.secrets.env_secrets_client import EnvSecretsClient


class ApplicationContainer(containers.DeclarativeContainer):
    """Root IoC container for the application.

    New providers are added here as each phase is implemented.
    Never instantiate services directly in routes or handlers.
    """

    wiring_config = containers.WiringConfiguration(
        packages=[
            "core.presentation.api.v1.routers",
            "core.presentation.api.v1.dependencies",
        ]
    )

    # -------------------------------------------------------------------------
    # Phase 1 — Foundation
    # -------------------------------------------------------------------------

    settings: providers.Singleton[AppSettings] = providers.Singleton(AppSettings)

    # -------------------------------------------------------------------------
    # Phase 2 — Security & Configuration Layer
    # -------------------------------------------------------------------------

    security_config: providers.Singleton[SecurityConfig] = providers.Singleton(SecurityConfig)

    ai_config: providers.Singleton[AIConfig] = providers.Singleton(AIConfig)

    risk_config: providers.Singleton[RiskConfig] = providers.Singleton(load_risk_config)

    scoring_config: providers.Singleton[ScoringConfig] = providers.Singleton(load_scoring_config)

    secrets_client: providers.Singleton[EnvSecretsClient] = providers.Singleton(EnvSecretsClient)

    # -------------------------------------------------------------------------
    # Phase 4 — Database Layer
    # -------------------------------------------------------------------------

    database_config: providers.Singleton[DatabaseConfig] = providers.Singleton(DatabaseConfig)

    db_write_engine = providers.Singleton(
        build_write_engine,
        url=database_config.provided.database_write_url,
        pool_size=database_config.provided.database_pool_size,
        max_overflow=database_config.provided.database_max_overflow,
        pool_timeout=database_config.provided.database_pool_timeout,
    )

    db_read_engine = providers.Singleton(
        build_read_engine,
        url=database_config.provided.effective_read_url,
        pool_size=database_config.provided.database_pool_size,
        max_overflow=database_config.provided.database_max_overflow,
        pool_timeout=database_config.provided.database_pool_timeout,
    )

    db_session_factory = providers.Singleton(
        build_session_factory,
        engine=db_write_engine,
    )

    db_read_session_factory = providers.Singleton(
        build_session_factory,
        engine=db_read_engine,
    )

    # -------------------------------------------------------------------------
    # Phase 10 — Event Bus  (declared here so redis_client is available to
    # signal_repository below)
    # -------------------------------------------------------------------------

    redis_config: providers.Singleton[RedisConfig] = providers.Singleton(RedisConfig)

    redis_client = providers.Singleton(
        Redis.from_url,
        url=redis_config.provided.redis_url,
        max_connections=redis_config.provided.redis_max_connections,
        decode_responses=redis_config.provided.redis_decode_responses,
        protocol=2,  # Redis 5.x (RESP2); redis-py 5.x defaults to RESP3 which 5.x server rejects
    )

    event_bus = providers.Singleton(
        RedisStreamEventBus,
        redis=redis_client,
        source=settings.provided.app_name,
    )

    signal_repository = providers.Singleton(
        SqlAlchemySignalRepository,
        session_factory=db_session_factory,
        redis_client=redis_client,
    )

    order_repository = providers.Singleton(
        SqlAlchemyOrderRepository,
        session_factory=db_session_factory,
    )

    position_repository = providers.Singleton(
        SqlAlchemyPositionRepository,
        session_factory=db_session_factory,
    )

    instrument_repository = providers.Singleton(
        SqlAlchemyInstrumentRepository,
        session_factory=db_session_factory,
    )

    # -------------------------------------------------------------------------
    # Phase 12 — WebSocket Manager
    # -------------------------------------------------------------------------

    websocket_config: providers.Singleton[WebSocketConfig] = providers.Singleton(WebSocketConfig)

    # KiteWebSocketManager requires a live broker access_token, which is only
    # available after Phase 8 (Broker Abstraction) broker login flow.
    # Wired in Phase 8 using the ISecretsClient + broker session token.

    # -------------------------------------------------------------------------
    # Phase 6 — Authentication & Authorization
    # -------------------------------------------------------------------------

    user_repository = providers.Singleton(
        SqlAlchemyUserRepository,
        session_factory=db_session_factory,
    )

    password_service: providers.Singleton[PasswordService] = providers.Singleton(PasswordService)

    jwt_service: providers.Singleton[JWTService] = providers.Singleton(
        JWTService,
        config=security_config,
        redis_client=redis_client,
    )

    rate_limiter: providers.Singleton[LoginRateLimiter] = providers.Singleton(
        LoginRateLimiter,
        redis_client=redis_client,
        max_attempts=security_config.provided.max_login_attempts,
        attempt_window_seconds=security_config.provided.login_attempt_window_seconds,
        lockout_seconds=security_config.provided.lockout_duration_seconds,
    )

    # -------------------------------------------------------------------------
    # Phase 7 — Instrument Master & Market Data
    # -------------------------------------------------------------------------

    expiry_calendar: providers.Singleton[ExpiryCalendar] = providers.Singleton(
        ExpiryCalendar,
    )

    kite_instrument_provider: providers.Singleton[KiteInstrumentProvider] = providers.Singleton(
        KiteInstrumentProvider,
    )

    instrument_master_service: providers.Singleton[InstrumentMasterService] = providers.Singleton(
        InstrumentMasterService,
        data_provider=kite_instrument_provider,
        instrument_repository=instrument_repository,
        redis_client=redis_client,
        event_bus=event_bus,
        session_factory=db_session_factory,
        expiry_calendar=expiry_calendar,
    )

    instrument_sync_use_case: providers.Singleton[InstrumentSyncUseCase] = providers.Singleton(
        InstrumentSyncUseCase,
        instrument_master=instrument_master_service,
        instrument_provider=kite_instrument_provider,
        instrument_repo=instrument_repository,
        redis_client=redis_client,
        expiry_calendar=expiry_calendar,
    )

    instrument_lookup_use_case: providers.Singleton[InstrumentLookupUseCase] = providers.Singleton(
        InstrumentLookupUseCase,
        instrument_master=instrument_master_service,
        instrument_repo=instrument_repository,
        redis_client=redis_client,
    )

    instrument_service: providers.Singleton[InstrumentService] = providers.Singleton(
        InstrumentService,
        sync_use_case=instrument_sync_use_case,
        lookup_use_case=instrument_lookup_use_case,
    )

    # -------------------------------------------------------------------------
    # Phase 8 — Broker Abstraction & WebSocket Manager
    # -------------------------------------------------------------------------

    broker_config: providers.Singleton[BrokerConfig] = providers.Singleton(BrokerConfig)

    token_encryptor: providers.Singleton[TokenEncryptor] = providers.Singleton(
        TokenEncryptor,
        secrets_client=secrets_client,
        key_secret_name=broker_config.provided.broker_token_key_secret_name,
    )

    broker_session_repository = providers.Singleton(
        SqlAlchemyBrokerSessionRepository,
        session_factory=db_session_factory,
    )

    kite_broker: providers.Singleton[KiteBroker] = providers.Singleton(
        KiteBroker,
        token_encryptor=token_encryptor,
        config=broker_config,
    )

    paper_broker: providers.Singleton[PaperBrokerAdapter] = providers.Singleton(
        PaperBrokerAdapter,
    )

    candle_aggregator: providers.Singleton[CandleAggregatorService] = providers.Singleton(
        CandleAggregatorService,
        event_bus=event_bus,
        redis_client=redis_client,
    )

    option_chain_poller: providers.Singleton[OptionChainPoller] = providers.Singleton(
        OptionChainPoller,
        event_bus=event_bus,
    )

    # -------------------------------------------------------------------------
    # Phase 9 — Market Regime Engine
    # -------------------------------------------------------------------------

    regime_config: providers.Singleton[RegimeConfig] = providers.Singleton(load_regime_config)

    trend_layer: providers.Singleton[TrendLayer] = providers.Singleton(
        TrendLayer,
        config=regime_config,
    )

    volatility_layer: providers.Singleton[VolatilityLayer] = providers.Singleton(
        VolatilityLayer,
        config=regime_config,
    )

    regime_resolver: providers.Singleton[RegimeResolver] = providers.Singleton(
        RegimeResolver,
        config=regime_config,
    )

    regime_smoother: providers.Singleton[RegimeSmoother] = providers.Singleton(
        RegimeSmoother,
        config=regime_config,
    )

    confidence_calculator: providers.Singleton[ConfidenceCalculator] = providers.Singleton(
        ConfidenceCalculator,
        config=regime_config,
    )

    regime_evaluation_use_case: providers.Singleton[RegimeEvaluationUseCase] = (
        providers.Singleton(
            RegimeEvaluationUseCase,
            trend_layer=trend_layer,
            volatility_layer=volatility_layer,
            resolver=regime_resolver,
            confidence_calculator=confidence_calculator,
        )
    )

    regime_repository = providers.Singleton(
        SqlAlchemyRegimeRepository,
        session_factory=db_session_factory,
    )

    regime_engine_service: providers.Singleton[MarketRegimeService] = providers.Singleton(
        MarketRegimeService,
        evaluation_use_case=regime_evaluation_use_case,
        smoother=regime_smoother,
        regime_repository=regime_repository,
        event_bus=event_bus,
    )

    # -------------------------------------------------------------------------
    # Phase 10 — Strategy Framework
    # -------------------------------------------------------------------------

    strategy_config: providers.Singleton[StrategyConfig] = providers.Singleton(
        load_strategy_config
    )

    sentiment_provider: providers.Singleton[NeutralSentimentProvider] = providers.Singleton(
        NeutralSentimentProvider,
    )

    oi_buildup_component: providers.Singleton[OIBuildupComponent] = providers.Singleton(
        OIBuildupComponent,
        config=strategy_config,
    )

    trend_component: providers.Singleton[TrendComponent] = providers.Singleton(
        TrendComponent,
        config=strategy_config,
    )

    option_chain_component: providers.Singleton[OptionChainComponent] = providers.Singleton(
        OptionChainComponent,
        config=strategy_config,
    )

    volume_component: providers.Singleton[VolumeComponent] = providers.Singleton(
        VolumeComponent,
        config=strategy_config,
    )

    vwap_component: providers.Singleton[VWAPComponent] = providers.Singleton(
        VWAPComponent,
        config=strategy_config,
    )

    sentiment_component: providers.Singleton[SentimentComponent] = providers.Singleton(
        SentimentComponent,
        config=strategy_config,
    )

    iv_analysis_component: providers.Singleton[IVAnalysisComponent] = providers.Singleton(
        IVAnalysisComponent,
        config=strategy_config,
    )

    # -------------------------------------------------------------------------
    # Phase 11 — Scoring Engine
    # -------------------------------------------------------------------------

    score_calculator: providers.Singleton[ScoreCalculator] = providers.Singleton(
        ScoreCalculator,
        strategy_cfg=strategy_config,
        scoring_cfg=scoring_config,
    )

    scoring_engine_service: providers.Singleton[ScoringEngineService] = providers.Singleton(
        ScoringEngineService,
        oi_buildup_component=oi_buildup_component,
        trend_component=trend_component,
        option_chain_component=option_chain_component,
        volume_component=volume_component,
        vwap_component=vwap_component,
        sentiment_component=sentiment_component,
        iv_analysis_component=iv_analysis_component,
        score_calculator=score_calculator,
        event_bus=event_bus,
    )

    # -------------------------------------------------------------------------
    # Phase 12 — Confidence Engine
    # -------------------------------------------------------------------------

    confidence_config: providers.Singleton[ConfidenceConfig] = providers.Singleton(
        load_confidence_config
    )

    signal_performance_repository = providers.Singleton(
        SqlAlchemySignalPerformanceRepository,
        session_factory=db_session_factory,
    )

    signal_confidence_calculator: providers.Singleton[SignalConfidenceCalculator] = (
        providers.Singleton(
            SignalConfidenceCalculator,
            config=confidence_config,
        )
    )

    signal_confidence_explanation_builder: providers.Singleton[
        SignalConfidenceExplanationBuilder
    ] = providers.Singleton(
        SignalConfidenceExplanationBuilder,
        config=confidence_config,
    )

    confidence_engine_service: providers.Singleton[ConfidenceEngineService] = (
        providers.Singleton(
            ConfidenceEngineService,
            performance_repository=signal_performance_repository,
            redis_client=redis_client,
            config=confidence_config,
            event_bus=event_bus,
            calculator=signal_confidence_calculator,
            explanation_builder=signal_confidence_explanation_builder,
        )
    )

    signal_dedup_service: providers.Singleton[SignalDedupService] = providers.Singleton(
        SignalDedupService,
        redis_client=redis_client,
        config=confidence_config,
    )

    calibration_service: providers.Singleton[CalibrationService] = providers.Singleton(
        CalibrationService,
        session_factory=db_session_factory,
        redis_client=redis_client,
        config=confidence_config,
    )

    signal_expiry_worker: providers.Singleton[SignalExpiryWorker] = providers.Singleton(
        SignalExpiryWorker,
        session_factory=db_session_factory,
        event_bus=event_bus,
    )

    # -------------------------------------------------------------------------
    # Phase 13 — Risk Engine Application Layer
    # -------------------------------------------------------------------------

    kill_switch_repository = providers.Singleton(
        RedisKillSwitchRepository,
        redis_client=redis_client,
    )

    execution_lock_repository: providers.Singleton[RedisExecutionLockRepository] = (
        providers.Singleton(RedisExecutionLockRepository, redis_client=redis_client)
    )

    execution_lock_service: providers.Singleton[ExecutionLockService] = providers.Singleton(
        ExecutionLockService,
        repo=execution_lock_repository,
    )

    kill_switch_events_repository = providers.Singleton(
        SqlAlchemyKillSwitchEventsRepository,
        session_factory=db_session_factory,
    )

    risk_decision_repository = providers.Singleton(
        SqlAlchemyRiskDecisionRepository,
        session_factory=db_session_factory,
    )

    account_state_repository = providers.Singleton(
        RedisAccountStateRepository,
        redis_client=redis_client,
    )

    portfolio_state_repository = providers.Singleton(
        RedisPortfolioStateRepository,
        redis_client=redis_client,
    )

    correlation_repository = providers.Singleton(
        RedisCorrelationRepository,
        redis_client=redis_client,
    )

    margin_service = providers.Singleton(
        RedisMarginService,
        redis_client=redis_client,
        config=risk_config,
    )

    kill_switch_service = providers.Singleton(
        KillSwitchService,
        kill_switch_repo=kill_switch_repository,
        kill_switch_events_repo=kill_switch_events_repository,
        event_bus=event_bus,
    )

    risk_engine_service = providers.Singleton(
        RiskEngineService,
        kill_switch_repo=kill_switch_repository,
        account_state_repo=account_state_repository,
        portfolio_state_repo=portfolio_state_repository,
        correlation_repo=correlation_repository,
        margin_service=margin_service,
        signal_perf_repo=signal_performance_repository,
        risk_decision_repo=risk_decision_repository,
        event_bus=event_bus,
        redis_client=redis_client,
        config=risk_config,
    )

    portfolio_monitor_service = providers.Singleton(
        PortfolioMonitorService,
        account_state_repo=account_state_repository,
        portfolio_state_repo=portfolio_state_repository,
        kill_switch_service=kill_switch_service,
        event_bus=event_bus,
        redis_client=redis_client,
        config=risk_config,
    )

    dead_mans_switch_service = providers.Singleton(
        DeadMansSwitchService,
        kill_switch_service=kill_switch_service,
        redis_client=redis_client,
        session_factory=db_session_factory,
        config=risk_config,
    )

    background_task_registry: providers.Singleton[BackgroundTaskRegistry] = providers.Singleton(
        BackgroundTaskRegistry,
    )

    account_state_seeder: providers.Singleton[AccountStateSeeder] = providers.Singleton(
        AccountStateSeeder,
        redis_client=redis_client,
        risk_config=risk_config,
    )

    # -------------------------------------------------------------------------
    # Phase 16.5 — Universe + Signal Engine + OMS + Broker execution pipeline
    # -------------------------------------------------------------------------

    # --- Config ---------------------------------------------------------------

    signal_config: providers.Singleton[SignalConfig] = providers.Singleton(load_signal_config)

    oms_config: providers.Singleton[OmsConfig] = providers.Singleton(load_oms_config)

    universe_config: providers.Singleton[UniverseConfig] = providers.Singleton(load_universe_config)

    # --- Cache repositories ---------------------------------------------------

    signal_cache_repository = providers.Singleton(
        RedisSignalCacheRepository,
        redis=redis_client,
    )

    order_cache_repository = providers.Singleton(
        RedisOrderCacheRepository,
        redis=redis_client,
        config=oms_config,
    )

    greeks_repository = providers.Singleton(
        RedisGreeksRepository,
        redis_client=redis_client,
        tier1_ttl_seconds=risk_config.provided.greeks.max_age_seconds,
        tier2_ttl_seconds=risk_config.provided.greeks.fallback_ttl_seconds,
    )

    universe_repository = providers.Singleton(
        RedisUniverseRepository,
        redis_client=redis_client,
    )

    # --- DB repositories (Phase 16.5) ----------------------------------------

    execution_repository = providers.Singleton(
        SqlAlchemyExecutionRepository,
        session_factory=db_session_factory,
    )

    # --- Universe ---------------------------------------------------------------

    universe_filter_service = providers.Singleton(
        UniverseFilterService,
        universe_repo=universe_repository,
        event_bus=event_bus,
        config=universe_config,
    )

    # --- Signal engine --------------------------------------------------------

    signal_explanation_builder: providers.Singleton[SignalExplanationBuilder] = (
        providers.Singleton(SignalExplanationBuilder)
    )

    signal_deduplication_service: providers.Singleton[SignalDeduplicationService] = (
        providers.Singleton(
            SignalDeduplicationService,
            cache=signal_cache_repository,
            config=signal_config,
        )
    )

    signal_engine_service: providers.Singleton[SignalEngineService] = providers.Singleton(
        SignalEngineService,
        scoring_engine=scoring_engine_service,
        confidence_engine=confidence_engine_service,
        risk_engine=risk_engine_service,
        signal_repository=signal_repository,
        signal_cache=signal_cache_repository,
        event_bus=event_bus,
        explanation_builder=signal_explanation_builder,
        dedup_service=signal_deduplication_service,
        config=signal_config,
    )

    signal_expiration_service: providers.Singleton[SignalExpirationService] = providers.Singleton(
        SignalExpirationService,
        signal_repository=signal_repository,
        signal_cache=signal_cache_repository,
        event_bus=event_bus,
    )

    # --- Broker infra ---------------------------------------------------------
    # Selects paper or live broker/router based on TRADING_MODE in .env.

    paper_order_router: providers.Singleton[PaperOrderRouter] = providers.Singleton(
        PaperOrderRouter,
        broker=paper_broker,
    )

    kite_order_router: providers.Singleton[KiteOrderRouter] = providers.Singleton(
        KiteOrderRouter,
        broker=kite_broker,
        session_repository=broker_session_repository,
    )

    # Callable that extracts trading_mode string (lowercase) from BrokerConfig.
    _broker_mode = providers.Callable(
        lambda cfg: cfg.trading_mode.lower(),
        broker_config,
    )

    # Active broker and order router — resolved from TRADING_MODE at startup.
    active_broker = providers.Selector(
        _broker_mode,
        live=kite_broker,
        paper=paper_broker,
    )

    active_order_router = providers.Selector(
        _broker_mode,
        live=kite_order_router,
        paper=paper_order_router,
    )

    # Session manager always uses kite_broker — it is responsible for OAuth exchange,
    # which is Kite-specific regardless of runtime trading mode.
    broker_session_manager: providers.Singleton[BrokerSessionManager] = providers.Singleton(
        BrokerSessionManager,
        broker=kite_broker,
        session_repository=broker_session_repository,
    )

    # Health service uses kite_broker so live-mode status probes Kite;
    # paper-mode status uses session=None → only the no-auth connectivity probe runs.
    broker_health_service: providers.Singleton[BrokerHealthService] = providers.Singleton(
        BrokerHealthService,
        broker=kite_broker,
    )

    execution_guard_service: providers.Singleton[ExecutionGuardService] = providers.Singleton(
        ExecutionGuardService,
        kill_switch_repository=kill_switch_repository,
        broker=active_broker,
    )

    # --- OMS ------------------------------------------------------------------

    order_management_service: providers.Singleton[OrderManagementService] = providers.Singleton(
        OrderManagementService,
        order_repository=order_repository,
        order_cache=order_cache_repository,
        kill_switch_repository=kill_switch_repository,
        event_bus=event_bus,
        config=oms_config,
    )

    order_router_service: providers.Singleton[OrderRouterService] = providers.Singleton(
        OrderRouterService,
        order_router=active_order_router,
        order_repository=order_repository,
        event_bus=event_bus,
    )

    execution_monitor_service: providers.Singleton[ExecutionMonitorService] = providers.Singleton(
        ExecutionMonitorService,
        order_repository=order_repository,
        execution_repository=execution_repository,
        order_router=active_order_router,
        event_bus=event_bus,
    )

    position_manager_service: providers.Singleton[PositionManagerService] = providers.Singleton(
        PositionManagerService,
        position_repository=position_repository,
        event_bus=event_bus,
    )

    exit_manager_service: providers.Singleton[ExitManagerService] = providers.Singleton(
        ExitManagerService,
        order_repository=order_repository,
        position_repository=position_repository,
        order_router_service=order_router_service,
        position_manager_service=position_manager_service,
        event_bus=event_bus,
    )

    broker_execution_monitor_service: providers.Singleton[BrokerExecutionMonitorService] = (
        providers.Singleton(
            BrokerExecutionMonitorService,
            broker=active_broker,
            order_repository=order_repository,
            execution_monitor=execution_monitor_service,
        )
    )

    # Defined here (before oms_reconciliation_service) so it can be wired in.
    reconciliation_run_repository = providers.Singleton(
        __import__(
            "core.infrastructure.database.repositories.reconciliation_run_repository",
            fromlist=["SqlAlchemyReconciliationRunRepository"],
        ).SqlAlchemyReconciliationRunRepository,
        session_factory=db_session_factory,
    )

    oms_reconciliation_service: providers.Singleton[ReconciliationService] = providers.Singleton(
        ReconciliationService,
        order_repository=order_repository,
        position_repository=position_repository,
        broker=active_broker,
        kill_switch_repository=kill_switch_repository,
        event_bus=event_bus,
        execution_repository=execution_repository,
        run_repository=reconciliation_run_repository,
        broker_name=broker_config.provided.trading_mode,
    )

    broker_reconciliation_service: providers.Singleton[BrokerReconciliationService] = (
        providers.Singleton(
            BrokerReconciliationService,
            session_repository=broker_session_repository,
            oms_reconciliation_service=oms_reconciliation_service,
            session_manager=broker_session_manager,
            broker_name=broker_config.provided.trading_mode,
        )
    )

    # --- Pipeline event handler -----------------------------------------------

    portfolio_intelligence_service = providers.Singleton(
        __import__(
            "core.application.services.portfolio_intelligence_service",
            fromlist=["PortfolioIntelligenceService"],
        ).PortfolioIntelligenceService,
        session_factory=db_session_factory,
    )

    pipeline_event_handler: providers.Singleton[PipelineEventHandler] = providers.Singleton(
        PipelineEventHandler,
        order_management_service=order_management_service,
        order_router_service=order_router_service,
        order_repository=order_repository,
        position_manager_service=position_manager_service,
        exit_manager_service=exit_manager_service,
        position_repository=position_repository,
        execution_lock_service=execution_lock_service,
        portfolio_intelligence_svc=portfolio_intelligence_service,
    )

    # -------------------------------------------------------------------------
    # Phase 17 — Capital Allocation Framework
    # -------------------------------------------------------------------------

    # --- Repositories ---------------------------------------------------------

    risk_profile_repository: providers.Singleton[SqlAlchemyRiskProfileRepository] = (
        providers.Singleton(
            SqlAlchemyRiskProfileRepository,
            session_factory=db_session_factory,
        )
    )

    capital_allocation_repository: providers.Singleton[SqlAlchemyCapitalAllocationRepository] = (
        providers.Singleton(
            SqlAlchemyCapitalAllocationRepository,
            session_factory=db_session_factory,
        )
    )

    portfolio_repository: providers.Singleton[SqlAlchemyPortfolioRepository] = (
        providers.Singleton(
            SqlAlchemyPortfolioRepository,
            session_factory=db_session_factory,
        )
    )

    # --- Services -------------------------------------------------------------

    risk_profile_service: providers.Singleton[RiskProfileService] = providers.Singleton(
        RiskProfileService,
        repository=risk_profile_repository,
    )

    capital_allocation_service: providers.Singleton[CapitalAllocationService] = providers.Singleton(
        CapitalAllocationService,
        repository=capital_allocation_repository,
    )

    portfolio_service: providers.Singleton[PortfolioService] = providers.Singleton(
        PortfolioService,
        repository=portfolio_repository,
    )

    effective_account_state_service: providers.Singleton[EffectiveAccountStateService] = (
        providers.Singleton(
            EffectiveAccountStateService,
            account_state_repo=account_state_repository,
            risk_profile_repo=risk_profile_repository,
            capital_allocation_repo=capital_allocation_repository,
            portfolio_repo=portfolio_repository,
        )
    )

    # -------------------------------------------------------------------------
    # Phase 18 — Production Hardening
    # -------------------------------------------------------------------------

    broker_order_mapping_repository = providers.Singleton(
        __import__(
            "core.infrastructure.database.repositories.broker_order_mapping_repository",
            fromlist=["SqlAlchemyBrokerOrderMappingRepository"],
        ).SqlAlchemyBrokerOrderMappingRepository,
        session_factory=db_session_factory,
    )

    audit_log_repository = providers.Singleton(
        __import__(
            "core.infrastructure.database.repositories.audit_log_repository",
            fromlist=["SqlAlchemyAuditLogRepository"],
        ).SqlAlchemyAuditLogRepository,
        session_factory=db_session_factory,
    )

    audit_log_service = providers.Singleton(
        __import__(
            "core.application.services.audit_log_service",
            fromlist=["AuditLogService"],
        ).AuditLogService,
        repository=audit_log_repository,
    )

    broker_retry_service = providers.Singleton(
        __import__(
            "core.application.services.broker.broker_retry_service",
            fromlist=["BrokerRetryService"],
        ).BrokerRetryService,
        kill_switch_repository=kill_switch_repository,
    )

    broker_execution_service = providers.Singleton(
        __import__(
            "core.application.services.broker.broker_execution_service",
            fromlist=["BrokerExecutionService"],
        ).BrokerExecutionService,
        broker=active_broker,
        broker_name=_broker_mode,
        broker_retry_service=broker_retry_service,
        order_mapping_repository=broker_order_mapping_repository,
        order_repository=order_repository,
    )

    auto_kill_switch_service = providers.Singleton(
        __import__(
            "core.application.services.auto_kill_switch_service",
            fromlist=["AutoKillSwitchService"],
        ).AutoKillSwitchService,
        kill_switch_service=kill_switch_service,
        kill_switch_repository=kill_switch_repository,
        broker_health_service=broker_health_service,
        broker_execution_service=broker_execution_service,
        account_state_repository=account_state_repository,
        redis_client=redis_client,
        risk_config=risk_config,
    )

    # -------------------------------------------------------------------------
    # Phase 19 — Reconciliation Engine (persisted runs)
    # reconciliation_run_repository is defined above (before oms_reconciliation_service)
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Phase 20 — Paper Trading Validation
    # -------------------------------------------------------------------------

    paper_trading_stats_repository = providers.Singleton(
        __import__(
            "core.infrastructure.database.repositories.paper_trading_stats_repository",
            fromlist=["SqlAlchemyPaperTradingStatsRepository"],
        ).SqlAlchemyPaperTradingStatsRepository,
        session_factory=db_session_factory,
    )

    paper_trading_validation_service = providers.Singleton(
        __import__(
            "core.application.services.paper_trading_validation_service",
            fromlist=["PaperTradingValidationService"],
        ).PaperTradingValidationService,
        stats_repository=paper_trading_stats_repository,
        order_repository=order_repository,
        position_repository=position_repository,
        signal_repository=signal_repository,
    )

    # -------------------------------------------------------------------------
    # Phase 21 — Execution Analytics
    # -------------------------------------------------------------------------

    execution_analytics_repository = providers.Singleton(
        __import__(
            "core.infrastructure.database.repositories.execution_analytics_repository",
            fromlist=["SqlAlchemyExecutionAnalyticsRepository"],
        ).SqlAlchemyExecutionAnalyticsRepository,
        session_factory=db_session_factory,
    )

    execution_analytics_service = providers.Singleton(
        __import__(
            "core.application.services.execution_analytics_service",
            fromlist=["ExecutionAnalyticsService"],
        ).ExecutionAnalyticsService,
        repository=execution_analytics_repository,
    )

    # -------------------------------------------------------------------------
    # Phase 25 — Live Trading Safety Layer
    # -------------------------------------------------------------------------

    ramp_up_repository = providers.Singleton(
        __import__(
            "core.infrastructure.database.repositories.ramp_up_repository",
            fromlist=["SqlAlchemyRampUpRepository"],
        ).SqlAlchemyRampUpRepository,
        session_factory=db_session_factory,
    )

    live_trading_safety_service = providers.Singleton(
        __import__(
            "core.application.services.live_trading_safety_service",
            fromlist=["LiveTradingSafetyService"],
        ).LiveTradingSafetyService,
        ramp_up_repository=ramp_up_repository,
    )

    # -------------------------------------------------------------------------
    # Phase 28 — Market Intelligence Platform
    # -------------------------------------------------------------------------

    # --- Repositories ---------------------------------------------------------

    historical_candle_repository = providers.Singleton(
        __import__(
            "core.infrastructure.database.repositories.historical_candle_repository",
            fromlist=["SqlAlchemyHistoricalCandleRepository"],
        ).SqlAlchemyHistoricalCandleRepository,
        session_factory=db_session_factory,
    )

    market_universe_repository = providers.Singleton(
        __import__(
            "core.infrastructure.database.repositories.market_universe_repository",
            fromlist=["SqlAlchemyMarketUniverseRepository"],
        ).SqlAlchemyMarketUniverseRepository,
        session_factory=db_session_factory,
    )

    news_repository = providers.Singleton(
        __import__(
            "core.infrastructure.database.repositories.news_repository",
            fromlist=["SqlAlchemyNewsRepository"],
        ).SqlAlchemyNewsRepository,
        session_factory=db_session_factory,
    )

    opportunity_repository = providers.Singleton(
        __import__(
            "core.infrastructure.database.repositories.opportunity_repository",
            fromlist=["SqlAlchemyOpportunityRepository"],
        ).SqlAlchemyOpportunityRepository,
        session_factory=db_session_factory,
    )

    backtest_repository = providers.Singleton(
        __import__(
            "core.infrastructure.database.repositories.opportunity_repository",
            fromlist=["SqlAlchemyBacktestRepository"],
        ).SqlAlchemyBacktestRepository,
        session_factory=db_session_factory,
    )

    # --- Market data providers ------------------------------------------------

    kite_market_data_provider = providers.Singleton(
        __import__(
            "core.infrastructure.market_data.kite_market_data_provider",
            fromlist=["KiteMarketDataProvider"],
        ).KiteMarketDataProvider,
        config=broker_config,
        session_repository=broker_session_repository,
        token_encryptor=token_encryptor,
    )

    nse_fallback_provider = providers.Singleton(
        __import__(
            "core.infrastructure.market_data.nse_fallback_provider",
            fromlist=["NSEFallbackProvider"],
        ).NSEFallbackProvider,
    )

    # --- Application services -------------------------------------------------

    market_universe_service = providers.Singleton(
        __import__(
            "core.application.services.market_universe_service",
            fromlist=["MarketUniverseService"],
        ).MarketUniverseService,
        repository=market_universe_repository,
        kite_provider=kite_market_data_provider,
    )

    historical_data_service = providers.Singleton(
        __import__(
            "core.application.services.market_data.historical_data_service",
            fromlist=["HistoricalDataService"],
        ).HistoricalDataService,
        repository=historical_candle_repository,
        primary_provider=kite_market_data_provider,
        fallback_provider=nse_fallback_provider,
    )

    live_feed_service = providers.Singleton(
        __import__(
            "core.application.services.market_data.live_feed_service",  # noqa: E501
            fromlist=["LiveMarketFeedService"],
        ).LiveMarketFeedService,
        redis_client=redis_client,
        kite_provider=kite_market_data_provider,
        nse_provider=nse_fallback_provider,
        broker_config=broker_config,
        session_repository=broker_session_repository,
        token_encryptor=token_encryptor,
    )

    session_expiry_watcher: providers.Singleton[SessionExpiryWatcher] = providers.Singleton(
        SessionExpiryWatcher,
        session_repository=broker_session_repository,
        kill_switch_service=kill_switch_service,
        broker_config=broker_config,
        live_feed_service=live_feed_service,
    )

    signal_qualification_service = providers.Singleton(
        __import__(
            "core.application.services.signal_qualification_service",
            fromlist=["SignalQualificationService"],
        ).SignalQualificationService,
    )

    signal_analytics_service = providers.Singleton(
        __import__(
            "core.application.services.signal_analytics_service",
            fromlist=["SignalAnalyticsService"],
        ).SignalAnalyticsService,
        session_factory=db_session_factory,
        execution_lock_service=execution_lock_service,
        qualification_service=signal_qualification_service,
    )

    # Defined here (before signal_outcome_tracker_service) so it can be wired in.
    trade_management_service = providers.Singleton(
        __import__(
            "core.application.services.trade_management_service",
            fromlist=["TradeManagementService"],
        ).TradeManagementService,
        session_factory=db_session_factory,
    )

    signal_outcome_tracker_service = providers.Singleton(
        __import__(
            "core.application.services.signal_outcome_tracker_service",
            fromlist=["SignalOutcomeTrackerService"],
        ).SignalOutcomeTrackerService,
        analytics_svc=signal_analytics_service,
        historical_svc=historical_data_service,
        tmi_svc=trade_management_service,
    )

    strategy_performance_service = providers.Singleton(
        __import__(
            "core.application.services.strategy_performance_service",
            fromlist=["StrategyPerformanceService"],
        ).StrategyPerformanceService,
        session_factory=db_session_factory,
    )

    filter_analytics_service = providers.Singleton(
        __import__(
            "core.application.services.filter_analytics_service",
            fromlist=["FilterAnalyticsService"],
        ).FilterAnalyticsService,
        session_factory=db_session_factory,
    )

    regime_performance_service = providers.Singleton(
        __import__(
            "core.application.services.regime_performance_service",
            fromlist=["RegimePerformanceService"],
        ).RegimePerformanceService,
        session_factory=db_session_factory,
    )

    signal_leaderboard_service = providers.Singleton(
        __import__(
            "core.application.services.signal_leaderboard_service",
            fromlist=["SignalLeaderboardService"],
        ).SignalLeaderboardService,
        session_factory=db_session_factory,
    )

    optimization_insights_service = providers.Singleton(
        __import__(
            "core.application.services.optimization_insights_service",
            fromlist=["OptimizationInsightsService"],
        ).OptimizationInsightsService,
        session_factory=db_session_factory,
    )

    daily_universe_builder_service = providers.Singleton(
        __import__(
            "core.application.services.daily_universe_builder_service",
            fromlist=["DailyUniverseBuilderService"],
        ).DailyUniverseBuilderService,
        universe_svc=market_universe_service,
        historical_svc=historical_data_service,
    )

    # ── Phase 21 — Futures OI Integration ────────────────────────────────────

    futures_oi_config: providers.Singleton[FuturesOIConfig] = providers.Singleton(
        FuturesOIConfig,
    )

    futures_oi_service: providers.Singleton[FuturesOIService] = providers.Singleton(
        FuturesOIService,
        config=futures_oi_config,
    )

    # ── Phase 21.1 — OI Analytics Layer ──────────────────────────────────────

    oi_analytics_config = providers.Singleton(
        __import__(
            "core.infrastructure.config.oi_analytics_config",
            fromlist=["OIAnalyticsConfig"],
        ).OIAnalyticsConfig,
    )

    oi_history_repository = providers.Singleton(
        __import__(
            "core.infrastructure.database.repositories.oi_history_repository",
            fromlist=["OIHistoryRepository"],
        ).OIHistoryRepository,
        session_factory=db_session_factory,
    )

    oi_analytics_service = providers.Singleton(
        __import__(
            "core.application.services.oi_analytics_service",
            fromlist=["OIAnalyticsService"],
        ).OIAnalyticsService,
        config=oi_analytics_config,
        oi_history_repo=oi_history_repository,
    )

    failure_attribution_service = providers.Singleton(
        __import__(
            "core.application.services.failure_attribution_service",
            fromlist=["FailureAttributionService"],
        ).FailureAttributionService,
        session_factory=db_session_factory,
    )

    feature_registry = providers.Singleton(
        __import__(
            "core.application.services.feature_registry",
            fromlist=["FeatureRegistry"],
        ).FeatureRegistry,
    )

    option_chain_service = providers.Singleton(
        __import__(
            "core.application.services.option_chain_service",
            fromlist=["OptionChainService"],
        ).OptionChainService,
        primary_provider=kite_market_data_provider,
        fallback_provider=nse_fallback_provider,
        session_factory=db_session_factory,
        futures_oi_service=futures_oi_service,
        oi_analytics_service=oi_analytics_service,
    )

    market_breadth_service = providers.Singleton(
        __import__(
            "core.application.services.market_breadth_service",
            fromlist=["MarketBreadthService"],
        ).MarketBreadthService,
        universe_repo=market_universe_repository,
        candle_repo=historical_candle_repository,
        live_feed=live_feed_service,
        session_factory=db_session_factory,
    )

    # Phase 21.1 — Market Context Engine + Event Calendar Service
    market_context_engine = providers.Singleton(
        __import__(
            "core.application.services.market_context_engine",
            fromlist=["MarketContextEngine"],
        ).MarketContextEngine,
        session_factory=db_session_factory,
    )

    event_calendar_service = providers.Singleton(
        __import__(
            "core.application.services.event_calendar_service",
            fromlist=["EventCalendarService"],
        ).EventCalendarService,
        session_factory=db_session_factory,
    )

    overlay_pipeline = providers.Singleton(
        __import__(
            "core.application.services.overlay_pipeline",
            fromlist=["OverlayPipeline"],
        ).OverlayPipeline,
    )

    overlay_effectiveness_service = providers.Singleton(
        __import__(
            "core.application.services.overlay_effectiveness_service",
            fromlist=["OverlayEffectivenessService"],
        ).OverlayEffectivenessService,
        session_factory=db_session_factory,
    )

    # ── Phase 22 — Validation, Readiness & Evidence Framework ────────────────

    deployment_readiness_service = providers.Singleton(
        __import__(
            "core.application.services.deployment_readiness_service",
            fromlist=["DeploymentReadinessService"],
        ).DeploymentReadinessService,
        session_factory=db_session_factory,
        oi_analytics_service=oi_analytics_service,
    )

    statistical_validation_service = providers.Singleton(
        __import__(
            "core.application.services.statistical_validation_service",
            fromlist=["StatisticalValidationService"],
        ).StatisticalValidationService,
        session_factory=db_session_factory,
    )

    bug_detection_service = providers.Singleton(
        __import__(
            "core.application.services.bug_detection_service",
            fromlist=["BugDetectionService"],
        ).BugDetectionService,
        session_factory=db_session_factory,
    )

    production_drift_service = providers.Singleton(
        __import__(
            "core.application.services.production_drift_service",
            fromlist=["ProductionDriftService"],
        ).ProductionDriftService,
        session_factory=db_session_factory,
    )

    go_no_go_service = providers.Singleton(
        __import__(
            "core.application.services.go_no_go_service",
            fromlist=["GoNoGoService"],
        ).GoNoGoService,
        session_factory=db_session_factory,
    )

    validation_report_service = providers.Singleton(
        __import__(
            "core.application.services.validation_report_service",
            fromlist=["ValidationReportService"],
        ).ValidationReportService,
        deployment_readiness_service=deployment_readiness_service,
        statistical_validation_service=statistical_validation_service,
        bug_detection_service=bug_detection_service,
        production_drift_service=production_drift_service,
        go_no_go_service=go_no_go_service,
    )

    # ── Phase 23 — Research Operating Model ──────────────────────────────────

    cohort_engine_service = providers.Singleton(
        __import__(
            "core.application.services.cohort_engine_service",
            fromlist=["CohortEngineService"],
        ).CohortEngineService,
        session_factory=db_session_factory,
    )

    research_cube_service = providers.Singleton(
        __import__(
            "core.application.services.research_cube_service",
            fromlist=["ResearchCubeService"],
        ).ResearchCubeService,
        session_factory=db_session_factory,
    )

    strategy_health_service = providers.Singleton(
        __import__(
            "core.application.services.strategy_health_service",
            fromlist=["StrategyHealthService"],
        ).StrategyHealthService,
        session_factory=db_session_factory,
        deployment_readiness_service=deployment_readiness_service,
        bug_detection_service=bug_detection_service,
        go_no_go_service=go_no_go_service,
    )

    recommendation_engine_service = providers.Singleton(
        __import__(
            "core.application.services.recommendation_engine_service",
            fromlist=["RecommendationEngineService"],
        ).RecommendationEngineService,
        session_factory=db_session_factory,
        cohort_engine=cohort_engine_service,
    )

    live_validation_service = providers.Singleton(
        __import__(
            "core.application.services.live_validation_service",
            fromlist=["LiveValidationService"],
        ).LiveValidationService,
        session_factory=db_session_factory,
    )

    weekly_research_service = providers.Singleton(
        __import__(
            "core.application.services.weekly_research_service",
            fromlist=["WeeklyResearchService"],
        ).WeeklyResearchService,
        session_factory=db_session_factory,
        strategy_health_service=strategy_health_service,
        deployment_readiness_service=deployment_readiness_service,
        go_no_go_service=go_no_go_service,
        cohort_engine_service=cohort_engine_service,
        recommendation_engine_service=recommendation_engine_service,
        statistical_validation_service=statistical_validation_service,
        overlay_effectiveness_service=overlay_effectiveness_service,
        live_validation_service=live_validation_service,
    )

    scan_metrics_service = providers.Singleton(
        __import__(
            "core.application.services.scan_metrics_service",
            fromlist=["ScanMetricsService"],
        ).ScanMetricsService,
        session_factory=db_session_factory,
    )

    # ── Phase 22 services ─────────────────────────────────────────────────────
    option_chain_intelligence_worker = providers.Singleton(
        __import__(
            "core.application.services.option_chain_intelligence_worker",
            fromlist=["OptionChainIntelligenceWorker"],
        ).OptionChainIntelligenceWorker,
        option_chain_svc=option_chain_service,
        universe_svc=market_universe_service,
        redis_client=redis_client,
    )

    market_regime_snapshot_service = providers.Singleton(
        __import__(
            "core.application.services.market_regime_snapshot_service",
            fromlist=["MarketRegimeSnapshotService"],
        ).MarketRegimeSnapshotService,
        session_factory=db_session_factory,
    )

    scanner_replay_service = providers.Singleton(
        __import__(
            "core.application.services.scanner_replay_service",
            fromlist=["ScannerReplayService"],
        ).ScannerReplayService,
        session_factory=db_session_factory,
    )

    execution_readiness_service = providers.Singleton(
        __import__(
            "core.application.services.execution_readiness_service",
            fromlist=["ExecutionReadinessService"],
        ).ExecutionReadinessService,
        redis_client=redis_client,
    )

    indicator_cache_service = providers.Singleton(
        __import__(
            "core.application.services.indicator_cache_service",
            fromlist=["IndicatorCacheService"],
        ).IndicatorCacheService,
        redis_client=redis_client,
    )

    resource_monitor_service = providers.Singleton(
        __import__(
            "core.application.services.resource_monitor_service",
            fromlist=["ResourceMonitorService"],
        ).ResourceMonitorService,
        redis_client=redis_client,
        db_engine=db_write_engine,
    )
    # ─────────────────────────────────────────────────────────────────────────

    signal_scanner_service: providers.Singleton[SignalScannerService] = providers.Singleton(
        SignalScannerService,
        universe_svc=market_universe_service,
        historical_svc=historical_data_service,
        signal_engine=signal_engine_service,
        analytics_svc=signal_analytics_service,
        option_chain_svc=option_chain_service,
        signal_config=signal_config,
        market_context_engine=market_context_engine,
        event_calendar_svc=event_calendar_service,
        breadth_svc=market_breadth_service,
        execution_lock_svc=execution_lock_service,
        overlay_pipeline=overlay_pipeline,
        portfolio_svc=portfolio_intelligence_service,
        scan_metrics_svc=scan_metrics_service,
        futures_oi_svc=futures_oi_service,
        oc_intel_worker=option_chain_intelligence_worker,
        regime_snapshot_svc=market_regime_snapshot_service,
        scanner_replay_svc=scanner_replay_service,
        exec_readiness_svc=execution_readiness_service,
        indicator_cache_svc=indicator_cache_service,
    )

    expired_trade_intelligence_service: providers.Singleton[ExpiredTradeIntelligenceService] = providers.Singleton(
        ExpiredTradeIntelligenceService,
        session_factory=db_session_factory,
    )

    experiment_service: providers.Singleton[ExperimentService] = providers.Singleton(
        ExperimentService,
        session_factory=db_session_factory,
    )

    change_governance_service: providers.Singleton[ChangeGovernanceService] = providers.Singleton(
        ChangeGovernanceService,
        session_factory=db_session_factory,
    )

    weekly_research_review_service: providers.Singleton[WeeklyResearchReviewService] = providers.Singleton(
        WeeklyResearchReviewService,
        session_factory=db_session_factory,
    )

    market_close_exit_service: providers.Singleton[MarketCloseExitService] = providers.Singleton(
        MarketCloseExitService,
        session_factory=db_session_factory,
        event_bus=event_bus,
        signal_config=signal_config,
        exit_intelligence=expired_trade_intelligence_service,
    )

    option_chain_poller_service = providers.Singleton(
        __import__(
            "core.application.services.option_chain_poller_service",
            fromlist=["OptionChainPollerService"],
        ).OptionChainPollerService,
        universe_svc=market_universe_service,
        option_chain_svc=option_chain_service,
        oc_intel_worker=option_chain_intelligence_worker,
    )

    news_aggregation_service = providers.Singleton(
        __import__(
            "core.application.services.news_aggregation_service",
            fromlist=["NewsAggregationService"],
        ).NewsAggregationService,
        repository=news_repository,
    )

    sentiment_service = providers.Singleton(
        __import__(
            "core.application.services.sentiment_service",
            fromlist=["SentimentService"],
        ).SentimentService,
        session_factory=db_session_factory,
        ai_config=ai_config,
    )

    market_scanner_service = providers.Singleton(
        __import__(
            "core.application.services.market_scanner_service",
            fromlist=["MarketScannerService"],
        ).MarketScannerService,
        universe_service=market_universe_service,
        candle_repo=historical_candle_repository,
    )

    opportunity_ranking_service = providers.Singleton(
        __import__(
            "core.application.services.opportunity_ranking_service",
            fromlist=["OpportunityRankingService"],
        ).OpportunityRankingService,
        scanner=market_scanner_service,
        sentiment_service=sentiment_service,
        repository=opportunity_repository,
    )

    backtest_service = providers.Singleton(
        __import__(
            "core.application.services.backtest_service",
            fromlist=["BacktestService"],
        ).BacktestService,
        candle_repo=historical_candle_repository,
        session_factory=db_session_factory,
    )

    paper_trading_daemon = providers.Singleton(
        __import__(
            "core.application.services.paper_trading_daemon",
            fromlist=["PaperTradingDaemon"],
        ).PaperTradingDaemon,
        universe_service=market_universe_service,
        historical_service=historical_data_service,
        strategies=providers.List(),   # populated via factory below
        session_factory=db_session_factory,
    )

    # --- AI services ----------------------------------------------------------

    ai_client = providers.Singleton(
        __import__(
            "core.infrastructure.ai.ai_client",
            fromlist=["AIClient"],
        ).AIClient,
        config=ai_config,
    )

    news_analyst_service = providers.Singleton(
        __import__(
            "core.application.services.ai.news_analyst_service",
            fromlist=["NewsAnalystService"],
        ).NewsAnalystService,
        ai_client=ai_client,
    )

    market_analyst_service = providers.Singleton(
        __import__(
            "core.application.services.ai.market_analyst_service",
            fromlist=["MarketAnalystService"],
        ).MarketAnalystService,
        ai_client=ai_client,
        breadth_service=market_breadth_service,
        sentiment_service=sentiment_service,
        option_chain_service=option_chain_service,
        session_factory=db_session_factory,
    )

    strategy_selector_service = providers.Singleton(
        __import__(
            "core.application.services.ai.strategy_selector_service",
            fromlist=["StrategySelectorService"],
        ).StrategySelectorService,
        ai_client=ai_client,
        strategies=providers.List(),   # populated via factory
    )

    # ── Phase 20.5 — Post-Trade Intelligence ──────────────────────────────────
    post_trade_intelligence_service = providers.Singleton(
        __import__(
            "core.application.services.post_trade_intelligence_service",
            fromlist=["PostTradeIntelligenceService"],
        ).PostTradeIntelligenceService,
        session_factory=db_session_factory,
    )

    trade_journey_service = providers.Singleton(
        __import__(
            "core.application.services.trade_journey_service",
            fromlist=["TradeJourneyService"],
        ).TradeJourneyService,
        session_factory=db_session_factory,
    )

    # ── Phase 24 — Operations Mode ────────────────────────────────────────────

    platform_readiness_service = providers.Singleton(
        __import__(
            "core.application.services.platform_readiness_service",
            fromlist=["PlatformReadinessService"],
        ).PlatformReadinessService,
        session_factory=db_session_factory,
    )

    incident_service = providers.Singleton(
        __import__(
            "core.application.services.incident_service",
            fromlist=["IncidentService"],
        ).IncidentService,
        session_factory=db_session_factory,
    )

    pre_market_checklist_service = providers.Singleton(
        __import__(
            "core.application.services.pre_market_checklist_service",
            fromlist=["PreMarketChecklistService"],
        ).PreMarketChecklistService,
        session_factory=db_session_factory,
        platform_readiness_svc=platform_readiness_service,
    )

    component_attribution_service = providers.Singleton(
        __import__(
            "core.application.services.component_attribution_service",
            fromlist=["ComponentAttributionService"],
        ).ComponentAttributionService,
        session_factory=db_session_factory,
    )

    strategy_evolution_service = providers.Singleton(
        __import__(
            "core.application.services.strategy_evolution_service",
            fromlist=["StrategyEvolutionService"],
        ).StrategyEvolutionService,
        session_factory=db_session_factory,
    )

    weekly_intelligence_report_service = providers.Singleton(
        __import__(
            "core.application.services.weekly_intelligence_report_service",
            fromlist=["WeeklyIntelligenceReportService"],
        ).WeeklyIntelligenceReportService,
        session_factory=db_session_factory,
        strategy_evolution_svc=strategy_evolution_service,
        component_attribution_svc=component_attribution_service,
    )

    # ── Phase 20.6 — Research Intelligence ───────────────────────────────────
    trade_cohort_service = providers.Singleton(
        __import__(
            "core.application.services.trade_cohort_service",
            fromlist=["TradeCohortService"],
        ).TradeCohortService,
        session_factory=db_session_factory,
    )

    edge_discovery_service = providers.Singleton(
        __import__(
            "core.application.services.edge_discovery_service",
            fromlist=["EdgeDiscoveryService"],
        ).EdgeDiscoveryService,
        session_factory=db_session_factory,
    )

    trade_replay_service = providers.Singleton(
        __import__(
            "core.application.services.trade_replay_service",
            fromlist=["TradeReplayService"],
        ).TradeReplayService,
        session_factory=db_session_factory,
    )

    loss_cluster_service = providers.Singleton(
        __import__(
            "core.application.services.loss_cluster_service",
            fromlist=["LossClusterService"],
        ).LossClusterService,
        session_factory=db_session_factory,
    )

    operator_observability_service = providers.Singleton(
        __import__(
            "core.application.services.operator_observability_service",
            fromlist=["OperatorObservabilityService"],
        ).OperatorObservabilityService,
        session_factory=db_session_factory,
    )

    research_dashboard_service = providers.Singleton(
        __import__(
            "core.application.services.research_dashboard_service",
            fromlist=["ResearchDashboardService"],
        ).ResearchDashboardService,
        session_factory=db_session_factory,
        cohort_svc=trade_cohort_service,
        edge_svc=edge_discovery_service,
        cluster_svc=loss_cluster_service,
        observability_svc=operator_observability_service,
        portfolio_svc=portfolio_intelligence_service,
        strategy_evo_svc=strategy_evolution_service,
    )

    # ── Phase 23: Execution Intelligence ──────────────────────────────────────

    execution_timeline_service = providers.Singleton(
        __import__(
            "core.application.services.execution_intelligence.execution_timeline_service",
            fromlist=["ExecutionTimelineService"],
        ).ExecutionTimelineService,
        session_factory=db_session_factory,
    )

    execution_latency_service = providers.Singleton(
        __import__(
            "core.application.services.execution_intelligence.execution_latency_service",
            fromlist=["ExecutionLatencyService"],
        ).ExecutionLatencyService,
        session_factory=db_session_factory,
        redis_client=redis_client,
    )

    execution_slippage_service = providers.Singleton(
        __import__(
            "core.application.services.execution_intelligence.execution_slippage_service",
            fromlist=["ExecutionSlippageService"],
        ).ExecutionSlippageService,
        session_factory=db_session_factory,
    )

    execution_retry_service = providers.Singleton(
        __import__(
            "core.application.services.execution_intelligence.execution_retry_service",
            fromlist=["ExecutionRetryService"],
        ).ExecutionRetryService,
        session_factory=db_session_factory,
    )

    execution_rejection_service = providers.Singleton(
        __import__(
            "core.application.services.execution_intelligence.execution_rejection_service",
            fromlist=["ExecutionRejectionService"],
        ).ExecutionRejectionService,
        session_factory=db_session_factory,
    )

    execution_replay_service = providers.Singleton(
        __import__(
            "core.application.services.execution_intelligence.execution_replay_service",
            fromlist=["ExecutionReplayService"],
        ).ExecutionReplayService,
        session_factory=db_session_factory,
    )

    broker_health_monitor_service = providers.Singleton(
        __import__(
            "core.application.services.execution_intelligence.broker_health_monitor_service",
            fromlist=["BrokerHealthMonitorService"],
        ).BrokerHealthMonitorService,
        session_factory=db_session_factory,
        redis_client=redis_client,
    )

    execution_historical_service = providers.Singleton(
        __import__(
            "core.application.services.execution_intelligence.execution_historical_service",
            fromlist=["ExecutionHistoricalService"],
        ).ExecutionHistoricalService,
        session_factory=db_session_factory,
    )

    execution_event_handler = providers.Singleton(
        __import__(
            "core.application.services.execution_intelligence.execution_event_handler",
            fromlist=["ExecutionEventHandler"],
        ).ExecutionEventHandler,
        timeline_svc=execution_timeline_service,
        latency_svc=execution_latency_service,
        slippage_svc=execution_slippage_service,
        retry_svc=execution_retry_service,
        rejection_svc=execution_rejection_service,
        replay_svc=execution_replay_service,
        broker_health_svc=broker_health_monitor_service,
    )

    # ── Phase 24: Research Framework ──────────────────────────────────────────

    research_strategy_version_service = providers.Singleton(
        __import__(
            "core.application.services.research.strategy_version_service",
            fromlist=["StrategyVersionService"],
        ).StrategyVersionService,
        session_factory=db_session_factory,
    )

    research_performance_metrics_service = providers.Singleton(
        __import__(
            "core.application.services.research.performance_metrics_service",
            fromlist=["PerformanceMetricsService"],
        ).PerformanceMetricsService,
        session_factory=db_session_factory,
    )

    research_parameter_optimization_service = providers.Singleton(
        __import__(
            "core.application.services.research.parameter_optimization_service",
            fromlist=["ParameterOptimizationService"],
        ).ParameterOptimizationService,
        session_factory=db_session_factory,
    )

    research_walk_forward_analyzer_service = providers.Singleton(
        __import__(
            "core.application.services.research.walk_forward_analyzer_service",
            fromlist=["WalkForwardAnalyzerService"],
        ).WalkForwardAnalyzerService,
        session_factory=db_session_factory,
    )

    research_monte_carlo_simulation_service = providers.Singleton(
        __import__(
            "core.application.services.research.monte_carlo_simulation_service",
            fromlist=["MonteCarloSimulationService"],
        ).MonteCarloSimulationService,
        session_factory=db_session_factory,
    )

    research_component_correlation_service = providers.Singleton(
        __import__(
            "core.application.services.research.component_correlation_service",
            fromlist=["ComponentCorrelationService"],
        ).ComponentCorrelationService,
        session_factory=db_session_factory,
    )

    research_feature_importance_service = providers.Singleton(
        __import__(
            "core.application.services.research.feature_importance_service",
            fromlist=["FeatureImportanceService"],
        ).FeatureImportanceService,
        session_factory=db_session_factory,
        feature_registry=feature_registry,
    )

    research_regime_performance_service = providers.Singleton(
        __import__(
            "core.application.services.research.regime_performance_service",
            fromlist=["ResearchRegimePerformanceService"],
        ).ResearchRegimePerformanceService,
        session_factory=db_session_factory,
    )

    research_symbol_ranking_service = providers.Singleton(
        __import__(
            "core.application.services.research.symbol_ranking_service",
            fromlist=["SymbolRankingService"],
        ).SymbolRankingService,
        session_factory=db_session_factory,
    )

    research_false_positive_analyzer_service = providers.Singleton(
        __import__(
            "core.application.services.research.false_positive_analyzer_service",
            fromlist=["FalsePositiveAnalyzerService"],
        ).FalsePositiveAnalyzerService,
        session_factory=db_session_factory,
    )

    research_strategy_promotion_service = providers.Singleton(
        __import__(
            "core.application.services.research.strategy_promotion_service",
            fromlist=["StrategyPromotionService"],
        ).StrategyPromotionService,
        session_factory=db_session_factory,
    )

