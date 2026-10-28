"""Cloud-only behaviour: the single-writer lock, waiting for the database, and the password login."""

import stat
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module  # noqa: E402
from auth import COOKIE, Auth  # noqa: E402
from persistence import Lock, LockLost, Persistence  # noqa: E402


class MemoryLockBackend:
    """The GCS lock object, in memory. `age` lets a test make the lock look stale."""

    def __init__(self):
        self.obj = None  # (generation, body, updated)
        self.gen = 0
        self.mutex = threading.Lock()

    def create(self, body):
        with self.mutex:
            if self.obj:
                return None
            self.gen += 1
            self.obj = (self.gen, body, time.time())
            return self.gen

    def read(self):
        with self.mutex:
            return None if not self.obj else (self.obj[0], time.time() - self.obj[2])

    def replace(self, generation, body):
        with self.mutex:
            if not self.obj or self.obj[0] != generation:
                return None
            self.gen += 1
            self.obj = (self.gen, body, time.time())
            return self.gen

    def delete(self, generation):
        with self.mutex:
            if self.obj and self.obj[0] == generation:
                self.obj = None

    def age(self, seconds):
        g, b, _ = self.obj
        self.obj = (g, b, time.time() - seconds)


def test_second_instance_waits_for_release():
    backend = MemoryLockBackend()
    a, b = Lock(backend, "a", poll_seconds=0.01), Lock(backend, "b", poll_seconds=0.01)
    a.acquire()
    with pytest.raises(TimeoutError):
        b.acquire(timeout=0.1)
    a.release()
    b.acquire(timeout=1)
    assert b.generation is not None


def test_stale_lock_is_taken_over_and_old_holder_notices():
    backend = MemoryLockBackend()
    a, b = Lock(backend, "a", stale_seconds=5, poll_seconds=0.01), Lock(backend, "b", stale_seconds=5, poll_seconds=0.01)
    a.acquire()
    backend.age(10)  # a stopped refreshing (frozen or killed)
    b.acquire(timeout=1)
    with pytest.raises(LockLost):
        a.refresh()


@pytest.fixture
def fake_litestream(tmp_path):
    """Stands in for the litestream binary: restore does nothing, replicate runs until stopped."""
    script = tmp_path / "litestream"
    script.write_text("#!/bin/sh\nif [ \"$1\" = replicate ]; then exec sleep 60; fi\nexit 0\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_new_instance_takes_over_only_after_old_one_stops(tmp_path, fake_litestream):
    backend = MemoryLockBackend()
    order = []

    def instance(name):
        lock = Lock(backend, name, poll_seconds=0.01)
        return Persistence(tmp_path / name / "app.sqlite", "bucket", lambda: order.append(name), lock, fake_litestream)

    old, new = instance("old"), instance("new")
    old.start()
    assert old.ready.wait(5)
    new.start()
    assert not new.ready.wait(0.3)  # still held by the old instance
    old.stop()  # Cloud Run's SIGTERM: final sync, release
    assert new.ready.wait(5)
    assert order == ["old", "new"]
    new.stop()


def test_api_waits_for_database_then_serves(tmp_path, monkeypatch, library):
    lib = library
    monkeypatch.setattr(app_module, "READY_WAIT_SECONDS", 0.2)
    p = Persistence(tmp_path / "cloud.sqlite", "bucket", lambda: None)  # never started: not ready
    c = TestClient(app_module.create_app(tmp_path / "cloud.sqlite", lib, persistence=p))
    assert c.get("/api/players").status_code == 503
    assert c.get("/api/health").json()["ready"] is False
    p.ready.set()
    # The schema normally comes from on_ready; create it the local way for this check.
    app_module.create_app(tmp_path / "cloud.sqlite", lib)
    assert c.get("/api/players").status_code == 200


def test_password_login(tmp_path, library):
    lib = library
    static = tmp_path / "web"
    static.mkdir()
    (static / "index.html").write_text("<h1>practice</h1>")
    c = TestClient(app_module.create_app(tmp_path / "auth.sqlite", lib, auth=Auth("hunter2", "k"), static_dir=static))

    assert c.get("/api/health").status_code == 200  # open, for Cloud Run checks
    assert c.get("/api/players").status_code == 401
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/"

    r = c.post("/login", content="password=nope&next=/", headers={"Content-Type": "application/x-www-form-urlencoded"},
               follow_redirects=False)
    assert "error=1" in r.headers["location"] and COOKIE not in r.cookies

    r = c.post("/login", content="password=hunter2&next=/admin.html",
               headers={"Content-Type": "application/x-www-form-urlencoded"}, follow_redirects=False)
    assert r.headers["location"] == "/admin.html" and COOKIE in r.cookies
    c.cookies.set(COOKIE, r.cookies[COOKIE])
    assert c.get("/api/players").status_code == 200
    assert "practice" in c.get("/").text

    # A token signed for a different password doesn't work.
    assert not Auth("other", "k").valid(r.cookies[COOKIE])
    # Open redirects are refused.
    r = c.post("/login", content="password=hunter2&next=//evil.example",
               headers={"Content-Type": "application/x-www-form-urlencoded"}, follow_redirects=False)
    assert r.headers["location"] == "/"
