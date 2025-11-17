from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
    ADMIN_ID: str

    # Bot
    bot_token: SecretStr
    use_webhook: bool | None = None
    webhook_port: int | None = None
    bot_webhook_url: str | None = None
    bot_secret_token: str | None = None
    bot_skip_updates: bool = True

    # Database
    DATABASE_URL: SecretStr
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 50
    DB_POOL_RECYCLE: int = 3600
    DB_ECHO: bool = False

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
    default_quota_free: int = 10
    default_quota_premium: int = 1000

    # Monitoring
    prometheus_port: int = 8000
    log_level: str = "DEBUG"
    debug: bool = True


    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


settings = Settings()