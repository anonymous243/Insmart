from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://claimuser:claimpass@localhost:5432/claimsdb"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    TPA_BASE_URL: str = "http://localhost:8000"
    HIS_CALLBACK_BASE_URL: str = "http://localhost:8000"
    # JWT signing secret — override in production via JWT_SECRET_KEY env variable
    JWT_SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
