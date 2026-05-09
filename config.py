"""AutoNoGaDa ADK — 설정 (shared-libraries + LM Studio)."""
from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "autonogada-adk"
    version: str = "0.1.0"
    environment: str = "development"

    database_url: str = (
        "postgresql+asyncpg://dev:dev@postgres:5432/mediiot"
    )
    redis_url: str = "redis://redis:6379/0"

    llm_provider: str = "local"

    git_repo_path: str = Field(
        default="/app",
        validation_alias=AliasChoices("GIT_REPO_PATH", "git_repo_path"),
    )
    git_generated_prefix: str = Field(default="generated/snippets")

    git_author_name: str = Field(
        default="AutoNoGaDa CI",
        validation_alias=AliasChoices("GIT_AUTHOR_NAME", "git_author_name"),
    )
    git_author_email: str = Field(
        default="autonogada@localhost",
        validation_alias=AliasChoices("GIT_AUTHOR_EMAIL", "git_author_email"),
    )
    git_committer_name: str = Field(
        default="",
        validation_alias=AliasChoices("GIT_COMMITTER_NAME", "git_committer_name"),
    )
    git_committer_email: str = Field(
        default="",
        validation_alias=AliasChoices("GIT_COMMITTER_EMAIL", "git_committer_email"),
    )
    git_default_remote: str = Field(default="origin")

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in ("dev", "development", "local")


@lru_cache
def get_settings() -> Settings:
    return Settings()
