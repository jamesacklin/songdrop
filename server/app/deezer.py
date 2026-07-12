"""Track metadata search via the Deezer public API (no key required)."""

import httpx

BASE = "https://api.deezer.com"


async def search_tracks(query: str, limit: int = 25) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{BASE}/search", params={"q": query, "limit": limit})
        r.raise_for_status()
        data = r.json().get("data", [])
    results = []
    for t in data:
        results.append(
            {
                "id": t["id"],
                "title": t.get("title", ""),
                "artist": (t.get("artist") or {}).get("name", ""),
                "album": (t.get("album") or {}).get("title", ""),
                "cover": (t.get("album") or {}).get("cover_medium"),
                "duration": t.get("duration"),
                "source": "deezer",
                "cover_xl": (t.get("album") or {}).get("cover_xl"),
                "track_no": None,
                "year": None,
            }
        )
    return results


async def track_details(deezer_id: int) -> dict | None:
    """Full metadata for tagging: track/disc numbers, album, year, cover art."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{BASE}/track/{deezer_id}")
        if r.status_code != 200:
            return None
        t = r.json()
        if t.get("error"):
            return None
        album = t.get("album") or {}
        year = None
        cover_url = album.get("cover_xl") or album.get("cover_big")
        album_artist = None
        if album.get("id"):
            ra = await client.get(f"{BASE}/album/{album['id']}")
            if ra.status_code == 200 and not ra.json().get("error"):
                a = ra.json()
                date = a.get("release_date") or ""
                year = date[:4] if len(date) >= 4 else None
                cover_url = a.get("cover_xl") or cover_url
                album_artist = (a.get("artist") or {}).get("name")
    return {
        "title": t.get("title_short") or t.get("title", ""),
        "artist": (t.get("artist") or {}).get("name", ""),
        "album": album.get("title"),
        "album_artist": album_artist or (t.get("artist") or {}).get("name", ""),
        "track_no": t.get("track_position"),
        "disc_no": t.get("disk_number"),
        "year": year,
        "cover_url": cover_url,
        "duration": t.get("duration"),
    }


async def _all_album_tracks(client: httpx.AsyncClient, album_id: int, album: dict) -> list[dict]:
    """Full ordered tracklist, following Deezer's pagination past the ~25 cap."""
    tracks: list[dict] = list((album.get("tracks") or {}).get("data", []))
    nxt = (album.get("tracks") or {}).get("next")
    guard = 0
    while nxt and guard < 20:  # cap paging so a bad `next` can't loop forever
        guard += 1
        rp = await client.get(nxt)
        if rp.status_code != 200:
            break
        page = rp.json()
        tracks.extend(page.get("data", []))
        nxt = page.get("next")
    return tracks


async def find_album(artist: str, album: str) -> dict | None:
    """Album tracklist fallback for releases MusicBrainz doesn't know."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{BASE}/search/album", params={"q": f"{artist} {album}", "limit": 5})
        if r.status_code != 200:
            return None
        for candidate in r.json().get("data", []):
            ra = await client.get(f"{BASE}/album/{candidate['id']}")
            if ra.status_code != 200 or ra.json().get("error"):
                continue
            al = ra.json()
            # The album object embeds only the first ~25 tracks; page the
            # /album/{id}/tracks endpoint to get the full list.
            raw_tracks = await _all_album_tracks(client, candidate["id"], al)
            discs = {t.get("disk_number") for t in raw_tracks if t.get("disk_number")}
            multi_disc = len(discs) > 1
            tracks = [
                {
                    "position": i + 1,
                    "title": t.get("title", ""),
                    "track_no": t.get("track_position") or (i + 1),
                    "disc_no": t.get("disk_number") if multi_disc else None,
                }
                for i, t in enumerate(raw_tracks)
            ]
            if not tracks:
                continue
            date = al.get("release_date") or ""
            return {
                "title": al.get("title") or album,
                "artist": (al.get("artist") or {}).get("name") or artist,
                "year": date[:4] if len(date) >= 4 else None,
                "cover": al.get("cover_medium"),
                "cover_xl": al.get("cover_xl"),
                "source": "deezer",
                "tracks": tracks,
            }
    return None


async def fetch_cover(url: str) -> tuple[bytes, str] | None:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        r = await client.get(url)
        if r.status_code != 200:
            return None
        mime = r.headers.get("content-type", "image/jpeg").split(";")[0]
        return r.content, mime
