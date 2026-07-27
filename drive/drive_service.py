"""
Google Drive connection using a service account -- no login screen for
restaurant staff. Eyal creates one service account key (one-time, see
SETUP_INSTRUCTIONS.md), shares the menu's Drive folder with it, and the app
reads/writes files in that folder silently in the background.

Falls back to local files in sample_data/ if no credentials are configured,
so the app is fully usable/demoable before Drive is wired up.
"""
import io
import os
import json

DRIVE_FOLDER_ID = os.environ.get("MENU_DRIVE_FOLDER_ID", "")
CREDENTIALS_PATH = os.environ.get("MENU_DRIVE_CREDENTIALS", os.path.join(
    os.path.dirname(__file__), "service_account.json"))

SCOPES = ["https://www.googleapis.com/auth/drive"]


def is_configured():
    return os.path.exists(CREDENTIALS_PATH) and bool(DRIVE_FOLDER_ID)


def _get_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def _find_file(service, filename):
    query = f"'{DRIVE_FOLDER_ID}' in parents and name = '{filename}' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None


def load_menu_json(content_filename, local_fallback_path):
    """Returns the current menu content dict, from Drive if configured,
    otherwise from the local sample file. content_filename identifies this
    specific template+language's content (e.g. 'voyage_shabour_en.json')."""
    if not is_configured():
        with open(local_fallback_path) as f:
            return json.load(f), "local"

    from googleapiclient.http import MediaIoBaseDownload

    service = _get_service()
    file_id = _find_file(service, content_filename)
    if not file_id:
        with open(local_fallback_path) as f:
            return json.load(f), "local"

    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return json.load(buf), "drive"


def save_menu_json(menu_data, content_filename, local_fallback_path):
    """Persists the latest edits (used so a refresh doesn't lose work)."""
    if not is_configured():
        with open(local_fallback_path, "w") as f:
            json.dump(menu_data, f, indent=2)
        return "local"

    from googleapiclient.http import MediaIoBaseUpload

    service = _get_service()
    file_id = _find_file(service, content_filename)
    buf = io.BytesIO(json.dumps(menu_data, indent=2).encode("utf-8"))
    media = MediaIoBaseUpload(buf, mimetype="application/json")

    if file_id:
        service.files().update(fileId=file_id, media_body=media).execute()
    else:
        metadata = {"name": content_filename, "parents": [DRIVE_FOLDER_ID]}
        service.files().create(body=metadata, media_body=media).execute()
    return "drive"


def upload_pdf(local_pdf_path, drive_filename):
    """Uploads the finished dated PDF to the Drive folder. Returns a
    shareable link if Drive is configured, otherwise None (file stays local)."""
    if not is_configured():
        return None

    from googleapiclient.http import MediaFileUpload

    service = _get_service()
    metadata = {"name": drive_filename, "parents": [DRIVE_FOLDER_ID]}
    media = MediaFileUpload(local_pdf_path, mimetype="application/pdf")
    file = service.files().create(body=metadata, media_body=media, fields="id, webViewLink").execute()
    return file.get("webViewLink")
