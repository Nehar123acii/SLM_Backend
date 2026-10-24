from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./privacy_assistant.db"
    upload_temp_dir: str = "./uploads_temp"
    max_upload_rows: int = 50_000
    max_upload_columns: int = 200
    ai_mode: str = "mock"  # "mock" | "live"
    ai_live_url: str = "http://localhost:11434"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
