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

    # Check new passwords against the Have I Been Pwned k-anonymity range API.
    # Fails open (allows the password) if the service is unreachable, so it is
    # safe in offline/air-gapped deployments. Disabled in tests.
    password_breach_check_enabled: bool = True

    # Comma-separated list of allowed CORS origins, or "*". When unset in
    # production the app falls back to its own origin (see main.py); "*" in
    # development only.
    cors_origins: str = ""

    # Fernet key (urlsafe-base64, 32 bytes) used to encrypt MFA secrets at rest.
    # When empty, a key is derived deterministically from jwt_secret.
    mfa_encryption_key: str = ""

    # Data retention (DSGVO Art. 5(1)(e)). Run by the `retention` cron container.
    retention_enabled: bool = True
    retention_positions_hours: int = 24      # live positions older than this are purged
    retention_audit_days: int = 365          # audit-log entries older than this are purged
    retention_share_links_days: int = 30     # revoked share links older than this are purged

    class Config:
        env_file = ".env"


settings = Settings()
