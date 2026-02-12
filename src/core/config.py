from pathlib import Path
from common.config import BaseAgentSettings

class Settings(BaseAgentSettings):
    VIVALDI_HISTORY_PATH: str = ""

settings = Settings()

def get_vivaldi_profile_path() -> Path:
    """Resolved Vivaldi Default profile directory (History and Bookmarks live here)."""
    if settings.VIVALDI_HISTORY_PATH:
        p = Path(settings.VIVALDI_HISTORY_PATH).expanduser().resolve()
    else:
        p = (Path.home() / ".config" / "vivaldi" / "Default").resolve()
    return p
