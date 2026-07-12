"""YouTube acquisition via yt-dlp — the fallback when Soulseek has nothing.

Downloads the bare bestaudio stream (m4a preferred) so no ffmpeg is needed;
YouTube audio tops out around 128kbps AAC, so this is a last resort behind
Soulseek, not a replacement. Also handles user-supplied YouTube URLs.
"""

import asyncio
import os
import re
import shutil
import tempfile

import yt_dlp

MIN_SECONDS, MAX_SECONDS = 60, 1200
# A candidate scoring below this is more likely the wrong thing (karaoke, cover,
# live) than the track — better to keep retrying than import garbage.
MIN_SCORE = 30.0
# Version qualifiers that mean "wrong video" unless the user asked for them.
UNWANTED = {
    "live", "cover", "reaction", "karaoke", "instrumental", "remix",
    "acoustic", "demo", "slowed", "reverb", "nightcore", "8d",
    "edition", "version", "mix", "mashup", "remaster", "remastered",
    "bootleg", "concert", "festival", "tour", "unplugged", "session", "sessions",
}


def _tokens(s: str) -> list[str]:
    # \w is Unicode-aware, so CJK/Cyrillic/accented titles still tokenize; keep
    # 1-char tokens only when they carry meaning (non-ASCII, e.g. a CJK glyph).
    return [t for t in re.split(r"[^\w]+", s.lower(), flags=re.UNICODE) if t and (len(t) > 1 or not t.isascii())]


def score_video(
    entry: dict, artist: str, title: str, duration_hint: int | None = None
) -> float | None:
    """Score a search result; None means 'not a plausible match'.

    duration_hint (seconds, from catalog metadata) is the strongest signal
    against live cuts and extended versions when we have it."""
    duration = entry.get("duration")
    if duration and not (MIN_SECONDS <= duration <= MAX_SECONDS):
        return None
    video_title = (entry.get("title") or "").lower()
    title_tokens = _tokens(title)
    if not title_tokens:
        return None
    hits = sum(1 for t in title_tokens if t in video_title)
    if hits / len(title_tokens) < 0.8:
        return None

    score = 50.0
    channel = (entry.get("channel") or entry.get("uploader") or "").lower()
    artist_tokens = _tokens(artist)
    if artist_tokens and (
        all(t in video_title for t in artist_tokens)
        or all(t in channel for t in artist_tokens)
    ):
        score += 20
    # Auto-generated "Artist - Topic" channels are the album audio, ideal.
    if channel.endswith(" - topic"):
        score += 25
    if "official audio" in video_title:
        score += 15
    elif "audio" in video_title:
        score += 5
    unwanted = (set(_tokens(video_title)) & UNWANTED) - set(title_tokens)
    score -= 40 * len(unwanted)

    if duration_hint and duration:
        diff = abs(duration - duration_hint)
        if diff <= 15:
            score += 25
        elif diff <= 30:
            score += 10
        elif diff > 90:
            score -= 30
    return score


def pick_video(
    entries: list[dict], artist: str, title: str, duration_hint: int | None = None
) -> dict | None:
    scored = [(score_video(e, artist, title, duration_hint), e) for e in entries or []]
    # Discard the unmatchable AND the strongly-penalized (karaoke/cover/live):
    # importing the wrong recording tagged as the original is worse than not
    # importing at all — the request keeps retrying instead.
    scored = [(s, e) for s, e in scored if s is not None and s >= MIN_SCORE]
    if not scored:
        return None
    return max(scored, key=lambda x: x[0])[1]


def _entry_url(entry: dict) -> str | None:
    if entry.get("url"):
        return entry["url"]
    if entry.get("webpage_url"):
        return entry["webpage_url"]
    if entry.get("id"):
        return f"https://www.youtube.com/watch?v={entry['id']}"
    return None


def _download_sync(url: str) -> str | None:
    # Work in a throwaway dir we always delete; move the one finished file out
    # so partial .part files, extra playlist entries, and the dir itself never
    # accumulate in the container.
    workdir = tempfile.mkdtemp(prefix="songdrop-yt-work-")
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": os.path.join(workdir, "%(id)s.%(ext)s"),
        "noplaylist": True,
        "playlist_items": "1",  # belt-and-suspenders vs any list URL slipping through
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info.get("entries"):
                info = info["entries"][0]
            produced = ydl.prepare_filename(info)
        if not produced or not os.path.exists(produced):
            return None
        # Relocate to a stable flat temp file the caller (worker) will move into
        # the library; keep the extension for the tagger's format detection.
        ext = os.path.splitext(produced)[1]
        fd, dest = tempfile.mkstemp(prefix="songdrop-yt-", suffix=ext)
        os.close(fd)
        shutil.move(produced, dest)
        return dest
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _search_sync(artist: str, title: str) -> list[dict]:
    query = f"ytsearch6:{artist} {title}"
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
    return (info or {}).get("entries") or []


async def download_url(url: str) -> str | None:
    """Download audio from a specific YouTube URL. Returns the local path."""
    return await asyncio.wait_for(asyncio.to_thread(_download_sync, url), timeout=600)


async def search_and_download(
    artist: str, title: str, duration_hint: int | None = None
) -> str | None:
    """Find the best-matching YouTube audio for a track and download it."""
    entries = await asyncio.wait_for(
        asyncio.to_thread(_search_sync, artist, title), timeout=120
    )
    best = pick_video(entries, artist, title, duration_hint)
    if best is None:
        return None
    url = _entry_url(best)
    if url is None:
        return None
    return await download_url(url)
