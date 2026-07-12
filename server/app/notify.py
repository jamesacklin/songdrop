"""Optional push notifications via ntfy."""

import logging

import httpx

log = logging.getLogger("songdrop.notify")


async def send(ntfy_url: str, title: str, body: str) -> None:
    if not ntfy_url:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(ntfy_url, content=body.encode(), headers={"Title": title})
    except httpx.HTTPError as e:
        log.warning("ntfy notification failed: %s", e)
