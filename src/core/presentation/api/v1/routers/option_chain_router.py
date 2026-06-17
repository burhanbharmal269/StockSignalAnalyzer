"""Option Chain Router.

GET  /api/v1/options/{underlying}          — latest option chain data + analysis
GET  /api/v1/options/{underlying}/history  — PCR history
POST /api/v1/options/{underlying}/refresh  — force refresh from provider
"""


from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.application.services.option_chain_service import OptionChainService

router = APIRouter(prefix="/options", tags=["option-chain"])


@router.get("/{underlying}")
@inject
async def get_chain(
    underlying: str,
    option_svc: OptionChainService = Depends(Provide[ApplicationContainer.option_chain_service]),
):
    data = await option_svc.get_latest(underlying.upper())
    return data or {"underlying": underlying.upper(), "message": "no_data"}


@router.get("/{underlying}/history")
@inject
async def get_pcr_history(
    underlying: str,
    limit: int = Query(20, ge=1, le=100),
    option_svc: OptionChainService = Depends(Provide[ApplicationContainer.option_chain_service]),
):
    history = await option_svc.get_pcr_history(underlying.upper(), limit=limit)
    return {"underlying": underlying.upper(), "history": history}


@router.post("/{underlying}/refresh")
@inject
async def refresh_chain(
    underlying: str,
    option_svc: OptionChainService = Depends(Provide[ApplicationContainer.option_chain_service]),
):
    result = await option_svc.fetch_and_store(underlying.upper())
    return result
