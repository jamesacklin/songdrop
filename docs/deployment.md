# Deployment & operations

How Songdrop's three deliverables — the **server** (Docker image), the **marketing
site** (Cloudflare Pages), and the **iOS app** (TestFlight) — are built, shipped,
and run. No secrets are in this repo; see [Secrets](#secrets) for where each lives.

Quick command reference lives in [AGENTS.md](../AGENTS.md); this document explains
how the pieces fit together and why.

---

## Server

### Published image

The server is published as **`jamesacklin/songdrop`** on Docker Hub — a public,
multi-arch image (`linux/amd64` + `linux/arm64`), tagged `:latest` and a version
tag. It is built from [`server/Dockerfile`](../server/Dockerfile) (python:3.12-slim,
`WORKDIR /app`, `CMD uvicorn app.main:app --host 0.0.0.0 --port 8585`).

Multi-arch publishing requires a buildx `docker-container` builder (Docker Desktop
running):

```sh
docker buildx build --builder <container-builder> \
  --platform linux/amd64,linux/arm64 \
  -t jamesacklin/songdrop:<ver> -t jamesacklin/songdrop:latest \
  --push server/
```

> A freshly created Docker Hub repository defaults to **private** — flip it to
> public in the Hub UI or `docker pull` fails for everyone.

### Volumes (the part that bites people)

| Container path | Holds | Must map to |
| --- | --- | --- |
| `/data` | SQLite queue + auto-generated access key | any persistent volume |
| `/music` | filed tracks (`Artist/Album/NN - Title.ext`) | **the exact folder Plex scans** |
| `/downloads` | where slskd writes completed files | **slskd's completed-downloads folder** |

The #1 failure mode: if `/music` is not the same underlying folder Plex indexes,
tracks acquire and file successfully but never appear in Plex (and if `/music`
isn't mounted at all, they vanish on the next `docker rm`). When Plex and Songdrop
are separate containers mounting the same host folder at *different* container
paths, set `PLEX_LIBRARY_DIR` to the path Plex uses so partial scans target the
right directory.

### Configuration

Two layers, env wins over nothing and runtime-config wins over env for the keys it
covers:

- **Env vars** at container start (`SLSKD_URL`, `SLSKD_USERNAME`/`SLSKD_PASSWORD`
  or `SLSKD_API_KEY`, `PLEX_URL`, `PLEX_TOKEN`, `MUSIC_LIBRARY_DIR`,
  `PLEX_LIBRARY_DIR`, `SLSKD_DOWNLOADS_DIR`, `SONGDROP_API_KEY`, `YTDLP_ENABLED`, …).
- **Runtime config** via `PUT /api/config` — slskd/Plex settings + `ytdlp_enabled`
  persist in the DB and apply without a restart. See [server.md](server.md).

The **access key** (`SONGDROP_API_KEY`) is optional: leave it unset and the server
generates one on first boot, persists it in `/data`, and prints it to the logs.
The env var takes precedence over the persisted key (the persisted key is only a
fallback), so setting `SONGDROP_API_KEY` reliably pins the key.

### docker compose (local / self-host from source)

[`docker-compose.yml`](../docker-compose.yml) runs **slskd + Songdrop together**
and wires the volumes. `slskd` uses the upstream `slskd/slskd:latest` image;
`songdrop` builds from `./server`. Copy `.env.example` → `.env`, set
`MUSIC_LIBRARY_PATH` (host path to the Plex music folder), Plex creds, and slskd
creds, then `docker compose up -d`.

---

## Production: TrueNAS SCALE

The live instance runs as a TrueNAS **custom app** named `songdrop` that **pulls
the published image** `jamesacklin/songdrop:latest` (it previously ran from
bind-mounted source; it was switched to the image). TrueNAS is reached over
Tailscale.

### The management API

TrueNAS SCALE exposes a **JSON-RPC 2.0 API over WebSocket** at
`ws://<host>/api/current`. Authenticate with the method `auth.login_with_api_key`
(passing a TrueNAS API key), then call:

| Method | Purpose |
| --- | --- |
| `app.query [["id","=","songdrop"]] {}` | app state (`RUNNING`/`DEPLOYING`/…) |
| `app.config "songdrop"` | the current resolved docker-compose (services dict) |
| `app.update "songdrop" {custom_compose_config: {...}}` | replace the compose; returns a **job id** |
| `core.get_jobs [["id","=",<jid>]] {}` | poll the update job to `SUCCESS` |

`app.update` triggers a redeploy (pull + recreate). The safe redeploy pattern is:
read `app.config`, mutate exactly the field you need, push it back via
`app.update`, poll the job, verify `app.query` returns `RUNNING` and
`http://<host>:8585/api/health` returns `{"ok":true}`.

### The custom-app compose

The app's compose sets `image: jamesacklin/songdrop:latest`, the env (Plex/slskd
creds + `SONGDROP_API_KEY`), `ports: ["8585:8585"]`, a healthcheck hitting
`/api/health`, and host volume mounts of the form:

```
/mnt/apps/appdata/songdrop/data      -> /data
/mnt/fort/files/Downloads            -> /downloads
/mnt/fort/music                      -> /music
```

`PLEX_LIBRARY_DIR` is set (Plex mounts the same music folder at a different
container path than Songdrop does). Env values live in the TrueNAS app config,
**not** in this repo.

---

## Marketing site: Cloudflare Pages

[`site/`](../site) is a static two-file page — `index.html` + `editorial.css` —
styled with the **`@ackl/editorial`** design system (content-first, left-aligned,
Arimo webfont, `--ed-*` tokens, dark-mode aware). No build step; `index.html`
links `./editorial.css` and uses its CSS variables, so **both files must ship
together**.

- **Pages project:** `songdrop`; **custom domain:** `songdrop.ackl.in` (zone
  `ackl.in`), a proxied CNAME → `songdrop.pages.dev`.
- **Redeploy:** [`deploy-site.sh`](../deploy-site.sh) —
  `CLOUDFLARE_API_TOKEN=… CLOUDFLARE_ACCOUNT_ID=… ./deploy-site.sh`. It runs
  `npx wrangler pages deploy site` (whole dir, so `editorial.css` goes too). The
  token needs Account · Cloudflare Pages · Edit, plus Zone · DNS · Edit + Zone ·
  Read on `ackl.in` to manage the custom domain.
- The **TestFlight join link** in the page must match the current app's build.

---

## iOS app: TestFlight

Generate the Xcode project first: `cd ios && xcodegen generate` (the `.xcodeproj`
is gitignored — always regenerate it from [`project.yml`](../ios/project.yml)).

### Identity — read this before touching signing

- **Bundle ID: `com.jamesacklin.songdropapp`.** The original
  `com.jamesacklin.songdrop` is **permanently burned** — an App Store Connect app
  on it was deleted, and Apple never lets a deleted app's bundle id be reused (it
  won't even appear in the New App dropdown).
- **Two Apple teams — do not mix them:**
  - `FTFY9QQ2XQ` — the **paid** Developer Program team (ASC provider `142171647`,
    "James Acklin"). Owns the app record, bundle id, distribution cert, and the
    App Store Connect API key. Everything distribution uses this.
  - `4S2D335HW6` — the free personal team (dev only). `project.yml` lists it as
    `DEVELOPMENT_TEAM`, but the fastlane lane overrides signing to `FTFY9QQ2XQ`.
  - Create the app under the **James Acklin** App Store Connect account, not Tlon
    Corporation (the same Apple ID can access both).

### Ship

Lanes live in [`ios/fastlane/Fastfile`](../ios/fastlane/Fastfile), driven by an
App Store Connect API key (no Apple ID login required):

```sh
cd ios
export ASC_KEY_ID=… ASC_ISSUER_ID=… \
       ASC_KEY_PATH=~/.appstoreconnect/private_keys/AuthKey_<id>.p8
fastlane build     # dist cert + App Store profile + signed .ipa
fastlane upload    # upload_to_testflight via the API key
```

Bump `MARKETING_VERSION` + `CURRENT_PROJECT_VERSION` in `project.yml` per release.
Export compliance is pre-answered (`ITSAppUsesNonExemptEncryption=false`).

### Signing gotchas (all hit on first ship)

1. **App records can't be created programmatically.** The ASC API forbids it
   (`apps` disallows CREATE) and fastlane `produce` needs an Apple ID login →
   create the app manually in App Store Connect (bundle-id *registration* is fine
   via `POST /v1/bundleIds`).
2. **codesign hangs on a keychain prompt** on headless/first-time machines. Fix:
   import the dist cert+key into a dedicated keychain with a known password, run
   `security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k <pw> <kc>`,
   and put it first in `security list-keychains -d user -s`.
3. **Xcode 16+ profile location.** Profiles must live in
   `~/Library/Developer/Xcode/UserData/Provisioning Profiles/`; `sigh` installs to
   the legacy path, so the Fastfile copies it across.

---

## Secrets

None are committed. Where they live:

| Secret | Location |
| --- | --- |
| ASC API key (`.p8`) | `~/.appstoreconnect/private_keys/AuthKey_<id>.p8` (local; Apple allows one download) |
| Plex token, slskd creds, `SONGDROP_API_KEY` | TrueNAS app config; local `.env` for compose (`.env` gitignored) |
| Cloudflare API token + account id | passed to `deploy-site.sh` via env |
| TrueNAS API key | supplied at deploy time |

Signing artifacts (`ios/*.p12`, `*.cer`, `*.mobileprovision`, `ios/build/`) and
fastlane run output are gitignored.
