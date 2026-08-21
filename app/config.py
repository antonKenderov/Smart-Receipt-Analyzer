from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, model_validator

class Settings(BaseSettings):
    llm_model: str = "gpt-4o"
    openai_api_key: SecretStr | None = None
    llm_timeout_seconds: int = 60

    database_url: str
    output_dir: Path = Path("output")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _require_api_key(self):
        if not self.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set. "
                "Copy .env.example to .env and add your key."
            )
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings()