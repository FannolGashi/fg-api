from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    app_name: str = "FG API"

    admin_username: str = "admin"
    admin_password: str = "changeme"
    secret_key: str = "please-change-this-secret-key-in-production-min-32"
    access_token_expire_minutes: int = 480

    data_dir: Path = Path("/data")

    default_timeout: int = 30
    default_max_concurrent: int = 3
    max_timeout: int = 300
    max_output_bytes: int = 1_048_576   # 1 MB cap on stdout/stderr
    max_upload_bytes: int = 10_485_760  # 10 MB script upload limit


settings = Settings()

SCRIPTS_DIR = settings.data_dir / "scripts"
VENVS_DIR   = settings.data_dir / "venvs"
LOGS_DIR    = settings.data_dir / "logs"
DB_DIR      = settings.data_dir / "db"

for _d in [SCRIPTS_DIR, VENVS_DIR, LOGS_DIR, DB_DIR]:
    _d.mkdir(parents=True, exist_ok=True)
