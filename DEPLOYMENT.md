# Deploying the menu editor so staff can use it from anywhere

This covers what changed to make the app safe to put on the internet, and
how to actually put it there.

## What's new

- Every page now requires a shared password to view or edit anything
  (`auth.py`). Nobody can reach `/api/save`, the admin panel, or a PDF
  download without logging in first.
- Failed logins are rate-limited (8 tries per 5 minutes per IP) so the
  password can't be brute-forced.
- Debug mode and insecure cookies turn off automatically when `PRODUCTION=1`
  is set (see below) -- locally, without that variable, everything behaves
  exactly as before.
- `gunicorn` was added as the production web server (the Flask dev server
  used until now isn't meant to be exposed to the internet).

## Required environment variables

Set these on whatever host you deploy to:

| Variable | Value | Why |
|---|---|---|
| `APP_PASSWORD` | a password you choose | shared login for all staff |
| `FLASK_SECRET_KEY` | a long random string, e.g. run `python3 -c "import secrets; print(secrets.token_hex(32))"` once and reuse the output | signs login sessions -- if this changes, everyone gets logged out |
| `PRODUCTION` | `1` | turns on the hardened settings described above |

If `APP_PASSWORD` is left unset, the app still won't run open -- it
generates a random password and prints it to the server log instead, so
you'd have to go find it in the host's logs. Set it explicitly instead.

To change the password later, just update `APP_PASSWORD` on the host and
restart the app -- no code change needed.

## Storage: why you need a persistent disk

Menu edits are saved to `sample_data/<menu>/<language>.json`, generated
PDFs go to `generated_pdfs/`, and admin layout/font changes are written to
`config/templates/<menu>.json` -- all as plain files next to the app code.
Most cheap hosting (free tiers especially) wipes local files on every
redeploy or restart. **If you skip this step, every menu edit will vanish
the next time the app restarts.** Pick a host with a persistent disk/volume
and mount it over those three folders.

## Recommended: Render

1. Push this folder to a GitHub repo (Render deploys from git).
2. On [render.com](https://render.com), create a new **Web Service** from
   that repo.
3. Build command: `pip install -r requirements.txt`
   Start command: `gunicorn app:app --workers 1 --threads 4 --timeout 60`
   (same as the included `Procfile` -- Render will pick that up automatically
   if you leave the start command blank).
4. Add the three environment variables from the table above.
5. Add a **persistent disk** (Render's paid tiers include one), mounted at
   the app's root so `sample_data/`, `generated_pdfs/`, and
   `config/templates/` all persist. The simplest way: mount the whole app
   directory, or mount three separate disks at those three paths if Render's
   plan only allows one mount point, keep the disk small (menus + PDFs are
   tiny) and pick a plan that includes it -- Render's free tier does not.
6. HTTPS is automatic and free on Render -- no extra setup.

Railway and Fly.io both work the same way (git-based deploy, env vars, a
volume for persistent storage) if you'd rather use one of those instead.

## Optional: back everything up to Google Drive too

The app already has a Google Drive integration (`drive/drive_service.py`)
that's currently unconfigured -- wiring up a service-account key (see
`SETUP_INSTRUCTIONS.md`) gives you an automatic off-host copy of every save,
independent of whatever host you pick. Not required, but a good safety net
on top of the persistent disk.

## Local use is unaffected

Running `python3 app.py` on your own Mac still works exactly as before --
you'll just now be asked to log in once (password printed to the terminal
if you haven't set `APP_PASSWORD`), and there's no need to set
`PRODUCTION=1` for that.
