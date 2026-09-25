from pathlib import Path
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'postgresql+psycopg://jobfinder:local-jobfinder-password@localhost/jobfinder'
    storage_path: Path = Path('/storage')
    app_origin: str = 'http://localhost:5173'
    cookie_secure: bool = False
    admin_email: str = 'owner@example.com'
    openai_api_key: str = ''
    text_provider: Literal['openai', 'gemini'] = 'openai'
    gemini_api_key: str = ''
    gemini_model: str = Field(default='gemini-3.5-flash-lite', pattern=r'^[a-zA-Z0-9._-]+$', max_length=70)
    gemini_free_tier: bool = True
    gemini_daily_requests: int = Field(default=100, ge=1, le=10000)
    gemini_input_usd_per_million: float = Field(default=0.30, ge=0)
    gemini_output_usd_per_million: float = Field(default=2.50, ge=0)
    hh_access_token: str = ''
    hh_user_agent: str = 'JobFinderKZ/0.1 (owner@example.com)'
    text_model: str = 'gpt-5.4-mini'
    answer_audio_model: str = 'gpt-4o-mini-transcribe'
    video_audio_model: str = 'gpt-4o-transcribe-diarize'
    embedding_model: str = 'text-embedding-3-small'
    monthly_budget_usd: float = 20
    monthly_video_hours: float = 20
    input_usd_per_million: float = 1
    output_usd_per_million: float = 6
    embed_usd_per_million: float = 0.1
    audio_usd_per_minute: float = 0.02
    allowed_material_hosts: str = 'developer.mozilla.org,docs.python.org,react.dev,playwright.dev,docs.pytest.org'


settings = Settings()
