"""Candidate selection: score slskd search results for a requested track."""

import os
import re

EXT_SCORES = {".flac": 100, ".mp3": 60, ".m4a": 55, ".ogg": 50, ".opus": 50}
MIN_SIZE_BYTES = 500_000  # discard obvious clips/samples

# Alternate-version markers: heavily penalized when the user didn't ask for
# them, so the canonical recording wins (but variants remain as fallbacks).
VARIANT_TOKENS = {
    "remix", "rmx", "extended", "live", "acoustic", "instrumental",
    "karaoke", "demo", "cover", "edit", "remaster", "remastered", "version",
}


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", s.lower()) if len(t) > 1]


def score_file(file: dict, response: dict, artist: str, title: str) -> float | None:
    """Score one remote file; None means 'not a plausible match'."""
    filename = (file.get("filename") or "").replace("\\", "/")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in EXT_SCORES:
        return None
    if (file.get("size") or 0) < MIN_SIZE_BYTES:
        return None

    basename = filename.rsplit("/", 1)[-1].lower()
    title_tokens = _tokens(title)
    if not title_tokens:
        return None
    hits = sum(1 for t in title_tokens if t in basename)
    if hits / len(title_tokens) < 0.8:
        return None

    score = float(EXT_SCORES[ext])

    # Version qualifiers in the filename that the user didn't ask for
    # (e.g. "(extended version)", "live") knock the candidate down.
    base_tokens = set(_tokens(basename))
    unwanted = (base_tokens & VARIANT_TOKENS) - set(title_tokens)
    score -= 40 * len(unwanted)

    # Artist appearing anywhere in the path is a strong signal.
    artist_tokens = _tokens(artist)
    path_l = filename.lower()
    if artist_tokens and all(t in path_l for t in artist_tokens):
        score += 25

    bitrate = file.get("bitRate") or 0
    if ext == ".mp3":
        if bitrate >= 320:
            score += 20
        elif bitrate >= 256:
            score += 10
        elif 0 < bitrate < 192:
            score -= 25

    if response.get("hasFreeUploadSlot"):
        score += 15
    score += min((response.get("uploadSpeed") or 0) / 100_000, 10)
    score -= min((response.get("queueLength") or 0) * 2, 20)
    return score


def rank_candidates(responses: list[dict], artist: str, title: str) -> list[dict]:
    """Flatten responses into a ranked candidate list."""
    candidates = []
    for resp in responses:
        username = resp.get("username")
        if not username:
            continue
        for f in resp.get("files", []):
            s = score_file(f, resp, artist, title)
            if s is None:
                continue
            candidates.append(
                {
                    "score": s,
                    "username": username,
                    "filename": f["filename"],
                    "size": f.get("size") or 0,
                }
            )
    candidates.sort(key=lambda c: -c["score"])
    return candidates
