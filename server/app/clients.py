"""Shared downstream clients, rebuilt automatically when config changes.

The Slskd client caches a JWT session, so it's shared across the worker and
API handlers — but must be replaced when its connection settings change at
runtime. Plex clients are stateless and cheap, so they're built per use.
"""

from .config import settings
from .plex import Plex
from .slskd import Slskd

_slskd: Slskd | None = None
_slskd_key: tuple | None = None


def get_slskd() -> Slskd:
    global _slskd, _slskd_key
    key = (
        settings.slskd_url,
        settings.slskd_api_key,
        settings.slskd_username,
        settings.slskd_password,
    )
    if _slskd is None or key != _slskd_key:
        _slskd = Slskd(
            settings.slskd_url,
            api_key=settings.slskd_api_key,
            username=settings.slskd_username,
            password=settings.slskd_password,
        )
        _slskd_key = key
    return _slskd


def get_plex() -> Plex:
    return Plex(settings.plex_url, settings.plex_token, settings.plex_section)
