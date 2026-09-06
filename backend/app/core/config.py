from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file (backend/.env), not the process's cwd --
# otherwise launching uvicorn from anywhere but backend/ silently finds no
# .env and every setting falls back to its default (empty API key, etc).
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8")

    app_name: str = "AnalystAI API"
    environment: str = "development"
    backend_cors_origins_raw: str = Field(
        default="http://localhost:5173",
        validation_alias="BACKEND_CORS_ORIGINS",
    )
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(
        default="gemini-3.1-pro-preview", validation_alias="GEMINI_MODEL"
    )

    @computed_field
    @property
    def backend_cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.backend_cors_origins_raw.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

