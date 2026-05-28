from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "dsa-faculty-service"
    app_version: str = "0.4.0"
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/hse_faculty"
    cors_origins: str = "*"
    log_level: str = "INFO"
    admin_token: str | None = None
    # HTTP Basic Auth для UI-админки (/admin, /admin/scrape, ...).
    # Если admin_password не задан — UI-админка целиком закрыта (403).
    admin_user: str = "admin"
    admin_password: str | None = None
    # Периодический джоб обновления данных (scrape + re-embed).
    # 0 = выключен. Любое > 0 запускает scheduler при старте приложения.
    schedule_days: int = 0
    # Запускать ли scheduler сразу же при первом старте (для теста), True/False.
    schedule_run_on_startup: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw == "*" or raw == "":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


settings = Settings()
