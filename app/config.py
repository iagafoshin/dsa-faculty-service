from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "dsa-faculty-service"
    app_version: str = "0.2.0"
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/hse_faculty"
    cors_origins: str = "*"
    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw == "*" or raw == "":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


settings = Settings()
