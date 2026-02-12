from common.config import BaseAgentSettings


class Settings(BaseAgentSettings):
    """WhatsApp specific settings."""
    # DATABASE_URL and EMBEDDING_URL are inherited
    pass


settings = Settings()
