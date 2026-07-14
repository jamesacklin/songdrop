"""Background worker: processes queued requests through the full pipeline.

acquire:  slskd search -> pick candidate -> download -> tag -> move -> Plex scan -> playlist
import:   (file already on disk)                     -> tag -> move -> Plex scan -> playlist
"""

import asyncio
import contextlib
import logging
import os
import time

import httpx

from . import clients, deezer, notify, ytdl
from .config import settings
from .db import Database
from .scoring import rank_candidates
from .slskd import SlskdError
from .tagger import TrackMeta, find_downloaded_file, library_destination, move_into_library, tag_file

log = logging.getLogger("songdrop.worker")

# httpx.InvalidURL (bad config, e.g. a mistyped port) is NOT an HTTPError, so
# name it explicitly — otherwise it escapes to the generic handler and hard-fails
# the request instead of being treated as a (retryable) connectivity problem.
NET_ERRORS = (SlskdError, httpx.HTTPError, httpx.InvalidURL, OSError)


class PipelineError(Exception):
    """A request failed for a reason worth surfacing to the user.

    retryable=True means the failure is plausibly transient on the Soulseek
    side (nothing found, peers flaked) and the request should be retried
    automatically after a delay instead of failing outright.
    """

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class Worker:
    def __init__(self, db: Database) -> None:
        self.db = db

    # Resolved per use so runtime config changes apply without a restart.
    @property
    def slskd(self):
        return clients.get_slskd()

    @property
    def plex(self):
        return clients.get_plex()

    async def run(self) -> None:
        requeued = self.db.reset_stale()
        if requeued:
            log.info("requeued %d stale request(s) after restart", requeued)
        while True:
            try:
                await self._tick()
            except Exception:
                # The loop must survive anything (db locked, disk full, ...).
                log.exception("worker loop error; continuing")
                await asyncio.sleep(5)

    async def _tick(self) -> None:
        req = self.db.next_ready()
        if req is None:
            await asyncio.sleep(2)
            return
        try:
            await self.process(req)
        except PipelineError as e:
            if e.retryable and self._should_retry(req):
                attempt = (req.get("retry_count") or 0) + 1
                log.info("request %s: %s; scheduling retry #%d", req["id"], e, attempt)
                self.db.update(
                    req["id"],
                    status="waiting",
                    error="",
                    retry_count=attempt,
                    next_retry_at=time.time() + settings.retry_interval,
                    detail=f"{e} — will search again (attempt {attempt})",
                )
                return
            log.warning("request %s failed: %s", req["id"], e)
            self.db.update(req["id"], status="failed", error=str(e))
            await notify.send(
                settings.ntfy_url,
                "Track Summon: request failed",
                f"{req['artist']} - {req['title']}: {e}",
            )
        except Exception:
            log.exception("unexpected error processing request %s", req["id"])
            self.db.update(req["id"], status="failed", error="internal error (see server logs)")

    def _should_retry(self, req: dict) -> bool:
        if settings.max_search_retries <= 0:
            return True  # unlimited; the user deletes the request to stop
        return (req.get("retry_count") or 0) < settings.max_search_retries

    async def process(self, req: dict) -> None:
        rid = req["id"]
        log.info("processing request %s: %s - %s", rid, req["artist"], req["title"])

        if req["mode"] == "import":
            local_path = req.get("source_path") or ""
            if not os.path.isfile(local_path):
                raise PipelineError(f"file not found: {local_path}")
            source = "your file"
        else:
            local_path, source = await self.acquire(req)

        self.db.update(rid, status="tagging", detail="tagging metadata")
        meta = await self.build_meta(req)
        try:
            tag_file(local_path, meta)
        except Exception as e:
            # A bad tag write shouldn't lose the file; import untagged instead.
            log.warning("tagging failed for %s: %s", local_path, e)
            self.db.update(rid, detail=f"tagging failed ({e}); importing untagged")

        dest = library_destination(settings.music_library_dir, meta, local_path)
        final_path = move_into_library(local_path, dest)
        self.db.update(rid, file_path=final_path, detail="moved into library")
        log.info("request %s: moved to %s", rid, final_path)

        # Verify the track actually landed in Plex before claiming it's ready —
        # a scan that targets the wrong path (bad volume/PLEX_LIBRARY_DIR mapping)
        # silently imports nothing, so "ready to play" would otherwise lie.
        in_plex, note = await self.plex_import(req, meta, final_path)
        srcsfx = f" · {source}" if source and source != "your file" else ""
        if in_plex is None:
            detail = f"saved to your library (Plex not configured){srcsfx}"
        elif in_plex:
            detail = (note or "ready to play") + srcsfx
        else:
            detail = note  # honest failure note (path mapping / Plex error)

        self.db.update(rid, status="done", detail=detail)
        await notify.send(
            settings.ntfy_url,
            "Track Summon: track ready" if in_plex or in_plex is None else "Track Summon: needs attention",
            f"{meta.artist} - {meta.title}: {detail}",
        )

    async def acquire(self, req: dict) -> tuple[str, str]:
        """Download the track and return (local_path, source_label). A supplied
        YouTube URL wins, otherwise Soulseek (best candidate), otherwise the
        YouTube fallback."""
        rid = req["id"]

        if req.get("youtube_url"):
            self.db.update(rid, status="downloading", detail="downloading from YouTube link")
            try:
                path = await ytdl.download_url(req["youtube_url"])
            except Exception as e:
                log.warning("request %s: YouTube link download failed: %s", rid, e)
                # A specific link failing (removed/region-locked) won't heal on retry.
                raise PipelineError(f"YouTube download failed: {e}") from e
            if path is None:
                raise PipelineError("YouTube download produced no file")
            return path, "YouTube link"

        self.db.update(rid, status="searching", detail="searching Soulseek")
        query = f"{req['artist']} {req['title']}"
        # Resolve the client ONCE so a mid-pipeline config change can't make us
        # enqueue on one slskd and then poll a different one.
        slskd = self.slskd
        try:
            responses = await slskd.search(query, timeout=settings.search_timeout)
        except NET_ERRORS as e:
            raise PipelineError(f"slskd search failed: {e}", retryable=True) from e

        candidates = rank_candidates(responses, req["artist"], req["title"])
        if not candidates:
            return await self._youtube_fallback(req, "not on Soulseek", ui="not on Soulseek — trying YouTube")
        log.info("request %s: %d candidate(s), best score %.0f", rid, len(candidates), candidates[0]["score"])

        last_error = "download failed"
        for i, cand in enumerate(candidates[: settings.max_candidates]):
            self.db.update(
                rid,
                status="downloading",
                detail=f"downloading from {cand['username']} (attempt {i + 1})",
            )
            try:
                await slskd.enqueue(cand["username"], cand["filename"], cand["size"])
            except NET_ERRORS as e:
                last_error = f"enqueue failed: {e}"
                continue

            try:
                state = await slskd.wait_for_download(
                    cand["username"], cand["filename"], timeout=settings.download_timeout
                )
                if "Succeeded" not in state:
                    await slskd.cancel(cand["username"], cand["filename"])
                    last_error = f"download from {cand['username']} ended in state {state}"
                    continue
            except NET_ERRORS as e:
                last_error = f"lost contact with slskd during download: {e}"
                continue

            local = find_downloaded_file(
                settings.slskd_downloads_dir, cand["filename"], cand["size"]
            )
            if local is None:
                last_error = (
                    "download completed but file not found in "
                    f"{settings.slskd_downloads_dir} (check volume mapping)"
                )
                continue
            return local, "Soulseek"
        # Candidates existed but every attempt failed; try YouTube before giving
        # up (peers may also be back later, so this stays retryable).
        return await self._youtube_fallback(req, last_error, ui="Soulseek attempts failed — trying YouTube")

    async def _youtube_fallback(self, req: dict, reason: str, ui: str = "trying YouTube") -> tuple[str, str]:
        if not settings.ytdlp_enabled:
            raise PipelineError(reason, retryable=True)
        rid = req["id"]
        self.db.update(rid, status="downloading", detail=ui)
        log.info("request %s: %s; trying YouTube fallback", rid, reason)
        duration_hint = None
        if req.get("deezer_id"):
            with contextlib.suppress(Exception):
                details = await deezer.track_details(req["deezer_id"])
                duration_hint = (details or {}).get("duration")
        try:
            path = await ytdl.search_and_download(req["artist"], req["title"], duration_hint)
        except Exception as e:
            log.warning("request %s: YouTube fallback errored: %s", rid, e)
            path = None
        if path is None:
            raise PipelineError(f"{reason}; YouTube had no good match either", retryable=True)
        self.db.update(rid, detail="downloaded from YouTube (~128kbps AAC)")
        return path, "YouTube (~128kbps AAC)"

    async def build_meta(self, req: dict) -> TrackMeta:
        meta = TrackMeta(
            title=req["title"],
            artist=req["artist"],
            album=req.get("album"),
            track_no=req.get("track_no"),
            disc_no=req.get("disc_no"),
            year=req.get("year"),
        )
        # Cover art supplied by the request (iTunes results, manual requests).
        if req.get("cover_url") and not req.get("deezer_id"):
            try:
                cover = await deezer.fetch_cover(req["cover_url"])
            except Exception:
                cover = None
            if cover:
                meta.cover, meta.cover_mime = cover
        if req.get("deezer_id"):
            try:
                details = await deezer.track_details(req["deezer_id"])
            except Exception as e:
                log.warning("deezer metadata lookup failed: %s", e)
                details = None
            if details:
                meta.title = details["title"] or meta.title
                meta.artist = details["artist"] or meta.artist
                meta.album = details["album"] or meta.album
                meta.album_artist = details["album_artist"]
                meta.track_no = details["track_no"]
                meta.disc_no = details["disc_no"]
                meta.year = details["year"]
                if details["cover_url"]:
                    try:
                        cover = await deezer.fetch_cover(details["cover_url"])
                    except Exception:
                        cover = None
                    if cover:
                        meta.cover, meta.cover_mime = cover
        return meta

    async def plex_import(self, req: dict, meta: TrackMeta, final_path: str) -> tuple[bool | None, str | None]:
        """Scan the file into Plex and confirm it actually indexed.

        Returns (in_plex, note):
          None  -> Plex isn't configured (nothing to import into)
          True  -> confirmed present in Plex (note may carry a playlist warning)
          False -> filed on disk but Plex never indexed it (note explains)
        """
        if not self.plex.configured:
            return None, None
        rid = req["id"]
        self.db.update(rid, status="importing", detail="scanning into Plex")
        try:
            section = await self.plex.music_section_id()
            # Translate the album dir to the path Plex sees, if they differ.
            album_dir = os.path.dirname(final_path)
            plex_dir = album_dir
            if settings.plex_library_dir != settings.music_library_dir:
                rel = os.path.relpath(album_dir, settings.music_library_dir)
                plex_dir = os.path.join(settings.plex_library_dir, rel)
            await self.plex.refresh_path(section, plex_dir)

            # Always verify the scan actually indexed the track — a wrong path
            # mapping scans nothing and would otherwise look like success.
            key = await self.plex.wait_for_track(section, meta.title, meta.artist, timeout=60)
            if key is None:
                return False, (
                    f"filed at {final_path}, but Plex hasn't indexed it — check that "
                    "this path is inside your Plex music library (volume mount / PLEX_LIBRARY_DIR)"
                )
            if req.get("playlist"):
                try:
                    await self.plex.add_to_playlist(req["playlist"], key)
                except Exception as e:  # noqa: BLE001 - playlist add is non-fatal
                    log.warning("playlist add failed for request %s: %s", rid, e)
                    return True, f"in Plex; couldn't add to playlist '{req['playlist']}' ({e})"
            return True, None
        except Exception as e:  # noqa: BLE001 - Plex failures must not lose the file
            log.warning("plex import step failed for request %s: %s", rid, e)
            return False, f"filed at {final_path}, but the Plex step failed: {e}"
