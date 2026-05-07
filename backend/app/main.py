import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, convoys, vehicles, routing, organizations, tracking, lage, weather, overpass, status, users

app = FastAPI(title="ConvoyPlan API", version="0.2.0")

_origins_env = os.environ.get("CORS_ORIGINS", "*")
_allow_origins = [o.strip() for o in _origins_env.split(",")] if _origins_env != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# V1
app.include_router(auth.router, prefix="/api")
app.include_router(vehicles.router, prefix="/api")
app.include_router(convoys.router, prefix="/api")
app.include_router(routing.router, prefix="/api")

# V2
app.include_router(organizations.router, prefix="/api")

# V3
app.include_router(tracking.router, prefix="/api")
app.include_router(lage.router, prefix="/api")
app.include_router(weather.router, prefix="/api")
app.include_router(overpass.router, prefix="/api")
app.include_router(status.router, prefix="/api")
app.include_router(users.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.2.0"}
