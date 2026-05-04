"""
集中配置: pydantic-settings 从 .env 读取。
红线: 所有人独立 API key, 不共享。
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === LLM ===
    gemini_api_key: str

    # === Reddit ===
    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str = "neu-compass/0.1"

    # === Google OAuth (Week 6 才需要) ===
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8501/oauth/callback"

    # === Storage ===
    sqlite_path: str = str(PROJECT_ROOT / "data" / "courses.db")
    faiss_index_path: str = str(PROJECT_ROOT / "data" / "faiss_index")

    # === API base URL (Streamlit -> FastAPI hop, Week 6) ===
    api_base_url: str = "http://localhost:8000"

    # === Embedding ===
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cuda"
    embedding_dim: int = 1024  # bge-m3 维度

    # === Logging ===
    log_level: str = "INFO"
    log_format: str = "json"  # json | console

    # === API budget ===
    api_budget_alarm: float = Field(default=150.0, description="USD/month, 超出触发告警")

    # === OAuth domain whitelist ===
    allowed_email_domains: list[str] = ["husky.neu.edu", "northeastern.edu"]


settings = Settings()
