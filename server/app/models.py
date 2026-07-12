"""API request/response models."""

from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class RequestIn(BaseModel):
    artist: str = Field(min_length=1)
    title: str = Field(min_length=1)
    album: str | None = None
    deezer_id: int | None = None
    playlist: str | None = None
    # Tagging metadata for non-Deezer sources (iTunes results, manual requests).
    cover_url: str | None = None
    track_no: int | None = None
    disc_no: int | None = None
    year: str | None = None
    # Acquire from this exact YouTube video instead of searching Soulseek.
    youtube_url: str | None = None

    @field_validator("youtube_url")
    @classmethod
    def _validate_youtube_url(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        url = v.strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("youtube_url must be an http(s) URL")
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        # Only single-video links: a playlist/channel/search URL would make
        # yt-dlp download every entry, so reject anything that isn't one video.
        if host == "youtu.be":
            if not parsed.path.strip("/"):
                raise ValueError("youtu.be link must include a video id")
        elif host.endswith("youtube.com"):
            if parsed.path not in ("/watch", "/shorts") and not parsed.path.startswith(
                ("/shorts/", "/embed/")
            ):
                raise ValueError("youtube_url must be a single video (watch/shorts/embed), not a playlist or channel")
            if parsed.path == "/watch" and "v=" not in (parsed.query or ""):
                raise ValueError("youtube.com/watch link must include a v= video id")
        else:
            raise ValueError("youtube_url must be a youtube.com or youtu.be link")
        return url


class ImportIn(BaseModel):
    path: str = Field(min_length=1)
    artist: str = Field(min_length=1)
    title: str = Field(min_length=1)
    album: str | None = None
    deezer_id: int | None = None
    playlist: str | None = None
    cover_url: str | None = None
    track_no: int | None = None
    disc_no: int | None = None
    year: str | None = None
