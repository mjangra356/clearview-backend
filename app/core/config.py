import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    COMPANIES_HOUSE_API_KEY: str = "4d9206cf-a0b4-4adf-b760-c9818053fbe1"
    COMPANIES_HOUSE_BASE_URL: str = "https://api.company-information.service.gov.uk"
    
    # LLM Configuration
    LLM_PROVIDER: str = "gemini" # 'gemini' | 'openai'
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    
    PORT: int = 8000
    CACHE_TTL_SECONDS: int = 900 # 15 minutes in-memory cache
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
