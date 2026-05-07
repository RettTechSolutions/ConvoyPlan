import os
from contextlib import asynccontextmanager

import bcrypt
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.routes import auth, convoys, vehicles, routing, organizations, tracking, lage, weather, overpass, status, users
from app.config import settings
from app.database import get_db_session
from app.models.user import User


async def _seed_superadmin() -> None:
    if not settings.superadmin_email or not settings.superadmin_password:
        return
    async with get_db_session() as db:
        result = await db.execute(select(User).where(User.is_superadmin == True))
        if result.scalar_one_or_none():
            return
        user = User(
            email=settings.superadmin_email,
            hashed_password=bcrypt.hashpw(
                settings.superadmin_password.encode(), bcrypt.gensalt()
            ).decode(),
            is_superadmin=True,
        )
        db.add(user)
        await db.commit()
        print(f"[seed] Superadmin created: {settings.superadmin_email}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _seed_superadmin()
    yield


app = FastAPI(title="ConvoyPlan API", version="0.3.0", lifespan=lifespan)

_origins_env = os.environ.get("CORS_ORIGINS", "*")
_allow_origins = [o.strip() for o in _origins_env.split(",")] if _origins_env != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(vehicles.router, prefix="/api")
app.include_router(convoys.router, prefix="/api")
app.include_router(routing.router, prefix="/api")
app.include_router(organizations.router, prefix="/api")
app.include_router(tracking.router, prefix="/api")
app.include_router(lage.router, prefix="/api")
app.include_router(weather.router, prefix="/api")
app.include_router(overpass.router, prefix="/api")
app.include_router(status.router, prefix="/api")
app.include_router(users.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.3.0"}
