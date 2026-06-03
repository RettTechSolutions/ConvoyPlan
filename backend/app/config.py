from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://convoyplan:convoyplan@localhost:5432/convoyplan"
    jwt_secret: str = "changeme-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days
    graphhopper_url: str = "http://localhost:8989"
    caddy_admin_url: str = "http://caddy:2019"
    github_token: str = ""
    github_repo: str = "RettTechSolutions/ConvoyPlan"
    license_key: str = ""
    app_base_url: str = "https://convoyplan.example.com"

    # Deployment environment. In "production" the app refuses to start with an
    # insecure JWT secret (fail-closed). Set APP_ENV=development to relax this
    # for local work; tests bypass the check (lifespan is not triggered there).
    app_env: str = "production"

    # Brute-force protection for authentication endpoints. Disabled in tests.
    rate_limit_enabled: bool = True

    # Interactive API docs (Swagger UI at /docs, ReDoc at /redoc, schema at
    # /openapi.json). Always available in development environments. In
    # production they are disabled by default so the API surface is not exposed
    # publicly; set ENABLE_DOCS=true to opt back in (e.g. behind reverse-proxy
    # auth or on an internal network).
    enable_docs: bool = False

    class Config:
        env_file = ".env"


settings = Settings()
