"""A single shared password for the whole app, remembered by a long-lived signed cookie.

Off when no password is configured (local development). Google sign-in isn't an option:
Google blocks it inside embedded web views like the iPad shell.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import time
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

COOKIE = "sr_session"
MAX_AGE = 365 * 24 * 3600
OPEN_PATHS = {"/login", "/logout", "/api/health"}


class Auth:
    def __init__(self, password: str | None, key: str | None, secure_cookie: bool = False):
        self.password = password
        # Sessions are tied to the password too, so changing it logs everyone out.
        self.key = hashlib.sha256(f"{key or ''}\0{password or ''}".encode()).digest()
        self.secure_cookie = secure_cookie

    @property
    def enabled(self) -> bool:
        return bool(self.password)

    def token(self) -> str:
        payload = f"v1.{int(time.time())}"
        return f"{payload}.{self._sign(payload)}"

    def valid(self, token: str | None) -> bool:
        if not token or token.count(".") != 2:
            return False
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sign(payload)):
            return False
        issued = int(payload.split(".")[1])
        return time.time() - issued < MAX_AGE

    def _sign(self, payload: str) -> str:
        return hmac.new(self.key, payload.encode(), hashlib.sha256).hexdigest()

    def install(self, app: FastAPI) -> None:
        @app.middleware("http")
        async def require_login(request: Request, call_next):
            if not self.enabled or request.url.path in OPEN_PATHS or self.valid(request.cookies.get(COOKIE)):
                return await call_next(request)
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "Not logged in"}, status_code=401)
            target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"/login?next={quote(target)}", status_code=303)

        @app.get("/login", include_in_schema=False)
        def login_form(next: str = "/", error: str = ""):
            return HTMLResponse(LOGIN_PAGE.format(next=html.escape(next, quote=True),
                                                  error="<p class=error>Wrong password.</p>" if error else ""))

        @app.post("/login", include_in_schema=False)
        async def login(request: Request):
            form = parse_qs((await request.body()).decode())
            password = form.get("password", [""])[0]
            target = form.get("next", ["/"])[0]
            if not target.startswith("/") or target.startswith("//"):
                target = "/"  # only local redirects
            if not self.enabled or not hmac.compare_digest(password.encode(), (self.password or "").encode()):
                await asyncio.sleep(1)  # slow down guessing
                return RedirectResponse(f"/login?error=1&next={quote(target)}", status_code=303)
            response = RedirectResponse(target, status_code=303)
            response.set_cookie(COOKIE, self.token(), max_age=MAX_AGE, httponly=True, samesite="lax",
                                secure=self.secure_cookie)
            return response

        @app.get("/logout", include_in_schema=False)
        def logout():
            response: Response = RedirectResponse("/login" if self.enabled else "/", status_code=303)
            response.delete_cookie(COOKIE)
            return response


LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sight Reader</title>
<style>
  :root {{ --bg: #f7f5f0; --ink: #1d1b18; --quiet: #6f6a61; --line: #d8d3c8; --accent: #2f6fde; --bad: #d64545; --card: #fff; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg: #181715; --ink: #efece6; --quiet: #a29c91; --line: #3a3732; --card: #26241f; }} }}
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--bg); color: var(--ink);
         font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
  form {{ display: grid; gap: 12px; width: min(320px, calc(100vw - 32px)); }}
  h1 {{ font-size: 22px; margin: 0 0 8px; }}
  input, button {{ font: inherit; padding: 10px 12px; border-radius: 8px; border: 1px solid var(--line); background: var(--card); color: var(--ink); }}
  button {{ background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }}
  .error {{ color: var(--bad); margin: 0; }}
</style></head>
<body><form method="post" action="/login">
  <h1>Sight Reader</h1>
  {error}
  <input type="password" name="password" placeholder="Password" autofocus required autocomplete="current-password">
  <input type="hidden" name="next" value="{next}">
  <button type="submit">Log in</button>
</form></body></html>
"""
