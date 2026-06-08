"""VIN + service-type result cache for ALLDATA labor / parts / repair_procedure.

Task #16. The single biggest contributor to Estimaro's 9-15 minute job
wall-clock is the ALLDATA vision agent (4-7 min per run). Repeat
customers and same-vehicle re-quotes hit identical (VIN, service_type)
keys that produce identical labor rows + parts lists — no reason to
re-run the agent.

Scope of what's cached:
  * labor (operation, hours, source, vehicle_match)
  * parts (the OEM parts list ALLDATA returned)
  * repair_procedure (R-cell items + scan_status)
  * section_path
  * extraction_confidence / verification (yes — they don't change)

NOT cached (always recomputed live):
  * Vendor quotes / pricing / availability — prices drift daily
  * NHTSA recalls — new ones get added periodically
  * The serviceSkeleton itself — derived from job spec, cheap

Storage: local SQLite file at SCREENSHOT_DIR/../result_cache.db.
SQLite chosen over JSON because: atomic writes, automatic locking,
built-in TTL via created_at column, single file backup-friendly.
Built-in `sqlite3` module — no new dependency.

Cache key = SHA256(vin_upper + '|' + service_type + '|' + complaint_norm).
Including the normalised complaint means 'front brake noise' and
'brakes squeaking' both classify to brake_front_full but cache as
different rows — protects against complaint nuance changes affecting
the right answer.

Default TTL: 24 hours. Override via CACHE_TTL_SEC env var.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional, Any

from loguru import logger


_DEFAULT_TTL = int(os.environ.get("CACHE_TTL_SEC", str(24 * 60 * 60)))
_DB_PATH = Path(os.environ.get(
    "RESULT_CACHE_DB",
    "/home/estimaro/Estimaro-AdminDashboard/EstimaroAgent/result_cache.db",
))


def _normalise_complaint(s: str) -> str:
    """Strip punctuation + extra whitespace + lowercase so 'Front brake
    noise!' and 'front brake noise' hash to the same key."""
    if not s:
        return ""
    out = re.sub(r"[^\w\s]+", " ", s.lower())
    out = re.sub(r"\s+", " ", out).strip()
    return out


def _key_for(vin: str, service_type: Optional[str], complaint: str) -> str:
    """Stable cache key — same inputs always produce same hex digest."""
    vin_u = (vin or "").strip().upper()
    st = (service_type or "unknown").strip()
    cn = _normalise_complaint(complaint or "")
    raw = f"{vin_u}|{st}|{cn}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class _ResultCache:
    """Singleton-ish wrapper. Lazily opens the SQLite file on first use
    and reuses the connection for the worker's lifetime."""

    def __init__(self, db_path: Path = _DB_PATH):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self):
        if self._conn is not None:
            return self._conn
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False because the worker uses asyncio +
        # asyncio.to_thread for some calls; the connection itself
        # serialises writes via SQLite's own lock so this is safe for
        # the worker's single-process use case.
        self._conn = sqlite3.connect(
            str(self.db_path), check_same_thread=False, timeout=10.0,
        )
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS result_cache (
                cache_key   TEXT PRIMARY KEY,
                vin         TEXT NOT NULL,
                service_type TEXT,
                complaint   TEXT,
                payload     TEXT NOT NULL,
                created_at  REAL NOT NULL,
                ttl_seconds INTEGER NOT NULL,
                hits        INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_created_at ON result_cache(created_at)"
        )
        self._conn.commit()
        return self._conn

    def get(self, vin: str, service_type: Optional[str], complaint: str) -> Optional[dict]:
        """Return cached payload dict or None on miss / expired.

        Side effect: increments `hits` for telemetry. Expired rows are
        NOT auto-deleted on read — that's purge_expired's job — but
        they ARE treated as misses so a stale row never returns.
        """
        try:
            conn = self._connect()
            key = _key_for(vin, service_type, complaint)
            row = conn.execute(
                "SELECT payload, created_at, ttl_seconds, hits FROM result_cache "
                "WHERE cache_key = ?",
                (key,),
            ).fetchone()
            if not row:
                return None
            payload_json, created_at, ttl, hits = row
            age = time.time() - created_at
            if age > ttl:
                logger.info(
                    f"[result_cache] MISS (expired) key={key[:8]}... age={age:.0f}s ttl={ttl}s"
                )
                return None
            # Bump hit counter (best-effort — failure here just means
            # telemetry is slightly off, never breaks the read).
            try:
                conn.execute(
                    "UPDATE result_cache SET hits = hits + 1 WHERE cache_key = ?",
                    (key,),
                )
                conn.commit()
            except Exception:
                pass
            logger.info(
                f"[result_cache] HIT key={key[:8]}... age={age:.0f}s hits={hits + 1}"
            )
            return json.loads(payload_json)
        except Exception as e:
            logger.warning(f"[result_cache] get error (treating as miss): {e}")
            return None

    def put(self, vin: str, service_type: Optional[str], complaint: str,
            payload: dict, ttl_seconds: int = _DEFAULT_TTL) -> bool:
        """Upsert payload for (vin, service_type, complaint) key.

        Returns True on success, False on error. Failures are logged
        but never raised — caching is best-effort, never blocking.
        """
        try:
            conn = self._connect()
            key = _key_for(vin, service_type, complaint)
            payload_json = json.dumps(payload, default=str)
            now = time.time()
            conn.execute(
                "INSERT OR REPLACE INTO result_cache "
                "(cache_key, vin, service_type, complaint, payload, created_at, ttl_seconds, hits) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                (key, (vin or "").upper(), service_type or "",
                 (complaint or "")[:300], payload_json, now, ttl_seconds),
            )
            conn.commit()
            logger.info(
                f"[result_cache] STORED key={key[:8]}... ttl={ttl_seconds}s "
                f"payload_kb={len(payload_json) // 1024}"
            )
            return True
        except Exception as e:
            logger.warning(f"[result_cache] put error: {e}")
            return False

    def purge_expired(self) -> int:
        """Delete expired rows. Returns count purged. Run periodically
        from the worker's keepalive."""
        try:
            conn = self._connect()
            now = time.time()
            cur = conn.execute(
                "DELETE FROM result_cache WHERE (? - created_at) > ttl_seconds",
                (now,),
            )
            conn.commit()
            count = cur.rowcount or 0
            if count:
                logger.info(f"[result_cache] purged {count} expired rows")
            return count
        except Exception as e:
            logger.warning(f"[result_cache] purge error: {e}")
            return 0

    def stats(self) -> dict:
        """Hits / misses / size for diagnostics. Cheap query, never raises."""
        try:
            conn = self._connect()
            row = conn.execute(
                "SELECT COUNT(*), SUM(hits), MIN(created_at), MAX(created_at) "
                "FROM result_cache"
            ).fetchone()
            n_rows, n_hits, oldest, newest = row or (0, 0, None, None)
            return {
                "rows": n_rows or 0,
                "total_hits": n_hits or 0,
                "oldest_age_sec": (time.time() - oldest) if oldest else None,
                "newest_age_sec": (time.time() - newest) if newest else None,
                "db_path": str(self.db_path),
            }
        except Exception as e:
            return {"error": str(e)[:120]}


# Module-level singleton so the worker reuses one connection instead
# of opening one per request.
_INSTANCE = _ResultCache()


def get_cached_result(vin: str, service_type: Optional[str], complaint: str) -> Optional[dict]:
    return _INSTANCE.get(vin, service_type, complaint)


def store_result(vin: str, service_type: Optional[str], complaint: str,
                 payload: dict, ttl_seconds: int = _DEFAULT_TTL) -> bool:
    return _INSTANCE.put(vin, service_type, complaint, payload, ttl_seconds)


def purge_expired() -> int:
    return _INSTANCE.purge_expired()


def cache_stats() -> dict:
    return _INSTANCE.stats()


if __name__ == "__main__":
    # Self-test.
    test_payload = {
        "labor": {"operation": "Front Pads", "hours": 1.3},
        "parts": [{"name": "Front Pads", "oem_number": "8634921", "price": 0.0}],
    }
    print("--- Initial put ---")
    print(store_result("YV1SZ58D621078311", "brake_front_full",
                       "front brake service", test_payload, ttl_seconds=60))
    print("--- Get (should HIT) ---")
    hit = get_cached_result("YV1SZ58D621078311", "brake_front_full",
                            "Front Brake Service!")
    print(json.dumps(hit, indent=2) if hit else "MISS")
    print("--- Different VIN (should MISS) ---")
    miss = get_cached_result("WBA4J1C53KBM14843", "brake_front_full",
                             "front brake service")
    print(miss)
    print("--- Stats ---")
    print(json.dumps(cache_stats(), indent=2))
