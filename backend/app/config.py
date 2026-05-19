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
    domain: str = "localhost"

    class Config:
        env_file = ".env"


settings = Settings()
