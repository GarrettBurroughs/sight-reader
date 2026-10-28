"""Keep the player database safe on Cloud Run: SQLite on local disk, replicated to GCS by Litestream.

Only one instance may write at a time, but during a deploy Cloud Run briefly runs the old
and new revision together. So each instance holds a lock object in the bucket:

1. On start, wait until no other live instance holds the lock (the old one releases it
   when Cloud Run stops it, after Litestream's final sync), or until the lock goes stale.
2. Restore the database from the bucket, set up the schema, start `litestream replicate`.
3. Refresh the lock every few seconds. If it's ever lost, stop writing.

The web server starts answering at once (Cloud Run needs that before it shifts traffic and
stops the old instance); requests that touch player data wait for `ready`.
Locally (no bucket configured) the database is used directly and is ready immediately.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

log = logging.getLogger("sightreader.persistence")

LOCK_NAME = "app.lock"
REFRESH_SECONDS = 10
STALE_SECONDS = 45  # a lock not refreshed for this long belongs to a dead instance
LITESTREAM_CONFIG = """\
dbs:
  - path: {db}
    replica:
      url: gs://{bucket}/litestream
      sync-interval: 1s
"""


class LockLost(Exception):
    pass


class LockBackend(Protocol):
    """Compare-and-swap storage for the lock object."""

    def create(self, body: str) -> int | None:
        """Create the object if absent; its generation, or None if it already exists."""

    def read(self) -> tuple[int, float] | None:
        """(generation, seconds since last update), or None if absent."""

    def replace(self, generation: int, body: str) -> int | None:
        """Overwrite if still at `generation`; the new generation, or None if it changed."""

    def delete(self, generation: int) -> None:
        """Delete if still at `generation`; otherwise leave it."""


class GcsLockBackend:
    def __init__(self, bucket: str, name: str = LOCK_NAME):
        from google.api_core.exceptions import NotFound, PreconditionFailed
        from google.cloud import storage

        self._errors = (NotFound, PreconditionFailed)
        self._bucket = storage.Client().bucket(bucket)
        self._name = name

    def _blob(self):
        return self._bucket.blob(self._name)

    def create(self, body):
        blob = self._blob()
        try:
            blob.upload_from_string(body, if_generation_match=0, content_type="application/json")
        except self._errors:
            return None
        return blob.generation

    def read(self):
        blob = self._bucket.get_blob(self._name)
        if blob is None:
            return None
        return blob.generation, time.time() - blob.updated.timestamp()

    def replace(self, generation, body):
        blob = self._blob()
        try:
            blob.upload_from_string(body, if_generation_match=generation, content_type="application/json")
        except self._errors:
            return None
        return blob.generation

    def delete(self, generation):
        try:
            self._blob().delete(if_generation_match=generation)
        except self._errors:
            pass


@dataclass
class Lock:
    backend: LockBackend
    owner: str
    stale_seconds: float = STALE_SECONDS
    poll_seconds: float = 1.0
    generation: int | None = None

    def _body(self) -> str:
        return json.dumps({"owner": self.owner, "at": time.time()})

    def acquire(self, timeout: float | None = None) -> None:
        """Block until the lock is ours: free, released by its holder, or stale."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            gen = self.backend.create(self._body())
            if gen is not None:
                self.generation = gen
                return
            current = self.backend.read()
            if current is not None and current[1] > self.stale_seconds:
                log.warning("Taking over a stale lock (%.0fs old)", current[1])
                self.backend.delete(current[0])
                continue
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("lock still held")
            time.sleep(self.poll_seconds)

    def refresh(self) -> None:
        gen = self.backend.replace(self.generation, self._body())
        if gen is None:
            raise LockLost("another instance took the lock")
        self.generation = gen

    def release(self) -> None:
        if self.generation is not None:
            self.backend.delete(self.generation)
            self.generation = None


class Persistence:
    """Owns the database file's lifecycle. `ready` is set once it's safe to read and write."""

    def __init__(self, db_path: Path, bucket: str | None, on_ready: Callable[[], None],
                 lock: Lock | None = None, litestream: str = "litestream"):
        self.db_path = db_path
        self.bucket = bucket
        self.on_ready = on_ready
        self.ready = threading.Event()
        self.failed: str | None = None
        self._lock = lock
        self._litestream = litestream
        self._proc: subprocess.Popen | None = None
        self._stopping = threading.Event()
        self._config = db_path.parent / "litestream.yml"
        self._started = False

    @classmethod
    def from_env(cls, db_path: Path, on_ready: Callable[[], None]) -> "Persistence":
        bucket = os.environ.get("SIGHTREADER_BUCKET") or None
        lock = None
        if bucket:
            logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
            owner = f"{os.environ.get('K_REVISION', 'local')}@{socket.gethostname()}"
            lock = Lock(GcsLockBackend(bucket), owner)
        return cls(db_path, bucket, on_ready, lock)

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        if not self.bucket:
            self.on_ready()
            self.ready.set()
            return
        threading.Thread(target=self._run, name="persistence", daemon=True).start()

    def _run(self) -> None:
        try:
            log.info("Waiting for the database lock")
            self._lock.acquire()
            log.info("Lock acquired; restoring %s", self.db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._config.write_text(LITESTREAM_CONFIG.format(db=self.db_path, bucket=self.bucket))
            subprocess.run([self._litestream, "restore", "-config", str(self._config), "-if-db-not-exists",
                            "-if-replica-exists", str(self.db_path)], check=True)
            self.on_ready()  # schema and migrations, before replication starts
            self._proc = subprocess.Popen([self._litestream, "replicate", "-config", str(self._config)])
            self.ready.set()
            log.info("Database ready")
            while not self._stopping.wait(REFRESH_SECONDS):
                if self._proc.poll() is not None:
                    raise RuntimeError(f"litestream exited with {self._proc.returncode}")
                self._lock.refresh()
        except Exception as e:  # stop serving player data rather than risk two writers
            if not self._stopping.is_set():
                log.exception("Persistence failed; refusing further writes")
                self.failed = str(e)
                self.ready.clear()
                self._stop_litestream()

    def stop(self) -> None:
        """On shutdown: stop taking requests, let Litestream do its final sync, release the lock."""
        self._stopping.set()
        self.ready.clear()
        self._stop_litestream()
        if self._lock:
            self._lock.release()

    def _stop_litestream(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()  # SIGTERM: Litestream syncs what's left, then exits
            try:
                self._proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._proc.kill()
