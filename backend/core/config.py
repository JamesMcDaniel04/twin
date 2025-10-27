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

from pydantic import AnyUrl, Field, PositiveInt, field_validator
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
    JWT_SECRET_KEY: str = Field("changeme", env="JWT_SECRET_KEY")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALLOWED_ORIGINS: List[str] = Field(default_factory=lambda: ["*"])
    ENCRYPTION_KEY: Optional[str] = None

    # Database connections
    NEO4J_URI: AnyUrl = Field("neo4j://localhost:7687")
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"

    PINECONE_API_KEY: str = Field("pinecone-api-key")
    PINECONE_ENVIRONMENT: str = Field("us-east-1-aws")
    PINECONE_INDEX: str = "twinops-knowledge"
    PINECONE_DIMENSION: PositiveInt = 1536

    REDIS_URL: AnyUrl = Field("redis://localhost:6379/0")
    MONGODB_URL: AnyUrl = Field("mongodb://localhost:27017")

    # Auxiliary data stores
    ELASTICSEARCH_URL: AnyUrl = Field("http://localhost:9200")
    TEMPORAL_NAMESPACE: str = "twinops"
    TEMPORAL_TASK_QUEUE: str = "twinops-workflows"
    TEMPORAL_HOST: str = "localhost:7233"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"

    # Object storage
    STORAGE_BACKEND: str = Field("local", pattern=r"^(local|s3|gcs)$")
    S3_BUCKET_NAME: Optional[str] = None
    S3_REGION: Optional[str] = None
    S3_ENDPOINT_URL: Optional[AnyUrl] = None
    GCS_BUCKET_NAME: Optional[str] = None
    LOCAL_STORAGE_PATH: Path = Field(default_factory=lambda: Path("storage"))

    # Integrations
    SLACK_BOT_TOKEN: str = Field("xoxb-placeholder")
    SLACK_SIGNING_SECRET: str = Field("slack-signing-secret")
    SLACK_APP_TOKEN: Optional[str] = None
    JIRA_BASE_URL: Optional[AnyUrl] = None
    JIRA_EMAIL: Optional[str] = None
    JIRA_API_TOKEN: Optional[str] = None
    GOOGLE_SERVICE_ACCOUNT_FILE: Optional[Path] = None
    GOOGLE_APPLICATION_CREDENTIALS: Optional[Path] = None
    GITHUB_APP_ID: Optional[str] = None
    GITHUB_PRIVATE_KEY_PATH: Optional[Path] = None
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_REPOS: List[str] = Field(default_factory=list)
    CONFLUENCE_URL: Optional[AnyUrl] = None
    CONFLUENCE_EMAIL: Optional[str] = None
    CONFLUENCE_API_TOKEN: Optional[str] = None
    GOOGLE_DRIVE_FILE_IDS: List[str] = Field(default_factory=list)

    # LLM provider configuration
    OPENAI_API_KEY: Optional[str] = None
    CLAUDE_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4"
    CLAUDE_MODEL: str = "claude-3-opus-20240229"
    EMBEDDING_MODEL: str = "text-embedding-ada-002"
    MAX_TOKENS: int = 4096
    TEMPERATURE: float = 0.7

    # Monitoring / tracing
    PROMETHEUS_PORT: int = 9090
    PROMETHEUS_PUSHGATEWAY: Optional[AnyUrl] = None
    OTEL_EXPORTER_JAEGER_ENDPOINT: Optional[AnyUrl] = None
    JAEGER_AGENT_HOST: str = "localhost"
    JAEGER_AGENT_PORT: int = 6831
    SENTRY_DSN: Optional[str] = None
    SENTRY_ENVIRONMENT: str = "development"

    # Rate limiting / performance tuning
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_PER_HOUR: int = 1000
    QUERY_TIMEOUT_SECONDS: int = 30
    MAX_CONCURRENT_QUERIES: int = 100
    VECTOR_SEARCH_TOP_K: int = 20
    GRAPH_TRAVERSAL_MAX_DEPTH: int = 3

    # Feature flags
    ENABLE_SLACK_BOT: bool = True
    ENABLE_JIRA_INTEGRATION: bool = True
    ENABLE_GITHUB_INTEGRATION: bool = True
    ENABLE_GOOGLE_WORKSPACE: bool = True
    ENABLE_WORKFLOW_AUTOMATION: bool = True
    ENABLE_ADVANCED_GRAPH_RAG: bool = True
    ENABLE_AUTO_DELEGATION: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    @field_validator("ALLOWED_ORIGINS", mode="before")
    def _split_origins(cls, value: str | List[str]) -> List[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("GITHUB_REPOS", "GOOGLE_DRIVE_FILE_IDS", mode="before")
    def _split_list(cls, value: str | List[str]) -> List[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value or []


@lru_cache()
def get_settings() -> Settings:
    """Return a cached `Settings` instance."""

    return Settings()


# Singleton-style settings instance for modules that prefer direct access.
settings = get_settings()
