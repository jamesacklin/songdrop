# Acquisition pipeline

This is the heart of Songdrop: how a queued request becomes a tagged file in Plex.
The background `Worker` (`worker.py`) drains the SQLite queue and runs each request
through search → download → tag → move → Plex scan → playlist. Metadata comes from
Deezer/iTunes/MusicBrainz; audio comes from slskd (Soulseek) with a yt-dlp fallback.

```
acquire:  slskd search → pick candidate → download → tag → move → Plex scan → playlist
import:   (file already on disk)                    → tag → move → Plex scan → playlist
```

## Worker loop & state machine

`Worker.run()` is an infinite loop that survives any exception (logs and sleeps 5s).
Each `_tick()` pulls one ready request (`db.next_ready()`), or idles 2s if none. On
startup it runs `db.reset_stale()` once, re-queuing anything an earlier run left
mid-flight.

Status transitions (strings set by the worker):

```
queued → searching → downloading → tagging → importing → done
searching → waiting        (nothing found; retried when next_retry_at passes)
any       → failed         (error set)
```

`detail` is updated at each step with human text ("searching Soulseek", "downloading
from {peer} (attempt N)", "tagging metadata", "scanning into Plex", …). `mode` is a
request field, not a status: `acquire` (default) runs the full pipeline; `import`
skips straight to tagging a file at `source_path`.

**Retries.** Failures raise `PipelineError(msg, retryable=bool)`. Retryable errors
(slskd network errors, or fallback exhaustion when YouTube is off/empty) move the
request to `waiting` with `next_retry_at = now + RETRY_INTERVAL` (default 600s) and
increment `retry_count`. `_should_retry()` allows unlimited retries when
`MAX_SEARCH_RETRIES == 0` (the default — the user deletes the request to stop),
otherwise caps at that count. `next_ready()` prioritizes fresh `queued` rows over
due `waiting` rows so retries never starve new work; `/api/requests` returns a server
`now` so clients render an accurate countdown. Non-retryable errors → `failed`.

## `acquire()` — source selection

Returns `(local_path, source_label)`. Order of preference:

1. **Explicit `youtube_url`** on the request → `ytdl.download_url()`. A specific link
   failing (removed/region-locked) is non-retryable. Source label: `"YouTube link"`.
2. **Soulseek** → `slskd.search("{artist} {title}")`, `scoring.rank_candidates()`,
   then try the top `MAX_CANDIDATES` (default 3) in score order: `enqueue` →
   `wait_for_download` → verify the file landed. First success returns
   `(path, "Soulseek")`. The slskd client is captured once up front so a mid-pipeline
   config change can't enqueue on one instance and poll another.
3. **YouTube fallback** (`_youtube_fallback`) — if Soulseek had no candidates or all
   attempts failed. Gated by `YTDLP_ENABLED`; when off it raises retryable instead.
   Passes a `duration_hint` (from Deezer track details, if a `deezer_id` is known) to
   improve matching. Source label: `"YouTube (~128kbps AAC)"`.

## `process()` and the honest final status

After `acquire()` (or, for imports, verifying `source_path` exists), the worker tags
the file (tagging failure is non-fatal — it imports untagged with a warning in
`detail`), moves it into the library, then calls `plex_import()`, which returns a
three-way result that drives an **honest** final `detail`:

| `plex_import` result | Final `detail` |
| --- | --- |
| `None` (Plex not configured) | `saved to your library (Plex not configured) · {source}` |
| `True` (verified in Plex) | `ready to play · {source}` (or a playlist-add warning note) |
| `False` (filed but not indexed) | `filed at {path}, but Plex hasn't indexed it — check … volume mount / PLEX_LIBRARY_DIR` |

Status is `done` in all three cases — failing to *verify* Plex indexing isn't a
pipeline failure, just surfaced truthfully (this is the fix for the original "says
ready but isn't in Plex" bug). A push notification is sent via ntfy, titled "track
ready" or "needs attention".

**Bulk** (`POST /api/requests/bulk`, ≤100 tracks): resolves the Plex section once,
skips tracks already in the library (`plex.find_track`) or already live in the queue
(atomic `add_request_if_absent`), so "Request All" on a half-owned album fetches only
what's missing.

## Metadata search

- **`/api/search`** runs `deezer.search_tracks` + `itunes.search_tracks` concurrently
  and merges them (`merge_results`): Deezer first, dedup on lowercased `(artist,title)`,
  capped at 40. Both use keyless public APIs (`api.deezer.com`, `itunes.apple.com`);
  iTunes fills gaps Deezer misses (remixes/compilations) and vice-versa.
- **`/api/album`** tries **MusicBrainz** first (`mb.find_album`) — it catalogs editions
  streaming services omit. It picks the best release (prefers `Official`, then highest
  track-count), rate-limits to ~1 req/s, reconstructs multi-artist credits from
  `artist-credit` join phrases, handles **multi-disc** (per-disc track numbers, so disc
  2 track 1 tags as track 1/disc 2), and points covers at Cover Art Archive
  (`front-500`/`front-1200`, which may 404). Falls back to `deezer.find_album` (paging
  past Deezer's ~25-track embed cap). MusicBrainz requests carry a required
  `User-Agent: Songdrop/1.0 (...)`.

## slskd client (`slskd.py`)

Async client for the slskd REST API v0. **Auth:** `X-API-Key` if `SLSKD_API_KEY` is
set, otherwise username/password login for a JWT, transparently re-acquired on a 401.

The critical gotcha, handled in `search()`: slskd's `/searches/{id}/responses` returns
an **empty list until the search reaches a `Completed` state** — so it creates the
search (`searchTimeout` 10s to end early when responses stop), polls
`/searches/{id}` every 1s until `state` starts with `Completed` (overall budget =
`SEARCH_TIMEOUT`, default 90s, chosen to exceed slskd's own ~40s search lifetime),
*then* reads responses and cleans up the search.

Download: `enqueue()` posts the batch download; `wait_for_download()` polls transfers
every 3s (budget `DOWNLOAD_TIMEOUT`, default 900s) until the state contains `Completed`
(caller checks for `Succeeded`); `cancel()` cleans up failed transfers.

**Finding the file** (`tagger.find_downloaded_file`): slskd may write
`{stem}_{transferid}{ext}`, so it matches with an anchored regex
`re.escape(stem) + r"(?:_\d+)?" + re.escape(ext) + r"$"` over `os.walk(downloads_dir)`,
normalizing Windows-style remote paths, and ranks matches by **exact size** first then
recency. A "download completed but file not found" error points at a volume-mapping
mistake.

## Candidate scoring (`scoring.py`)

`score_file()` disqualifies (returns `None`) files whose extension isn't audio, that
are under `MIN_SIZE_BYTES` (500 KB), or whose title-token match against the filename is
below 0.8. Otherwise it scores:

- **Format base:** FLAC 100, MP3 60, M4A 55, OGG/Opus 50 (`EXT_SCORES`).
- **Variant penalty:** −40 per unwanted token (`remix/live/acoustic/instrumental/…`)
  not in the requested title.
- **Artist in path:** +25 if all artist tokens appear in the full path.
- **MP3 bitrate:** ≥320 → +20, 256–319 → +10, 1–191 → −25.
- **Peer quality:** free upload slot +15; upload speed up to +10; queue length up to −20.

No minimum floor — every non-disqualified candidate is ranked. `rank_candidates()`
flattens all peer files and sorts by descending score.

## YouTube fallback scoring (`ytdl.py`)

Downloads `bestaudio[ext=m4a]/bestaudio` (no ffmpeg needed; ~128 kbps AAC — a last
resort, not a FLAC replacement). Searches `ytsearch6:{artist} {title}` (flat extract).
`score_video()` disqualifies out-of-range durations (60s–20min), poor title matches
(<0.8), then scores from 50:

- **Artist match** (title or channel) +20; **"Artist - Topic" channel** +25 (album
  audio); **"official audio"** +15 / **"audio"** +5.
- **Unwanted tokens** (`live/cover/karaoke/remix/nightcore/…`) −40 each.
- **Duration hint:** within 15s +25, within 30s +10, off by >90s −30.

`pick_video()` keeps only videos scoring ≥ `MIN_SCORE` (30) — importing the wrong
recording tagged as the original is worse than retrying. The tokenizer is Unicode-aware
(keeps single non-ASCII glyphs) so CJK/Cyrillic titles work. `youtube_url` on a request
is validated to a single video (never a playlist).

## Tagging (`tagger.py`)

`TrackMeta` (title, artist, album, album_artist, track/disc no, year, cover bytes+mime)
is written per format: **FLAC** (Vorbis comments + front-cover Picture), **MP3**
(ID3v2 TIT2/TPE1/TALB/TPE2/TRCK/TPOS/TDRC + APIC, UTF-8), **M4A/MP4** (iTunes atoms +
MP4Cover PNG/JPEG). `.ogg`/`.opus` get text tags but no disc number and no cover art;
WAV/AIFF are recognized as audio but not tagged. Tagging failure never discards the
file.

Metadata precedence: **Deezer track details > request fields**; cover precedence:
**Deezer track cover > request-supplied `cover_url`** (iTunes results ride in via the
request's `cover_url`).

`library_destination()` computes `{root}/{Album Artist}/{Album}/{NN - Title}{ext}`
(falls back to the track artist, an album folder of `Singles`, and drops the `NN - `
prefix when there's no track number). `move_into_library()` never clobbers — it
appends ` (n)` on collision.

## Plex import (`plex.py`)

Only runs when `configured` (URL + token). Sets status `importing`, then:

1. **Path mapping:** the album dir is translated from `MUSIC_LIBRARY_DIR` (what the
   server writes to) to `PLEX_LIBRARY_DIR` (what Plex sees) by swapping the root and
   preserving the `{Album Artist}/{Album}` subpath — for when the two containers mount
   the same library at different paths.
2. **Partial scan:** `GET /library/sections/{id}/refresh?path={plex_dir}` — just that
   album folder, not the whole library.
3. **Verification:** `wait_for_track()` polls `/library/sections/{id}/all?type=10`
   every 5s (worker uses a 60s timeout), matching artist by tolerant substring. Returns
   `False` with an honest note if the track never appears (the volume/`PLEX_LIBRARY_DIR`
   diagnostic).
4. **Playlist:** if requested, appends to the named playlist or creates it (non-smart,
   audio); a playlist failure is non-fatal (still `True`, annotated in the note).

Section selection uses the first `artist`-type section, or the one named `PLEX_SECTION`.
Request deletion with `purge=true` also uses Plex `delete_item`/`empty_trash`, falling
back to filesystem deletion if Plex disallows media deletion.
