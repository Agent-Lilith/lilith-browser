from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = ""
    EMBEDDING_URL: str = ""
    VIVALDI_HISTORY_PATH: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()


def get_vivaldi_profile_path() -> Path:
    """Resolved Vivaldi Default profile directory (History and Bookmarks live here)."""
    if settings.VIVALDI_HISTORY_PATH:
        p = Path(settings.VIVALDI_HISTORY_PATH).expanduser().resolve()
    else:
        p = (Path.home() / ".config" / "vivaldi" / "Default").resolve()
    return p
