"""Minimal async client for the slskd REST API (v0).

Auth: an API key (X-API-Key) if configured, otherwise username/password
login for a JWT, re-acquired automatically when it expires.
"""

import asyncio
import uuid

import httpx


class SlskdError(Exception):
    pass


class Slskd:
    def __init__(self, url: str, api_key: str = "", username: str = "", password: str = "") -> None:
        self.base = f"{url}/api/v0"
        self.api_key = api_key
        self.username = username
        self.password = password
        self._jwt = ""

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=30)

    async def _login(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            f"{self.base}/session",
            json={"username": self.username, "password": self.password},
        )
        if r.status_code != 200:
            raise SlskdError(f"slskd login failed: HTTP {r.status_code} {r.text[:200]}")
        self._jwt = r.json().get("token", "")
        if not self._jwt:
            raise SlskdError("slskd login succeeded but returned no token")

    async def _request(
        self, client: httpx.AsyncClient, method: str, path: str, **kwargs
    ) -> httpx.Response:
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        elif self.username:
            if not self._jwt:
                await self._login(client)
            headers["Authorization"] = f"Bearer {self._jwt}"
        r = await client.request(method, f"{self.base}{path}", headers=headers, **kwargs)
        if r.status_code == 401 and self.username and not self.api_key:
            # JWT expired; log in again and retry once.
            await self._login(client)
            headers["Authorization"] = f"Bearer {self._jwt}"
            r = await client.request(method, f"{self.base}{path}", headers=headers, **kwargs)
        return r

    async def app_state(self) -> dict:
        """slskd application info, including the Soulseek server connection state."""
        async with self._client() as client:
            r = await self._request(client, "GET", "/application")
            if r.status_code != 200:
                raise SlskdError(f"slskd returned HTTP {r.status_code}")
            return r.json()

    async def search(self, text: str, timeout: int = 90) -> list[dict]:
        """Run a search and return the list of peer responses.

        IMPORTANT: slskd's /searches/{id}/responses returns an EMPTY list until
        the search reaches a Completed state, even if peers have already
        responded — so we must wait for completion, not just for responses to
        exist. `searchTimeout` (ms) asks slskd to end the search sooner when
        responses stop arriving; searches that hit the response limit complete
        in a couple of seconds regardless.
        """
        sid = str(uuid.uuid4())
        async with self._client() as client:
            r = await self._request(
                client,
                "POST",
                "/searches",
                json={"id": sid, "searchText": text, "searchTimeout": 10000},
            )
            if r.status_code not in (200, 201):
                raise SlskdError(f"search create failed: HTTP {r.status_code} {r.text[:200]}")

            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                s = await self._request(client, "GET", f"/searches/{sid}")
                if s.status_code == 200 and str(s.json().get("state", "")).startswith("Completed"):
                    break
                await asyncio.sleep(1)

            resp = await self._request(client, "GET", f"/searches/{sid}/responses")
            responses = resp.json() if resp.status_code == 200 else []

            # Best-effort cleanup; slskd keeps finished searches around otherwise.
            try:
                await self._request(client, "DELETE", f"/searches/{sid}")
            except httpx.HTTPError:
                pass
        return responses or []

    async def enqueue(self, username: str, filename: str, size: int) -> None:
        async with self._client() as client:
            r = await self._request(
                client,
                "POST",
                f"/transfers/downloads/{username}",
                json=[{"filename": filename, "size": size}],
            )
            if r.status_code not in (200, 201):
                raise SlskdError(f"enqueue failed: HTTP {r.status_code} {r.text[:200]}")

    async def _find_transfer(
        self, client: httpx.AsyncClient, username: str, filename: str
    ) -> dict | None:
        r = await self._request(client, "GET", "/transfers/downloads")
        if r.status_code != 200:
            return None
        for user in r.json():
            if user.get("username") != username:
                continue
            for d in user.get("directories", []):
                for f in d.get("files", []):
                    if f.get("filename") == filename:
                        return f
        return None

    async def wait_for_download(self, username: str, filename: str, timeout: int = 900) -> str:
        """Poll until the transfer completes. Returns the final state string."""
        async with self._client() as client:
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                t = await self._find_transfer(client, username, filename)
                if t is not None:
                    state = str(t.get("state", ""))
                    if "Completed" in state:
                        return state
                await asyncio.sleep(3)
        return "TimedOut"

    async def cancel(self, username: str, filename: str) -> None:
        """Best-effort cancel + removal of a transfer."""
        async with self._client() as client:
            t = await self._find_transfer(client, username, filename)
            if t and t.get("id"):
                try:
                    await self._request(
                        client,
                        "DELETE",
                        f"/transfers/downloads/{username}/{t['id']}",
                        params={"remove": "true"},
                    )
                except httpx.HTTPError:
                    pass
