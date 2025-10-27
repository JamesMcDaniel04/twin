"""
Configuration management for the TwinOps platform.

This module centralizes environment-driven configuration using Pydantic's
`BaseSettings`. All services consume the shared `settings` instance to ensure
consistent configuration across the stack.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import AnyUrl, Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration sourced from environment variables."""

    # General application settings
    API_TITLE: str = "TwinOps API"
    API_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = Field("development", pattern=r"^(development|staging|production)$")
    BASE_DIR: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[2])

    # Security / auth
    SECRET_KEY: str = Field("changeme", env="TWINOPS_SECRET_KEY")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALLOWED_ORIGINS: List[str] = Field(default_factory=lambda: ["*"])

    # Database connections
    NEO4J_URI: AnyUrl = Field("neo4j://localhost:7687")
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"

    PINECONE_API_KEY: str = Field("pinecone-api-key")
    PINECONE_ENVIRONMENT: str = Field("us-east-1-aws")
    PINECONE_INDEX: str = "twinops-knowledge"

    REDIS_URL: AnyUrl = Field("redis://localhost:6379/0")
    MONGODB_URL: AnyUrl = Field("mongodb://localhost:27017")

    # Auxiliary data stores
    ELASTICSEARCH_URL: AnyUrl = Field("http://localhost:9200")
    TEMPORAL_NAMESPACE: str = "twinops"
    TEMPORAL_TASK_QUEUE: str = "twinops-workflows"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"

    # Integrations
    SLACK_BOT_TOKEN: str = Field("xoxb-placeholder")
    SLACK_SIGNING_SECRET: str = Field("slack-signing-secret")
    JIRA_BASE_URL: Optional[AnyUrl] = None
    JIRA_API_TOKEN: Optional[str] = None
    GOOGLE_SERVICE_ACCOUNT_FILE: Optional[Path] = None
    GITHUB_APP_ID: Optional[str] = None
    GITHUB_PRIVATE_KEY_PATH: Optional[Path] = None

    # LLM provider configuration
    OPENAI_API_KEY: Optional[str] = None
    CLAUDE_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4"
    CLAUDE_MODEL: str = "claude-3-opus-20240229"
    EMBEDDING_MODEL: str = "text-embedding-ada-002"

    # Monitoring / tracing
    PROMETHEUS_PUSHGATEWAY: Optional[AnyUrl] = None
    OTEL_EXPORTER_JAEGER_ENDPOINT: Optional[AnyUrl] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    @field_validator("ALLOWED_ORIGINS", mode="before")
    def _split_origins(cls, value: str | List[str]) -> List[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache()
def get_settings() -> Settings:
    """Return a cached `Settings` instance."""

    return Settings()


# Singleton-style settings instance for modules that prefer direct access.
settings = get_settings()
