"""Track Summon API: song-first requests for a self-hosted music library."""

import asyncio
import contextlib
import logging
import os
import secrets
import time

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import clients, deezer, itunes, mb
from .config import RUNTIME_KEYS, settings
from .db import Database
from .models import ImportIn, RequestIn
from .worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("songdrop")

db = Database(settings.db_path)
# Config saved via PUT /api/config overrides env defaults across restarts.
_persisted = db.get_config()
settings.apply_overrides(_persisted)

# Access key resolution: an explicit SONGDROP_API_KEY env var always wins. If
# it's unset, reuse a key persisted in /data from a previous boot, or generate
# and persist one — so a fresh container is secured by default and the operator
# can read the key from the container logs. `_auto_key` is set only in the
# auto path, so an operator-provided key is never echoed to the logs.
_auto_key = None
if not settings.api_key:
    settings.api_key = _persisted.get("api_key") or secrets.token_urlsafe(24)
    if not _persisted.get("api_key"):
        db.set_config({"api_key": settings.api_key})
    _auto_key = settings.api_key


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = asyncio.create_task(Worker(db).run())
    if _auto_key:
        log.warning(
            "\n" + "=" * 64
            + "\n  Track Summon access key (auto-generated — set SONGDROP_API_KEY to override):"
            + "\n\n      %s\n"
            + "\n  Enter this as the Access key when connecting the app or PWA.\n"
            + "=" * 64,
            _auto_key,
        )
    yield
    worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker_task


app = FastAPI(title="Track Summon", lifespan=lifespan)


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}


async def _probe_slskd() -> dict:
    try:
        state = str((await clients.get_slskd().app_state()).get("server", {}).get("state", "unknown"))
        return {
            "ok": "Connected" in state and "LoggedIn" in state,
            "detail": f"Soulseek: {state}",
        }
    except Exception as e:
        return {"ok": False, "detail": f"unreachable: {e}"}


async def _probe_plex() -> dict:
    plex = clients.get_plex()
    if not plex.configured:
        return {"ok": False, "detail": "not configured"}
    try:
        await plex.machine_id()
        return {"ok": True, "detail": "connected"}
    except Exception as e:
        return {"ok": False, "detail": f"unreachable: {e}"}


@app.get("/api/status", dependencies=[Depends(require_api_key)])
async def status() -> dict:
    """Downstream connectivity plus where files land — the paths are env/volume
    driven (not runtime-editable), so surfacing them lets the app diagnose the
    common 'ready to play but not in Plex' volume-mapping mistake."""
    slskd_status, plex_status = await asyncio.gather(_probe_slskd(), _probe_plex())
    return {
        "ok": slskd_status["ok"] and plex_status["ok"],
        "slskd": slskd_status,
        "plex": plex_status,
        "ytdlp_enabled": settings.ytdlp_enabled,
        "paths": {
            "music_library_dir": settings.music_library_dir,
            "plex_library_dir": settings.plex_library_dir,
            "slskd_downloads_dir": settings.slskd_downloads_dir,
        },
    }


class ConfigIn(BaseModel):
    slskd_url: str | None = None
    slskd_api_key: str | None = None
    slskd_username: str | None = None
    slskd_password: str | None = None
    plex_url: str | None = None
    plex_token: str | None = None
    plex_section: str | None = None
    ytdlp_enabled: bool | None = None

    @field_validator("slskd_url", "plex_url")
    @classmethod
    def _validate_url(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return v
        url = v.strip()
        # Reject a malformed URL here rather than let it reach the worker, where
        # httpx.InvalidURL (e.g. a mistyped port) would hard-fail every request.
        try:
            parsed = httpx.URL(url)
        except Exception as e:
            raise ValueError(f"not a valid URL: {e}") from e
        if parsed.scheme not in ("http", "https") or not parsed.host:
            raise ValueError("URL must be http(s):// with a host")
        return url


@app.get("/api/config", dependencies=[Depends(require_api_key)])
async def get_config() -> dict:
    """Current slskd/Plex connection settings (runtime overrides over env)."""
    return settings.runtime_config()


@app.put("/api/config", dependencies=[Depends(require_api_key)])
async def put_config(body: ConfigIn) -> dict:
    """Update slskd/Plex connection settings. Only provided fields change;
    persisted in the database and applied immediately (no restart)."""
    updates = {
        k: v for k, v in body.model_dump(exclude_unset=True).items() if k in RUNTIME_KEYS and v is not None
    }
    if updates:
        settings.apply_overrides(updates)
        # Persist normalized values as strings (the config table is TEXT).
        db.set_config({k: str(getattr(settings, k)) for k in updates})
    return settings.runtime_config()


def merge_results(*sources: list[dict], limit: int = 40) -> list[dict]:
    """Interleave sources in priority order, dropping same-artist+title dupes."""
    seen: set[tuple[str, str]] = set()
    merged = []
    for source in sources:
        for t in source:
            key = (t["artist"].strip().lower(), t["title"].strip().lower())
            if key in seen:
                continue
            seen.add(key)
            merged.append(t)
    return merged[:limit]


@app.get("/api/search", dependencies=[Depends(require_api_key)])
async def search(q: str) -> dict:
    if not q.strip():
        return {"results": []}
    dz, it = await asyncio.gather(
        deezer.search_tracks(q.strip()),
        itunes.search_tracks(q.strip()),
        return_exceptions=True,
    )
    if isinstance(dz, BaseException) and isinstance(it, BaseException):
        raise HTTPException(status_code=502, detail=f"metadata search failed: {dz}")
    return {
        "results": merge_results(
            dz if isinstance(dz, list) else [],
            it if isinstance(it, list) else [],
        )
    }


@app.get("/api/album", dependencies=[Depends(require_api_key)])
async def album_tracks(artist: str, album: str) -> dict:
    """Full tracklist for an album — MusicBrainz first (it catalogs editions
    streaming services omit), Deezer as fallback."""
    if not artist.strip() or not album.strip():
        raise HTTPException(status_code=400, detail="artist and album are required")
    result = None
    try:
        result = await mb.find_album(artist.strip(), album.strip())
    except Exception as e:
        log.warning("musicbrainz album lookup failed: %s", e)
    if result is None:
        try:
            result = await deezer.find_album(artist.strip(), album.strip())
        except Exception as e:
            log.warning("deezer album lookup failed: %s", e)
    if result is None:
        raise HTTPException(status_code=404, detail="album not found in MusicBrainz or Deezer")
    return result


@app.get("/api/requests", dependencies=[Depends(require_api_key)])
async def list_requests() -> dict:
    # `now` lets clients correct for clock skew when rendering countdowns.
    return {"requests": db.list(), "now": time.time()}


@app.get("/api/requests/{rid}", dependencies=[Depends(require_api_key)])
async def get_request(rid: int) -> dict:
    req = db.get(rid)
    if req is None:
        raise HTTPException(status_code=404, detail="request not found")
    return req


@app.post("/api/requests", status_code=201, dependencies=[Depends(require_api_key)])
async def create_request(body: RequestIn) -> dict:
    return db.add_request(
        artist=body.artist.strip(),
        title=body.title.strip(),
        album=body.album,
        deezer_id=body.deezer_id,
        playlist=body.playlist,
        cover_url=body.cover_url,
        track_no=body.track_no,
        disc_no=body.disc_no,
        year=body.year,
        youtube_url=body.youtube_url,
    )


class BulkRequestIn(BaseModel):
    requests: list[RequestIn] = Field(min_length=1, max_length=100)


@app.post("/api/requests/bulk", status_code=201, dependencies=[Depends(require_api_key)])
async def create_requests_bulk(body: BulkRequestIn) -> dict:
    """Queue many tracks at once (e.g. a whole album). Skips tracks that
    already have a live request OR are already in the Plex library — so
    'Request All' on a half-owned album only fetches what's missing."""
    plex = clients.get_plex()
    section = None
    if plex.configured:
        with contextlib.suppress(Exception):
            section = await plex.music_section_id()

    async def in_library(title: str, artist: str) -> bool:
        if section is None:
            return False
        try:
            return await plex.find_track(section, title, artist) is not None
        except Exception:
            return False

    created, skipped = 0, 0
    for item in body.requests:
        artist, title = item.artist.strip(), item.title.strip()
        if await in_library(title, artist):
            skipped += 1
            continue
        # Atomic check-and-insert so overlapping bulk calls can't double-add.
        inserted = db.add_request_if_absent(
            artist,
            title,
            album=item.album,
            deezer_id=item.deezer_id,
            playlist=item.playlist,
            cover_url=item.cover_url,
            track_no=item.track_no,
            disc_no=item.disc_no,
            year=item.year,
            youtube_url=item.youtube_url,
        )
        created += 1 if inserted else 0
        skipped += 0 if inserted else 1
    return {"created": created, "skipped": skipped}


@app.post("/api/requests/{rid}/retry", dependencies=[Depends(require_api_key)])
async def retry_request(rid: int) -> dict:
    req = db.get(rid)
    if req is None:
        raise HTTPException(status_code=404, detail="request not found")
    if req["status"] not in ("failed", "done", "waiting"):
        raise HTTPException(status_code=409, detail="request is still in progress")
    db.update(rid, status="queued", error="", detail="retrying", next_retry_at=None, retry_count=0)
    return db.get(rid)


@app.delete("/api/requests/{rid}", status_code=204, dependencies=[Depends(require_api_key)])
async def delete_request(rid: int, purge: bool = False) -> None:
    """Remove a request from the list. With purge=true, also delete the imported
    file from disk and remove the track (and its playlist entries) from Plex."""
    req = db.get(rid)
    if req is None:
        raise HTTPException(status_code=404, detail="request not found")
    if req["status"] not in ("queued", "done", "failed", "waiting"):
        raise HTTPException(status_code=409, detail="request is in progress; wait for it to finish")
    if purge and req["status"] == "done" and req.get("file_path"):
        await _purge_file(req)
    db.delete(rid)


class ClearIn(BaseModel):
    statuses: list[str] = ["done", "failed"]


@app.post("/api/requests/clear", dependencies=[Depends(require_api_key)])
async def clear_requests(body: ClearIn) -> dict:
    """Bulk-remove finished requests from the list (files stay on disk)."""
    allowed = {"done", "failed", "waiting", "queued"}
    bad = set(body.statuses) - allowed
    if bad:
        raise HTTPException(status_code=400, detail=f"cannot clear statuses: {sorted(bad)}")
    return {"cleared": db.delete_by_statuses(body.statuses)}


async def _purge_file(req: dict) -> None:
    """Delete the file behind a completed request and scrub it out of Plex."""
    library_root = os.path.realpath(settings.music_library_dir)
    path = os.path.realpath(req["file_path"])
    if not path.startswith(library_root + os.sep):
        raise HTTPException(status_code=400, detail="file is outside the music library; not deleting")

    plex = clients.get_plex()
    rating_key = section = None
    if plex.configured:
        with contextlib.suppress(Exception):
            section = await plex.music_section_id()
            rating_key = await plex.find_track(section, req["title"], req["artist"])

    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"could not delete file: {e}") from e
    # Prune now-empty album/artist folders, staying inside the library root.
    folder = os.path.dirname(path)
    while os.path.realpath(folder).startswith(library_root + os.sep):
        try:
            os.rmdir(folder)  # only succeeds when empty
        except OSError:
            break
        folder = os.path.dirname(folder)

    if not plex.configured or section is None:
        return
    with contextlib.suppress(Exception):
        # Deleting the item drops it (and its playlist entries) immediately;
        # needs "Allow media deletion" enabled on the Plex server.
        if rating_key and await plex.delete_item(rating_key):
            return
        # Fallback: rescan the folder so Plex trashes the missing track, then
        # empty the trash to drop it and its playlist entries.
        album_dir = os.path.dirname(req["file_path"])
        plex_dir = album_dir
        if settings.plex_library_dir != settings.music_library_dir:
            rel = os.path.relpath(album_dir, settings.music_library_dir)
            plex_dir = os.path.join(settings.plex_library_dir, rel)
        await plex.refresh_path(section, plex_dir)
        await asyncio.sleep(8)  # give the scanner a moment to notice
        await plex.empty_trash(section)


@app.post("/api/import", status_code=201, dependencies=[Depends(require_api_key)])
async def import_file(body: ImportIn) -> dict:
    """Tag a file already on disk and move it into the Plex library."""
    if not os.path.isfile(body.path):
        raise HTTPException(status_code=400, detail=f"file not found: {body.path}")
    return db.add_request(
        artist=body.artist.strip(),
        title=body.title.strip(),
        album=body.album,
        deezer_id=body.deezer_id,
        playlist=body.playlist,
        mode="import",
        source_path=body.path,
        cover_url=body.cover_url,
        track_no=body.track_no,
        disc_no=body.disc_no,
        year=body.year,
    )


@app.get("/api/playlists", dependencies=[Depends(require_api_key)])
async def playlists() -> dict:
    plex = clients.get_plex()
    if not plex.configured:
        return {"playlists": []}
    try:
        items = await plex.playlists()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"plex playlist lookup failed: {e}") from e
    return {"playlists": [p["title"] for p in items]}


# Serve the PWA (mirrors the iOS app) from the package's static/ dir. Mounted
# last so the /api/* routes above always take precedence; the app authenticates
# its own API calls with the X-API-Key it collects in onboarding.
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="pwa")
