# Server core

The server is a FastAPI app (`server/app/`) that exposes the request API, persists
a SQLite-backed queue, serves the PWA, and runs a background worker. This document
covers the API, configuration, persistence, and startup. The acquisition pipeline
that the worker actually runs is documented separately in [pipeline.md](pipeline.md).

Entry point: `app.main:app` (`FastAPI(title="Songdrop", lifespan=lifespan)`), run
by `uvicorn` on port **8585**.

## Startup sequence

Initialization is split between module-import time and the FastAPI `lifespan`:

**At import (`main.py` module scope):**
1. Logging configured; logger `songdrop`.
2. `db = Database(settings.db_path)` — opens SQLite (`settings` is the singleton from `config.py`, already built from env vars).
3. `settings.apply_overrides(db.get_config())` — layers persisted runtime config (from the DB `config` table) over the env-var defaults, so a restarted container returns with the last-saved slskd/Plex settings.
4. **Access key resolution** — if `SONGDROP_API_KEY` is unset, reuse the persisted `api_key` from `/data`, else generate `secrets.token_urlsafe(24)` and persist it. Only an auto-generated/auto-reused key is remembered in `_auto_key` (an operator-supplied key is never logged).

**In `lifespan` (ASGI startup → shutdown):**
- Start the background worker: `asyncio.create_task(Worker(db).run())`.
- If the key was auto-generated, print a startup log banner with the key ("set `SONGDROP_API_KEY` to override").
- On shutdown, cancel and await the worker task (suppressing `CancelledError`).

**PWA mount (last line of `main.py`):** `app.mount("/", StaticFiles(directory=static, html=True))`. Mounted **last** so the `/api/*` routes registered earlier win route-matching; the static mount is the catch-all serving the PWA. Skipped if the `static/` dir isn't present.

## HTTP API

Every route except `/api/health` and the static mount depends on
`Depends(require_api_key)`.

| Method | Path | Auth | Body / params | Purpose |
| --- | --- | --- | --- | --- |
| GET | `/api/health` | — | — | Liveness probe → `{"ok": true}` |
| GET | `/api/status` | ✅ | — | Downstream health: slskd + Plex probed concurrently, plus `ytdlp_enabled` and the effective `paths` (music/plex/downloads). Built to diagnose the "ready but not in Plex" volume mismatch. |
| GET | `/api/config` | ✅ | — | Current runtime config (the 8 `RUNTIME_KEYS`) |
| PUT | `/api/config` | ✅ | `ConfigIn` (slskd/Plex fields + `ytdlp_enabled`, all optional) | Update connection settings; applied in-process immediately and persisted to the DB (no restart) |
| GET | `/api/search?q=` | ✅ | `q` | Metadata search — Deezer + iTunes in parallel, merged/deduped (≤40) |
| GET | `/api/album?artist=&album=` | ✅ | `artist`, `album` | Full tracklist — MusicBrainz first, Deezer fallback |
| GET | `/api/requests` | ✅ | — | List requests (≤200, newest first) + server `now` timestamp for clock-skew correction |
| GET | `/api/requests/{rid}` | ✅ | — | One request, or 404 |
| POST | `/api/requests` | ✅ | `RequestIn` (`artist`,`title` required; `album`,`deezer_id`,`playlist`,`cover_url`,`track_no`,`disc_no`,`year`,`youtube_url`) | Queue an acquisition (`mode='acquire'`) → 201 |
| POST | `/api/requests/bulk` | ✅ | `{requests: RequestIn[]}` (1–100) | Queue a whole album; skips tracks already in Plex or already live in the queue (atomic `add_request_if_absent`) → `{created, skipped}` |
| POST | `/api/requests/{rid}/retry` | ✅ | — | Re-queue a `failed`/`done`/`waiting` request (409 if actively in progress) |
| DELETE | `/api/requests/{rid}?purge=` | ✅ | `purge` | Remove a finished/failed/waiting/queued request (409 otherwise); `purge=true` on a `done` request also deletes the file from disk and scrubs it from Plex → 204 |
| POST | `/api/requests/clear` | ✅ | `{statuses: [...]}` (default `["done","failed"]`) | Bulk-remove finished requests (files left on disk) |
| POST | `/api/import` | ✅ | `ImportIn` (`path`,`artist`,`title` + metadata) | Tag a file already on disk and move it into Plex (`mode='import'`); 400 if `path` isn't a file |
| GET | `/api/playlists` | ✅ | — | Plex playlist titles (`[]` if Plex unconfigured, 502 on error) |

`youtube_url` on `RequestIn` is validated to be a **single** YouTube video (watch/shorts/embed or a `youtu.be/<id>`), never a playlist/channel — otherwise yt-dlp would fetch every entry.

## Authentication & key precedence

`require_api_key` compares the `X-API-Key` header to `settings.api_key`; if
`settings.api_key` is empty, auth is disabled (open). Precedence for the key,
resolved once at startup:

1. `SONGDROP_API_KEY` env var (wins outright if set),
2. else the persisted `api_key` in the DB `config` table (from a prior boot),
3. else auto-generate `secrets.token_urlsafe(24)` and persist it.

`api_key` is deliberately **not** in `RUNTIME_KEYS` — it's the bootstrap credential
the API authenticates with, so it can't be rotated through the very API it gates
(no lockout risk), and paths stay env-only because they're volume mounts.

## Configuration (`config.py`)

`Settings` reads all config from env at construction. Notable env vars and defaults:

- **slskd:** `SLSKD_URL` (`http://localhost:5030`), `SLSKD_API_KEY`, `SLSKD_USERNAME`, `SLSKD_PASSWORD`, `SLSKD_DOWNLOADS_DIR` (`/downloads`).
- **Plex:** `PLEX_URL`, `PLEX_TOKEN`, `PLEX_SECTION` (auto-detected if blank).
- **Paths:** `MUSIC_LIBRARY_DIR` (`/music`), `PLEX_LIBRARY_DIR` (falls back to `MUSIC_LIBRARY_DIR`) — the two differ when Plex sees the library at a different container path.
- **Behavior:** `YTDLP_ENABLED` (`true`), `SEARCH_TIMEOUT` (`90`), `DOWNLOAD_TIMEOUT` (`900`), `MAX_CANDIDATES` (`3`), `RETRY_INTERVAL` (`600`), `MAX_SEARCH_RETRIES` (`0` = unlimited).
- **Other:** `SONGDROP_API_KEY`, `DATABASE_PATH` (`/data/songdrop.db` in the image), `NTFY_URL`.

`RUNTIME_KEYS` — the 8 fields editable at runtime via `PUT /api/config`:
`slskd_url`, `slskd_api_key`, `slskd_username`, `slskd_password`, `plex_url`,
`plex_token`, `plex_section`, `ytdlp_enabled`. `apply_overrides()` ignores unknown
or `None` keys, coerces `ytdlp_enabled` to bool, strips `_url` values; changes take
effect in-process immediately and `PUT` also persists the normalized values to the DB.

## Persistence (`db.py`)

A single `sqlite3` connection (`check_same_thread=False`, `Row` factory) guarded by
a `threading.Lock` on every access — serializing the worker task and the API
coroutines.

**`requests` table** — the queue/history. Key columns: `id`, `created_at`,
`updated_at`, `mode` (`acquire`|`import`), `artist`, `title`, `album`, `playlist`,
`deezer_id`, `source_path` (for imports), `status`, `detail`, `error`, `file_path`,
`next_retry_at`, `retry_count`, and tagging metadata (`cover_url`, `track_no`,
`disc_no`, `year`, `youtube_url`). Missing columns on older DBs are added on boot
via an idempotent `MIGRATIONS` map.

**`config` table** — flat `key`/`value` TEXT store backing persisted runtime
overrides and the auto-generated `api_key`.

**Status vocabulary:** `queued → searching → downloading → tagging → importing →
done`; `searching → waiting` (nothing found, retried when `next_retry_at` passes);
any → `failed`. `ACTIVE_STATUSES = (searching, downloading, tagging, importing)`.

**Queue dequeue** — `next_ready()` returns the next `queued` row, or a `waiting`
row whose `next_retry_at` has passed, ordering fresh `queued` ahead of due retries
so a retry backlog can't starve new work.

**Restart recovery** — `reset_stale()` re-queues anything left in an `ACTIVE_STATUS`
by a previous run (`detail = 'requeued after restart'`), so a crash/deploy mid-flight
doesn't lose work.

Notable helpers: `add_request` / `add_request_if_absent` (atomic dup-check + insert
for bulk), `has_similar` (case-insensitive artist+title, ignores `failed`),
`update(**fields)`, `delete`, `delete_by_statuses` (clear), `get_config`/`set_config`
(upsert).

## Request models (`models.py`)

Two Pydantic models: `RequestIn` (acquisition; `artist`/`title` required, plus
optional metadata and the validated `youtube_url`) and `ImportIn` (on-disk import;
adds required `path`). Small inline models `ConfigIn`, `BulkRequestIn`, and `ClearIn`
live in `main.py`.

## Downstream clients (`clients.py`)

- `get_slskd()` memoizes one `Slskd` instance (it caches a JWT session), keyed on
  the 4-tuple of slskd connection settings; when `PUT /api/config` changes any of
  them, the next call rebuilds the client — no explicit invalidation needed.
- `get_plex()` builds a fresh stateless `Plex` client per call.

## Notifications (`notify.py`)

`send(ntfy_url, title, body)` POSTs to an [ntfy](https://ntfy.sh) topic (title in
the `Title` header, body as content, 10s timeout). No-ops when `NTFY_URL` is unset;
failures are logged, never raised, so a failed push never breaks the pipeline.

## Container

`python:3.12-slim`, `WORKDIR /app`, deps installed before code (layer caching),
`ENV DATABASE_PATH=/data/songdrop.db`, `VOLUME /data`, `EXPOSE 8585`,
`CMD uvicorn app.main:app --host 0.0.0.0 --port 8585`. Deps: `fastapi`, `uvicorn[standard]`,
`httpx`, `mutagen`, `yt-dlp` (`sqlite3` is stdlib; `pydantic` is transitive).
