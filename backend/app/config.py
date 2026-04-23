from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://clearpath_user:clearpath_pass@localhost:5432/clearpath"
    ollama_base_url: str = "http://localhost:11434"
    google_ai_studio_api_key: Optional[str] = None
    gemma_local_model: str = "gemma4:e2b-it-q4_K_M"
    gemma_cloud_model: str = "gemma-4-26b"
    app_env: str = "development"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"


settings = Settings()
