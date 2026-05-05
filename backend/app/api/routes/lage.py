import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.convoy import Convoy
from app.models.lage_layer import LageLayer
from app.models.user import User

router = APIRouter(prefix="/convoys", tags=["lage"])


class LageLayerCreate(BaseModel):
    name: str
    geojson_data: dict
    color: str = "#e74c3c"
    visible: bool = True


class LageLayerUpdate(BaseModel):
    name: str | None = None
    geojson_data: dict | None = None
    color: str | None = None
    visible: bool | None = None


class LageLayerResponse(BaseModel):
    id: uuid.UUID
    name: str
    geojson_data: dict
    color: str
    visible: bool

    model_config = {"from_attributes": True}


@router.get("/{convoy_id}/lage", response_model=list[LageLayerResponse])
async def list_lage_layers(
    convoy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_access(convoy_id, current_user.id, db)
    result = await db.execute(select(LageLayer).where(LageLayer.convoy_id == convoy_id))
    return result.scalars().all()


@router.post("/{convoy_id}/lage", response_model=LageLayerResponse, status_code=status.HTTP_201_CREATED)
async def create_lage_layer(
    convoy_id: uuid.UUID,
    data: LageLayerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_access(convoy_id, current_user.id, db)
    layer = LageLayer(**data.model_dump(), convoy_id=convoy_id)
    db.add(layer)
    await db.commit()
    await db.refresh(layer)
    return layer


@router.put("/{convoy_id}/lage/{layer_id}", response_model=LageLayerResponse)
async def update_lage_layer(
    convoy_id: uuid.UUID,
    layer_id: uuid.UUID,
    data: LageLayerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_access(convoy_id, current_user.id, db)
    result = await db.execute(
        select(LageLayer).where(LageLayer.id == layer_id, LageLayer.convoy_id == convoy_id)
    )
    layer = result.scalar_one_or_none()
    if not layer:
        raise HTTPException(status_code=404, detail="Layer nicht gefunden")
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(layer, key, value)
    await db.commit()
    await db.refresh(layer)
    return layer


@router.delete("/{convoy_id}/lage/{layer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lage_layer(
    convoy_id: uuid.UUID,
    layer_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_access(convoy_id, current_user.id, db)
    result = await db.execute(
        select(LageLayer).where(LageLayer.id == layer_id, LageLayer.convoy_id == convoy_id)
    )
    layer = result.scalar_one_or_none()
    if layer:
        await db.delete(layer)
        await db.commit()


async def _assert_access(convoy_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession):
    result = await db.execute(
        select(Convoy).where(Convoy.id == convoy_id, Convoy.owner_id == user_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Convoy nicht gefunden")
