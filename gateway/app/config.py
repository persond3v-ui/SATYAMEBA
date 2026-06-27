"""Runtime configuration, loaded from environment / .env.

Every secret here MUST be overridden in production via the .env file that the
setup script generates. The defaults are intentionally weak placeholders so
that an unconfigured deployment fails loudly rather than silently shipping a
known secret.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, List

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SAT_", env_file=".env", extra="ignore")

    # --- core ---
    environment: str = "development"
    project_name: str = "SATYAMEBA"
    owner: str = "Samaraho Mukherjee"

    # --- database (ORM only; we never build raw SQL strings) ---
    database_url: str = "postgresql+psycopg2://satyameba:satyameba@db:5432/satyameba"

    # --- JWT / sessions ---
    # RS256 keypair is preferred; if private key is empty we fall back to HS256
    # using jwt_secret. The setup script provisions an RSA keypair.
    jwt_algorithm: str = "RS256"
    jwt_private_key: str = ""          # PEM, RS256 (inline)
    jwt_public_key: str = ""           # PEM, RS256 (inline)
    jwt_private_key_path: str = ""     # or a mounted file path
    jwt_public_key_path: str = ""
    jwt_secret: str = "CHANGE_ME_dev_only_secret"  # HS256 fallback
    access_token_ttl_seconds: int = 900            # 15 min — short lived
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 7  # 7 days

    # --- request signing (anti-replay / anti-tamper) ---
    request_signing_enabled: bool = True
    request_signing_skew_seconds: int = 120        # accepted clock skew
    request_signing_protect_methods: Annotated[List[str], NoDecode] = [
        "POST", "PUT", "PATCH", "DELETE"
    ]

    # --- bootstrap admin (created on first start if no admin exists) ---
    bootstrap_admin_email: str = "admin@satyameba.local"
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = ""  # empty => random, printed once to logs

    # --- jupyterhub integration ---
    hub_api_url: str = "http://jupyterhub:8081/hub/api"
    hub_api_token: str = "CHANGE_ME_hub_api_token"
    hub_public_url: str = "/hub"

    # --- internal shared secret (gateway <-> hub authenticator) ---
    internal_shared_secret: str = "CHANGE_ME_internal_secret"

    # --- single sign-on one-time tokens (SPA -> Hub, no second login) ---
    sso_token_ttl_seconds: int = 60

    # --- monitoring proxy (admin dashboard pulls live numbers from here) ---
    prometheus_url: str = "http://prometheus:9090"

    # --- redis (shared rate-limit + replay-nonce store across replicas) ---
    redis_url: str = ""  # empty => in-process fallback (single replica only)

    # --- resource / storage policy (populated by scan_resources.sh) ---
    expected_users: int = 8
    user_storage_limit_gb: int = 20
    free_storage_gb: int = 0
    total_storage_gb: int = 0

    # --- security knobs ---
    cors_origins: Annotated[List[str], NoDecode] = [
        "https://localhost", "https://satyameba.local"
    ]
    rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 10
    bot_filter_enabled: bool = True

    @field_validator("cors_origins", "request_signing_protect_methods", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    def model_post_init(self, __context) -> None:
        # Load PEM keys from mounted files when paths are provided.
        if not self.jwt_private_key and self.jwt_private_key_path:
            try:
                self.jwt_private_key = open(self.jwt_private_key_path).read()
            except OSError:
                pass
        if not self.jwt_public_key and self.jwt_public_key_path:
            try:
                self.jwt_public_key = open(self.jwt_public_key_path).read()
            except OSError:
                pass

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
