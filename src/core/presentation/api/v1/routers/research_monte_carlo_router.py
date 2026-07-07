"""Research Monte Carlo router."""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from container import ApplicationContainer
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.research_schemas import (
    MonteCarloResultsResponse,
    StartMonteCarloRequest,
)

router = APIRouter(prefix="/api/v1/research/monte-carlo", tags=["Research — Monte Carlo"])


@router.post("/start", summary="Start a Monte Carlo simulation")
@inject
async def start_simulation(
    body: StartMonteCarloRequest,
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_monte_carlo_simulation_service]),
) -> dict:
    run_id = await svc.start_simulation(
        version_id=body.version_id,
        n_sims=body.n_sims,
        lookback_days=body.lookback_days,
        seed=body.seed,
    )
    return {"run_id": run_id, "status": "RUNNING"}


@router.get("/{run_id}/results", response_model=MonteCarloResultsResponse,
            summary="Get Monte Carlo results")
@inject
async def get_results(
    run_id: str,
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_monte_carlo_simulation_service]),
) -> MonteCarloResultsResponse:
    data = await svc.get_results(run_id)
    return MonteCarloResultsResponse(
        run_id=run_id,
        summary=data.get("summary", {}),
        simulations=data.get("simulations", []),
    )
