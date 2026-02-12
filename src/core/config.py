from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = ""
    EMBEDDING_URL: str  # Required: Python MCP uses it for vector search; only Python runs embeddings.

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
