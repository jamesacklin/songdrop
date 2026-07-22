"""Configuration: environment variables provide defaults; connection settings
for slskd and Plex can be overridden at runtime via the API (persisted in the
database and applied without a restart)."""

import os

# Keys the app may edit via PUT /api/config. Paths and the Songdrop API key
# stay env-only: paths are volume mounts, and the API key is the bootstrap
# credential the app itself authenticates with.
RUNTIME_KEYS = (
    "slskd_url",
    "slskd_api_key",
    "slskd_username",
    "slskd_password",
    "plex_url",
    "plex_token",
    "plex_section",
    "ytdlp_enabled",
)


class Settings:
    def __init__(self) -> None:
        # slskd
        self.slskd_url = os.environ.get("SLSKD_URL", "http://localhost:5030").rstrip("/")
        # Auth: either an API key, or username/password (JWT login).
        self.slskd_api_key = os.environ.get("SLSKD_API_KEY", "")
        self.slskd_username = os.environ.get("SLSKD_USERNAME", "")
        self.slskd_password = os.environ.get("SLSKD_PASSWORD", "")
        # Where completed slskd downloads land, as seen by THIS process.
        self.slskd_downloads_dir = os.environ.get("SLSKD_DOWNLOADS_DIR", "/downloads")

        # Final Plex music library root, as seen by THIS process.
        self.music_library_dir = os.environ.get("MUSIC_LIBRARY_DIR", "/music")
        # If Plex sees the library at a different path (path mapping across
        # containers/hosts), set this to the library root as PLEX sees it.
        self.plex_library_dir = os.environ.get("PLEX_LIBRARY_DIR", "") or os.environ.get(
            "MUSIC_LIBRARY_DIR", "/music"
        )

        # Plex
        self.plex_url = os.environ.get("PLEX_URL", "").rstrip("/")
        self.plex_token = os.environ.get("PLEX_TOKEN", "")
        # Optional: name of the music library section. Auto-detected if empty.
        self.plex_section = os.environ.get("PLEX_SECTION", "")

        # Songdrop
        self.api_key = os.environ.get("SONGDROP_API_KEY", "")
        self.db_path = os.environ.get("DATABASE_PATH", "./songdrop.db")

        # Optional ntfy topic URL for push notifications, e.g. https://ntfy.sh/my-topic
        self.ntfy_url = os.environ.get("NTFY_URL", "")

        # Tunables
        # Must comfortably exceed slskd's own search lifetime (~40s): slskd
        # returns zero responses for searches that haven't completed yet.
        self.search_timeout = int(os.environ.get("SEARCH_TIMEOUT", "90"))
        self.download_timeout = int(os.environ.get("DOWNLOAD_TIMEOUT", "900"))
        self.max_candidates = int(os.environ.get("MAX_CANDIDATES", "3"))
        # Fall back to YouTube (yt-dlp) when Soulseek has nothing.
        self.ytdlp_enabled = os.environ.get("YTDLP_ENABLED", "true").lower() != "false"
        # When a search finds nothing (or every peer flakes), retry this often.
        self.retry_interval = int(os.environ.get("RETRY_INTERVAL", "600"))
        # 0 = retry until the user deletes the request.
        self.max_search_retries = int(os.environ.get("MAX_SEARCH_RETRIES", "0"))

    def apply_overrides(self, overrides: dict) -> None:
        """Apply runtime config (from the DB / PUT /api/config) over env defaults."""
        for key, value in overrides.items():
            if key not in RUNTIME_KEYS or value is None:
                continue
            if key == "ytdlp_enabled":
                self.ytdlp_enabled = (
                    value if isinstance(value, bool)
                    else str(value).strip().lower() not in ("false", "0", "no", "off", "")
                )
                continue
            value = str(value).strip()
            if key.endswith("_url"):
                value = value.rstrip("/")
            setattr(self, key, value)

    def runtime_config(self) -> dict:
        return {key: getattr(self, key) for key in RUNTIME_KEYS}


settings = Settings()
