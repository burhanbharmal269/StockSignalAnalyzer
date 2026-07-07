"""SQLAlchemy ORM models — imported here for Alembic autogenerate discovery."""

from core.infrastructure.database.models.base import Base
from core.infrastructure.database.models.broker_session_models import BrokerSessionOrm
from core.infrastructure.database.models.instrument_models import InstrumentOrm
from core.infrastructure.database.models.market_data_models import (
    MarketDataOrm,
    MarketFeaturesOrm,
    OptionChainOrm,
)
from core.infrastructure.database.models.order_models import OrderEventOrm, OrderOrm
from core.infrastructure.database.models.position_models import PositionOrm
from core.infrastructure.database.models.regime_models import RegimeSnapshotOrm
from core.infrastructure.database.models.signal_models import SignalEventOrm, SignalOrm
from core.infrastructure.database.models.risk_models import (  # noqa: F401
    KillSwitchEventModel,
    RiskDecisionModel,
)
from core.infrastructure.database.models.signal_performance_models import (
    SignalPerformanceStatsOrm,
)
from core.infrastructure.database.models.capital_framework_models import (  # noqa: F401
    AllocationHistoryOrm,
    CapitalAllocationOrm,
    PortfolioOrm,
    RiskProfileOrm,
)
from core.infrastructure.database.models.user_models import AuditLogOrm, UserOrm
from core.infrastructure.database.models.research_models import (  # noqa: F401
    ResearchStrategyVersionOrm,
    ResearchRunOrm,
    ResearchOptimizationRunOrm,
    ResearchOptimizationResultOrm,
    ResearchWalkForwardWindowOrm,
    ResearchMonteCarloRunOrm,
    ResearchMonteCarloResultOrm,
    ResearchPerformanceSnapshotOrm,
    ResearchComponentCorrelationOrm,
    ResearchFeatureImportanceOrm,
    ResearchRegimePerformanceOrm,
    ResearchSymbolRankingOrm,
    ResearchFalsePositiveAnalysisOrm,
    ResearchPromotionRequestOrm,
    ResearchThresholdAnalysisOrm,
)

__all__ = [
    "AllocationHistoryOrm",
    "AuditLogOrm",
    "Base",
    "BrokerSessionOrm",
    "CapitalAllocationOrm",
    "InstrumentOrm",
    "KillSwitchEventModel",
    "MarketDataOrm",
    "MarketFeaturesOrm",
    "OptionChainOrm",
    "OrderEventOrm",
    "OrderOrm",
    "PortfolioOrm",
    "PositionOrm",
    "RegimeSnapshotOrm",
    "RiskDecisionModel",
    "RiskProfileOrm",
    "SignalEventOrm",
    "SignalOrm",
    "SignalPerformanceStatsOrm",
    "UserOrm",
]
