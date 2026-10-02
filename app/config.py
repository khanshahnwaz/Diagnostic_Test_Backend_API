from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://eve:eve@localhost:5432/eve"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    bcrypt_rounds: int = 12
    webhook_secret: str = "change-me-too"
    # comma separated, these emails become admins on signup
    admin_emails: str = ""
    # chance of a simulated payment succeeding when the caller doesn't force an outcome
    payment_success_rate: float = 0.8

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


settings = Settings()
