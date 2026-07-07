"""Research strategy version router — version registry CRUD."""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

from container import ApplicationContainer
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.research_schemas import (
    CreateVariantRequest,
    UpdateVariantRequest,
    VersionListResponse,
    VersionResponse,
)

router = APIRouter(prefix="/api/v1/research/versions", tags=["Research — Versions"])


@router.get("", response_model=VersionListResponse, summary="List strategy versions")
@inject
async def list_versions(
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_strategy_version_service]),
) -> VersionListResponse:
    versions = await svc.list_versions()
    return VersionListResponse(
        versions=[VersionResponse(**{k: v for k, v in (v.items() if isinstance(v, dict) else vars(v).items())}) for v in versions],
        total=len(versions),
    )


@router.get("/{version_id}", response_model=VersionResponse, summary="Get a strategy version")
@inject
async def get_version(
    version_id: str,
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_strategy_version_service]),
) -> VersionResponse:
    v = await svc.get_version(version_id)
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    return VersionResponse(**v)


@router.post("", response_model=VersionResponse, status_code=status.HTTP_201_CREATED,
             summary="Create a research variant")
@inject
async def create_variant(
    body: CreateVariantRequest,
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_strategy_version_service]),
) -> VersionResponse:
    result = await svc.create_variant(
        name=body.name,
        base_version_id=body.base_version_id,
        weights=body.weights,
        params=body.params,
        description=body.description,
    )
    return VersionResponse(**result)


@router.patch("/{version_id}", response_model=VersionResponse, summary="Update a research variant")
@inject
async def update_variant(
    version_id: str,
    body: UpdateVariantRequest,
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_strategy_version_service]),
) -> VersionResponse:
    try:
        result = await svc.update_variant(
            version_id=version_id, weights=body.weights, params=body.params
        )
        v = await svc.get_version(version_id)
        return VersionResponse(**v) if v else VersionResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
