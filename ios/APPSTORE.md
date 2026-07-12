# Songdrop — App Store submission copy

This is the customer-facing and reviewer-facing text for the iOS client. The
guiding principle: **Songdrop is a remote control for a music-library server the
user runs themselves.** The app ships inert, contains no catalog or content,
performs no downloading on the device, and does nothing until it is pointed at
the user's own server. Every string below is written to be accurate to that.

Nothing here claims the app restricts what a user can request — it doesn't, and
saying so would be false. It states what is true: the app is a content-neutral
controller with substantial legitimate uses, and the user is responsible for
what they add.

---

## App name
Songdrop

## Subtitle (30 char max)
Remote for your music server

## Promotional text (170 char max)
Search for a track, tap request, and your own self-hosted music server finds,
tags, and files it into your library — then it's ready in Plex when you get home.

## Description

Songdrop is a companion app for the self-hosted Songdrop server. If you run your
own music-library server at home, Songdrop lets you manage it from your phone:
look up a track, send a request, and watch it land in your library — properly
tagged, with artwork, in the playlist you chose.

The app is a remote control. It has no music, no catalog, and no content of its
own. It connects only to a Songdrop server that you install and run yourself, and
it does nothing until you enter your server's address and access key.

WHAT YOU CAN DO
• Search track metadata (title, artist, album, artwork) to fill in a request
• Send single-track or full-album requests to your server
• Browse full album track listings, including editions streaming services omit
• Watch request status update live, and get a notification when a track is ready
• Organize your library: tidy metadata, file tracks, and manage Plex playlists
• Configure and monitor your server's connections from Settings

WHAT YOU NEED
• A Songdrop server running on your own machine (open-source; setup guide online)
• A Plex media server for library and playlist management (optional)

Songdrop is a tool for managing music you are entitled to have in your own
library. You are responsible for the content you add and for respecting the
rights of copyright holders.

## Keywords (100 char max, comma-separated)
self-hosted,music library,plex,remote,server,metadata,playlist,home server,music manager,companion

## Support URL
https://github.com/<your-handle>/songdrop

## Marketing URL (optional)
https://github.com/<your-handle>/songdrop

---

## App Review notes (the important part)

> Songdrop is a **companion/remote-control app for a self-hosted server** that
> the user runs on their own hardware — the same model as a Transmission remote,
> a Plex client, or an Overseerr/Seerr client. It is analogous to a database or
> SSH client: a management UI over the user's own private API.
>
> **The app cannot be exercised without a backend the reviewer supplies.** On
> first launch it shows a setup screen requesting a server address and access
> key. With no server it does nothing. To evaluate it, please use the demo
> server below (or we can provide a fresh one on request):
>
>     Server address: https://<demo-host>
>     Access key:     <demo-key>
>
> **The app performs no downloading, streaming, or file transfer on the device.**
> Search results come from public music-metadata APIs (the same catalogs used by
> music-recognition and tagging apps) purely to help the user describe a request.
> A "request" is a message to the user's own server; all fetching, tagging, and
> library filing happen server-side, on the user's machine, over services the
> user configures there. The app binary contains no torrent, peer-to-peer, or
> media-download code.
>
> Intended use is managing a personal music library — organizing files the user
> owns, correcting metadata, and managing Plex playlists. The user is responsible
> for the content they add.
>
> Happy to answer any questions or hop on a call.

## Age rating
4+ (no objectionable content in the app itself). Answer the questionnaire
truthfully; there is no mature content, gambling, or user-generated content
displayed in-app.

## Privacy — App Privacy "Nutrition" answers
• **Data collection: None.** The app has no analytics, no accounts, no ads, and
  no third-party SDKs.
• The server address and access key are stored **on device** (UserDefaults/
  Keychain-eligible) and sent only to the server the user configured. They are
  not transmitted to the developer or any third party.
• Search queries go to public metadata APIs (Deezer, iTunes Search, MusicBrainz)
  and to the user's own server — declare "Search History: not collected/linked"
  since nothing is stored or tied to identity.
• Privacy policy: state plainly that Songdrop collects no personal data and
  communicates only with the user's self-hosted server and public metadata APIs.

---

## Things to keep OUT of the listing and UI (review risk)
- Names of specific acquisition backends (Soulseek/slskd, yt-dlp, torrent, Usenet).
  These are server-side implementation details and appear nowhere in the client.
- The words "download free music", "MP3 download", "rip", "pirate", "unlimited music".
- Screenshots that show any of the above, or any copyrighted catalog as if the
  app provides it. Screenshot the setup screen, a metadata search, and the
  request-status list.
- Any claim the app provides or streams music. It requests; the server provides.

## Distribution alternatives (no review at all)
For a personal, single-user tool this is often the pragmatic path:
- **PWA / home-screen web app** — the server can serve a web UI; add to home screen.
- **TestFlight** — up to 100 internal testers, lightweight review only.
- **Ad-hoc / free-developer sideload / AltStore** — no App Store review.
