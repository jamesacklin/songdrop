"""Track metadata search via the iTunes Search API (no key required).

Second source alongside Deezer — catalogs differ, and remix/compilation
albums missing from one are often on the other.
"""

import httpx

BASE = "https://itunes.apple.com"


def _art(url: str | None, size: int) -> str | None:
    return url.replace("100x100", f"{size}x{size}") if url else None


async def search_tracks(query: str, limit: int = 25) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{BASE}/search",
            params={"term": query, "entity": "song", "media": "music", "limit": limit},
        )
        r.raise_for_status()
        data = r.json().get("results", [])
    results = []
    for t in data:
        if t.get("wrapperType") not in (None, "track"):
            continue
        release = t.get("releaseDate") or ""
        results.append(
            {
                "id": t.get("trackId"),
                "title": t.get("trackName", ""),
                "artist": t.get("artistName", ""),
                "album": t.get("collectionName", ""),
                "cover": t.get("artworkUrl100"),
                "duration": int(t["trackTimeMillis"] / 1000) if t.get("trackTimeMillis") else None,
                "source": "itunes",
                "cover_xl": _art(t.get("artworkUrl100"), 1200),
                "track_no": t.get("trackNumber"),
                "year": release[:4] if len(release) >= 4 else None,
            }
        )
    return results
