from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Bot
    bot_token: str
    bot_webhook_url: str | None = None
    bot_secret_token: str | None = None
    bot_skip_updates: bool = True

    # Database
    database_url: str
    db_echo: bool = False

    # Redis
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str

    # MinIO
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket_name: str = "image-bot-storage"
    minio_use_ssl: bool = False
    minio_public_url: str

    # Processing
    max_file_size_mb: int = 20
    supported_formats: str = "jpg,jpeg,png,webp,tiff"
    default_quota_free: int = 10
    default_quota_premium: int = 1000

    # Monitoring
    prometheus_port: int = 8000
    log_level: str = "INFO"

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


settings = Settings()