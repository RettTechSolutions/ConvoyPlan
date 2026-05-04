from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, convoys, vehicles, routing

app = FastAPI(title="MarschPlan API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(vehicles.router, prefix="/api")
app.include_router(convoys.router, prefix="/api")
app.include_router(routing.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
