"""Metadata tagging (mutagen) and library file organization."""

import os
import re
import shutil
from dataclasses import dataclass

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis

AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".wav", ".aiff"}


@dataclass
class TrackMeta:
    title: str
    artist: str
    album: str | None = None
    album_artist: str | None = None
    track_no: int | None = None
    disc_no: int | None = None
    year: str | None = None
    cover: bytes | None = None
    cover_mime: str = "image/jpeg"


def _sanitize(part: str) -> str:
    """Make a string safe as a single path component."""
    part = re.sub(r'[\\/:*?"<>|]', "_", part).strip().strip(".")
    return part or "Unknown"


def tag_file(path: str, meta: TrackMeta) -> None:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".flac":
        _tag_flac(path, meta)
    elif ext == ".mp3":
        _tag_mp3(path, meta)
    elif ext in (".m4a", ".mp4"):
        _tag_mp4(path, meta)
    elif ext in (".ogg", ".opus"):
        _tag_vorbis(path, meta)
    # Other formats: skip tagging rather than fail the whole request.


def _tag_flac(path: str, meta: TrackMeta) -> None:
    audio = FLAC(path)
    audio["title"] = meta.title
    audio["artist"] = meta.artist
    if meta.album:
        audio["album"] = meta.album
    if meta.album_artist:
        audio["albumartist"] = meta.album_artist
    if meta.track_no:
        audio["tracknumber"] = str(meta.track_no)
    if meta.disc_no:
        audio["discnumber"] = str(meta.disc_no)
    if meta.year:
        audio["date"] = meta.year
    if meta.cover:
        pic = Picture()
        pic.type = 3  # front cover
        pic.mime = meta.cover_mime
        pic.data = meta.cover
        audio.clear_pictures()
        audio.add_picture(pic)
    audio.save()


def _tag_mp3(path: str, meta: TrackMeta) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.setall("TIT2", [TIT2(encoding=3, text=meta.title)])
    tags.setall("TPE1", [TPE1(encoding=3, text=meta.artist)])
    if meta.album:
        tags.setall("TALB", [TALB(encoding=3, text=meta.album)])
    if meta.album_artist:
        tags.setall("TPE2", [TPE2(encoding=3, text=meta.album_artist)])
    if meta.track_no:
        tags.setall("TRCK", [TRCK(encoding=3, text=str(meta.track_no))])
    if meta.disc_no:
        tags.setall("TPOS", [TPOS(encoding=3, text=str(meta.disc_no))])
    if meta.year:
        tags.setall("TDRC", [TDRC(encoding=3, text=meta.year)])
    if meta.cover:
        tags.setall(
            "APIC",
            [APIC(encoding=3, mime=meta.cover_mime, type=3, desc="Cover", data=meta.cover)],
        )
    tags.save(path)


def _tag_mp4(path: str, meta: TrackMeta) -> None:
    audio = MP4(path)
    audio["\xa9nam"] = [meta.title]
    audio["\xa9ART"] = [meta.artist]
    if meta.album:
        audio["\xa9alb"] = [meta.album]
    if meta.album_artist:
        audio["aART"] = [meta.album_artist]
    if meta.track_no:
        audio["trkn"] = [(meta.track_no, 0)]
    if meta.disc_no:
        audio["disk"] = [(meta.disc_no, 0)]
    if meta.year:
        audio["\xa9day"] = [meta.year]
    if meta.cover:
        fmt = MP4Cover.FORMAT_PNG if meta.cover_mime == "image/png" else MP4Cover.FORMAT_JPEG
        audio["covr"] = [MP4Cover(meta.cover, imageformat=fmt)]
    audio.save()


def _tag_vorbis(path: str, meta: TrackMeta) -> None:
    audio = OggVorbis(path)
    audio["title"] = meta.title
    audio["artist"] = meta.artist
    if meta.album:
        audio["album"] = meta.album
    if meta.album_artist:
        audio["albumartist"] = meta.album_artist
    if meta.track_no:
        audio["tracknumber"] = str(meta.track_no)
    if meta.year:
        audio["date"] = meta.year
    audio.save()


def library_destination(library_root: str, meta: TrackMeta, src_path: str) -> str:
    """Compute {root}/{Album Artist}/{Album}/{NN - Title}{ext}."""
    ext = os.path.splitext(src_path)[1].lower()
    artist_dir = _sanitize(meta.album_artist or meta.artist)
    album_dir = _sanitize(meta.album or "Singles")
    prefix = f"{meta.track_no:02d} - " if meta.track_no else ""
    filename = f"{prefix}{_sanitize(meta.title)}{ext}"
    return os.path.join(library_root, artist_dir, album_dir, filename)


def move_into_library(src_path: str, dest_path: str) -> str:
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    if os.path.abspath(src_path) == os.path.abspath(dest_path):
        return dest_path
    # Never clobber an existing library file; suffix instead.
    final = dest_path
    base, ext = os.path.splitext(dest_path)
    n = 1
    while os.path.exists(final):
        final = f"{base} ({n}){ext}"
        n += 1
    shutil.move(src_path, final)
    return final


def find_downloaded_file(
    downloads_dir: str, remote_filename: str, size: int | None = None
) -> str | None:
    """Locate a completed slskd download on disk by its remote basename.

    slskd may write the file as `{stem}_{transferid}{ext}` locally, so accept
    an optional `_<digits>` suffix. Prefer an exact size match, then recency.
    """
    target = remote_filename.replace("\\", "/").rsplit("/", 1)[-1]
    stem, ext = os.path.splitext(target.lower())
    pattern = re.compile(re.escape(stem) + r"(?:_\d+)?" + re.escape(ext) + r"$")
    matches: list[tuple[int, float, str]] = []
    for root, _dirs, files in os.walk(downloads_dir):
        for name in files:
            if not pattern.fullmatch(name.lower()):
                continue
            full = os.path.join(root, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            size_match = 1 if (size is not None and st.st_size == size) else 0
            matches.append((size_match, st.st_mtime, full))
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][2]
