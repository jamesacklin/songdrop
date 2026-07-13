"""Album tracklists via MusicBrainz.

Streaming catalogs omit tracks (regional editions, physical-only releases);
MusicBrainz catalogs them all, so "view full album" asks MB first. Cover art
comes from the Cover Art Archive (may 404 for obscure releases — callers and
clients must tolerate missing art).
"""

import asyncio

import httpx

BASE = "https://musicbrainz.org/ws/2"
CAA = "https://coverartarchive.org"
HEADERS = {"User-Agent": "Track Summon/1.0 (self-hosted music requester)"}


def _lucene_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def pick_best_release(releases: list[dict]) -> dict | None:
    """Among near-top-score matches, prefer official releases, then the most
    complete edition (max track count) — bonus/deluxe editions win."""
    if not releases:
        return None
    top = max(r.get("score", 0) for r in releases)
    pool = [r for r in releases if r.get("score", 0) >= top - 10]
    official = [r for r in pool if (r.get("status") or "").lower() == "official"]
    pool = official or pool
    return max(pool, key=lambda r: r.get("track-count") or 0)


async def find_album(artist: str, album: str) -> dict | None:
    query = f'release:"{_lucene_escape(album)}" AND artist:"{_lucene_escape(artist)}"'
    async with httpx.AsyncClient(headers=HEADERS, timeout=15) as client:
        r = await client.get(
            f"{BASE}/release", params={"query": query, "fmt": "json", "limit": 10}
        )
        r.raise_for_status()
        best = pick_best_release(r.json().get("releases", []))
        if best is None:
            return None
        await asyncio.sleep(1.0)  # MB rate limit: ~1 request/second
        d = await client.get(
            f"{BASE}/release/{best['id']}", params={"inc": "recordings", "fmt": "json"}
        )
        d.raise_for_status()
        detail = d.json()

    media = detail.get("media", [])
    multi_disc = len(media) > 1
    tracks = []
    for disc_index, medium in enumerate(media, start=1):
        for track_index, t in enumerate(medium.get("tracks", []), start=1):
            tracks.append({
                # Unique, sequential across discs: the stable list id + ordering.
                "position": len(tracks) + 1,
                "title": t.get("title", ""),
                # Real per-disc track number for tagging, so disc 2 track 1 tags
                # as track 1 of disc 2 — not track (len of disc 1 + 1).
                "track_no": track_index,
                "disc_no": disc_index if multi_disc else None,
            })
    if not tracks:
        return None

    credit = "".join(
        (c.get("name") or "") + (c.get("joinphrase") or "")
        for c in (best.get("artist-credit") or [])
    )
    date = best.get("date") or detail.get("date") or ""
    return {
        "title": detail.get("title") or best.get("title") or album,
        "artist": credit or artist,
        "year": date[:4] if len(date) >= 4 else None,
        "cover": f"{CAA}/release/{best['id']}/front-500",
        "cover_xl": f"{CAA}/release/{best['id']}/front-1200",
        "source": "musicbrainz",
        "tracks": tracks,
    }
