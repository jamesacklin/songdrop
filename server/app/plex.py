"""Minimal async Plex client: partial scans, track lookup, playlist management."""

import asyncio

import httpx


class PlexError(Exception):
    pass


class Plex:
    def __init__(self, url: str, token: str, section_name: str = "") -> None:
        self.url = url
        self.token = token
        self.section_name = section_name

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.url,
            headers={"X-Plex-Token": self.token, "Accept": "application/json"},
            timeout=30,
        )

    @property
    def configured(self) -> bool:
        return bool(self.url and self.token)

    async def music_section_id(self) -> str:
        async with self._client() as client:
            r = await client.get("/library/sections")
            r.raise_for_status()
            sections = r.json()["MediaContainer"].get("Directory", [])
        for s in sections:
            if s.get("type") == "artist" and (
                not self.section_name or s.get("title") == self.section_name
            ):
                return str(s["key"])
        raise PlexError("no music library section found")

    async def machine_id(self) -> str:
        async with self._client() as client:
            r = await client.get("/identity")
            r.raise_for_status()
            return r.json()["MediaContainer"]["machineIdentifier"]

    async def refresh_path(self, section_id: str, path: str) -> None:
        """Partial scan of a single directory."""
        async with self._client() as client:
            r = await client.get(f"/library/sections/{section_id}/refresh", params={"path": path})
            r.raise_for_status()

    async def find_track(self, section_id: str, title: str, artist: str) -> str | None:
        """Return the ratingKey of a track matching title+artist, if present."""
        async with self._client() as client:
            r = await client.get(
                f"/library/sections/{section_id}/all",
                params={"type": "10", "title": title},
            )
            if r.status_code != 200:
                return None
            tracks = r.json()["MediaContainer"].get("Metadata", []) or []
        artist_l = artist.lower()
        for t in tracks:
            track_artist = (t.get("grandparentTitle") or t.get("originalTitle") or "").lower()
            if artist_l in track_artist or track_artist in artist_l:
                return str(t["ratingKey"])
        return None

    async def wait_for_track(
        self, section_id: str, title: str, artist: str, timeout: int = 90
    ) -> str | None:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            key = await self.find_track(section_id, title, artist)
            if key:
                return key
            await asyncio.sleep(5)
        return None

    async def delete_item(self, rating_key: str) -> bool:
        """Delete a library item via Plex. Requires 'Allow media deletion' on the
        server; returns False if Plex refuses so the caller can fall back."""
        async with self._client() as client:
            r = await client.delete(f"/library/metadata/{rating_key}")
            return r.status_code in (200, 204)

    async def empty_trash(self, section_id: str) -> None:
        async with self._client() as client:
            r = await client.put(f"/library/sections/{section_id}/emptyTrash")
            r.raise_for_status()

    async def playlists(self) -> list[dict]:
        async with self._client() as client:
            r = await client.get("/playlists", params={"playlistType": "audio"})
            r.raise_for_status()
            items = r.json()["MediaContainer"].get("Metadata", []) or []
        return [
            {"title": p["title"], "ratingKey": str(p["ratingKey"])}
            for p in items
            if not p.get("smart")
        ]

    async def add_to_playlist(self, playlist_name: str, rating_key: str) -> None:
        """Add a track to a playlist by name, creating the playlist if needed."""
        machine = await self.machine_id()
        uri = f"server://{machine}/com.plexapp.plugins.library/library/metadata/{rating_key}"
        existing = {p["title"]: p["ratingKey"] for p in await self.playlists()}
        async with self._client() as client:
            if playlist_name in existing:
                r = await client.put(
                    f"/playlists/{existing[playlist_name]}/items", params={"uri": uri}
                )
            else:
                r = await client.post(
                    "/playlists",
                    params={"type": "audio", "title": playlist_name, "smart": "0", "uri": uri},
                )
            r.raise_for_status()
