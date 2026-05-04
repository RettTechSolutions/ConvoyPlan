import uuid
from typing import Any

from pydantic import BaseModel


class RouteResponse(BaseModel):
    id: uuid.UUID
    convoy_id: uuid.UUID
    distance_m: int | None
    duration_s: int | None
    routing_params: dict[str, Any] | None
    geojson: dict | None = None

    model_config = {"from_attributes": True}
