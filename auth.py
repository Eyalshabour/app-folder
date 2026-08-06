"""
Shared-password login gate for the menu editor.

The app now goes out over the internet so staff can edit menus from their
phones, which means it needs *something* in front of every route -- a
single shared password is enough for a small team and is what the app was
asked to have. This module wires that in as a Flask before_request hook
rather than protecting each route individually, so nothing can accidentally
ship unprotected.

Env vars used:
  APP_PASSWORD      -- the shared password. If unset, a random one is
                       generated at startup and printed to the server log
                       (never to the page) so the app is never silently
                       open -- but for a real deployment, set this.
  FLASK_SECRET_KEY  -- signs the session cookie. If unset, a random one is
                       generated per-process (fine locally; on a real host
                       set this so logins survive restarts/redeploys).
"""

import hmac
import os
import secrets
import time

from flask import redirect, render_template_string, request, session, url_for

_EXEMPT_PREFIXES = ("/login", "/static/", "/assets/")

_LOGIN_PAGE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Voyage Shabour -- Menu Editor</title>
  <style>
    @font-face {
      font-family: "Shabour";
      src: url("/assets/fonts/SHABOUR-SemiBold.otf") format("opentype");
      font-weight: 600;
      font-display: swap;
    }
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #fbf6ee;
           display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
    form { background: #fff; padding: 36px 28px 32px; border-radius: 14px; box-shadow: 0 2px 12px rgba(0,0,0,0.08);
           width: 100%; max-width: 320px; box-sizing: border-box; text-align: center; }
    .login-logo { width: 44px; height: 44px; border-radius: 10px; background: #8a5227;
           display: flex; align-items: center; justify-content: center; margin: 0 auto 16px; }
    .login-logo img { width: 26px; height: 26px; filter: brightness(0) invert(1); }
    h1 { font-family: "Shabour", -apple-system, sans-serif; font-size: 19px; font-weight: 600;
         letter-spacing: .02em; margin: 0 0 20px; color: #3a2313; }
    input[type=password] { width: 100%; font-size: 16px; padding: 10px; border: 1px solid #ddd;
           border-radius: 8px; box-sizing: border-box; margin-bottom: 14px; text-align: center; }
    button { width: 100%; font-size: 15px; font-weight: 600; padding: 12px; border: none;
           border-radius: 999px; background: #8a5227; color: #fff; cursor: pointer; }
    button:hover { background: #713f1c; }
    .error { color: #a33; font-size: 14px; margin-bottom: 12px; }
  </style>
</head>
<body>
  <form method="post" action="{{ url_for('login') }}">
    <div class="login-logo"><img src="/assets/icons/shabour_symbol.png" alt=""></div>
    <h1>Voyage Shabour</h1>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
    <input type="password" name="password" placeholder="Password" autofocus required>
    <button type="submit">Enter</button>
  </form>
</body>
</html>
"""

# In-memory failed-login tracking: ip -> [timestamps]. Fine for a single
# process; a multi-worker deployment would need a shared store (e.g. Redis)
# for the lockout to hold across workers. Small restaurant team, single
# gunicorn worker is the documented deployment, so this is enough.
_FAILED_ATTEMPTS = {}
_WINDOW_SECONDS = 300
_MAX_ATTEMPTS = 8

_generated_password = None


def _get_app_password():
    global _generated_password
    env_pw = os.environ.get("APP_PASSWORD")
    if env_pw:
        return env_pw
    if _generated_password is None:
        _generated_password = secrets.token_urlsafe(9)
        print(
            "\n" + "=" * 60 +
            "\nNo APP_PASSWORD set -- generated a random one for this run:\n\n"
            f"    {_generated_password}\n\n"
            "Set APP_PASSWORD in your environment for a stable password\n"
            "across restarts (required for a real deployment).\n" + "=" * 60 + "\n",
            flush=True,
        )
    return _generated_password


def _client_ip():
    # Render/Railway/Fly all sit behind a proxy that sets this; fall back to
    # the direct peer address for local runs.
    fwd = request.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else (request.remote_addr or "unknown")


def _is_locked_out(ip):
    now = time.time()
    attempts = [t for t in _FAILED_ATTEMPTS.get(ip, []) if now - t < _WINDOW_SECONDS]
    _FAILED_ATTEMPTS[ip] = attempts
    return len(attempts) >= _MAX_ATTEMPTS


def _record_failure(ip):
    _FAILED_ATTEMPTS.setdefault(ip, []).append(time.time())


def init_auth(app):
    """Wires the login gate into a Flask app. Call once, right after the
    Flask app is created."""

    @app.before_request
    def _require_login():
        if request.path.startswith(_EXEMPT_PREFIXES):
            return None
        if session.get("authed"):
            return None
        return redirect(url_for("login", next=request.path))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        password = _get_app_password()

        if request.method == "GET":
            return render_template_string(_LOGIN_PAGE, error=None)

        ip = _client_ip()
        if _is_locked_out(ip):
            return render_template_string(
                _LOGIN_PAGE, error="Too many attempts -- wait a few minutes and try again."
            ), 429

        submitted = request.form.get("password", "")
        if hmac.compare_digest(submitted, password):
            session.clear()
            session["authed"] = True
            session.permanent = True
            dest = request.args.get("next") or "/"
            if not dest.startswith("/"):
                dest = "/"
            return redirect(dest)

        _record_failure(ip)
        return render_template_string(_LOGIN_PAGE, error="Wrong password."), 401

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))
