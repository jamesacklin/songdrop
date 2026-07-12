"""SQLite persistence for the request queue."""

import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    mode TEXT NOT NULL DEFAULT 'acquire',          -- 'acquire' (slskd) or 'import' (file on disk)
    deezer_id INTEGER,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    album TEXT,
    playlist TEXT,
    source_path TEXT,                              -- for mode='import'
    status TEXT NOT NULL DEFAULT 'queued',
    detail TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT '',
    next_retry_at REAL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    cover_url TEXT,
    track_no INTEGER,
    disc_no INTEGER,
    year TEXT,
    youtube_url TEXT
);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Columns added after the initial release; applied to pre-existing databases.
MIGRATIONS = {
    "next_retry_at": "ALTER TABLE requests ADD COLUMN next_retry_at REAL",
    "retry_count": "ALTER TABLE requests ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
    "cover_url": "ALTER TABLE requests ADD COLUMN cover_url TEXT",
    "track_no": "ALTER TABLE requests ADD COLUMN track_no INTEGER",
    "year": "ALTER TABLE requests ADD COLUMN year TEXT",
    "youtube_url": "ALTER TABLE requests ADD COLUMN youtube_url TEXT",
    "disc_no": "ALTER TABLE requests ADD COLUMN disc_no INTEGER",
}

# Request lifecycle:
#   queued -> searching -> downloading -> tagging -> importing -> done
#   searching -> waiting (nothing found; re-queued when next_retry_at passes)
#   any    -> failed (with error set)
ACTIVE_STATUSES = ("searching", "downloading", "tagging", "importing")


class Database:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(requests)")}
            for column, ddl in MIGRATIONS.items():
                if column not in existing:
                    self._conn.execute(ddl)
            self._conn.commit()

    def add_request(
        self,
        artist: str,
        title: str,
        album: str | None = None,
        deezer_id: int | None = None,
        playlist: str | None = None,
        mode: str = "acquire",
        source_path: str | None = None,
        cover_url: str | None = None,
        track_no: int | None = None,
        disc_no: int | None = None,
        year: str | None = None,
        youtube_url: str | None = None,
    ) -> dict:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO requests (created_at, updated_at, mode, deezer_id, artist,"
                " title, album, playlist, source_path, cover_url, track_no, disc_no, year,"
                " youtube_url)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (now, now, mode, deezer_id, artist, title, album, playlist, source_path,
                 cover_url, track_no, disc_no, year, youtube_url),
            )
            self._conn.commit()
            rid = cur.lastrowid
        return self.get(rid)

    def get(self, rid: int) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM requests WHERE id = ?", (rid,)).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM requests ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def update(self, rid: int, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            self._conn.execute(
                f"UPDATE requests SET {cols} WHERE id = ?", (*fields.values(), rid)
            )
            self._conn.commit()

    def delete(self, rid: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM requests WHERE id = ?", (rid,))
            self._conn.commit()

    def next_ready(self) -> dict | None:
        """Next request to work on: fresh queued requests always beat due retries,
        so a backlog of waiting retries can't starve new downloads."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM requests WHERE status = 'queued'"
                " OR (status = 'waiting' AND next_retry_at <= ?)"
                " ORDER BY (status = 'queued') DESC, id ASC LIMIT 1",
                (time.time(),),
            ).fetchone()
        return dict(row) if row else None

    def _has_similar_locked(self, artist: str, title: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM requests WHERE lower(artist) = lower(?)"
            " AND lower(title) = lower(?) AND status != 'failed' LIMIT 1",
            (artist, title),
        ).fetchone()
        return row is not None

    def has_similar(self, artist: str, title: str) -> bool:
        """A non-failed request for the same artist+title already exists."""
        with self._lock:
            return self._has_similar_locked(artist, title)

    def add_request_if_absent(self, artist: str, title: str, **fields) -> bool:
        """Insert a request only if no live one matches artist+title. The check
        and insert share one lock hold, so concurrent bulk calls can't both add
        the same track. Returns True if inserted, False if skipped."""
        with self._lock:
            if self._has_similar_locked(artist, title):
                return False
            now = time.time()
            cols = ["created_at", "updated_at", "artist", "title"]
            vals = [now, now, artist, title]
            for key, value in fields.items():
                cols.append(key)
                vals.append(value)
            placeholders = ", ".join("?" for _ in cols)
            self._conn.execute(
                f"INSERT INTO requests ({', '.join(cols)}) VALUES ({placeholders})", vals
            )
            self._conn.commit()
        return True

    def delete_by_statuses(self, statuses: "list[str]") -> int:  # quoted: `list` is shadowed by the method above
        if not statuses:
            return 0
        placeholders = ", ".join("?" for _ in statuses)
        with self._lock:
            cur = self._conn.execute(
                f"DELETE FROM requests WHERE status IN ({placeholders})", statuses
            )
            self._conn.commit()
        return cur.rowcount

    def get_config(self) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM config").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def set_config(self, updates: dict) -> None:
        with self._lock:
            for key, value in updates.items():
                self._conn.execute(
                    "INSERT INTO config (key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
            self._conn.commit()

    def reset_stale(self) -> int:
        """Re-queue requests left mid-flight by a previous run."""
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE requests SET status = 'queued', detail = 'requeued after restart'"
                f" WHERE status IN ({placeholders})",
                ACTIVE_STATUSES,
            )
            self._conn.commit()
        return cur.rowcount
