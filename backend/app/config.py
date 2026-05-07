from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://marschplan:marschplan@localhost:5432/marschplan"
    jwt_secret: str = "changeme-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days
    graphhopper_url: str = "http://localhost:8989"
    superadmin_email: str = ""
    superadmin_password: str = ""
    acme_email: str = "admin@example.com"

    class Config:
        env_file = ".env"


settings = Settings()
