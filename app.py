import json
import os
import secrets
from datetime import date, timedelta

from flask import Flask, jsonify, request, render_template, send_from_directory

import pdf_generator
from auth import init_auth
from drive import drive_service

BASE_DIR = os.path.dirname(__file__)
TEMPLATES_REGISTRY_PATH = os.path.join(BASE_DIR, "config", "templates.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "generated_pdfs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Set PRODUCTION=1 on the deployed host (see DEPLOYMENT.md). It turns off
# the debugger (a remote-code-execution risk if left on and reachable from
# the internet) and requires cookies to travel over HTTPS only. Left off by
# default so `python3 app.py` on your own Mac still behaves as before.
IS_PRODUCTION = os.environ.get("PRODUCTION", "0") == "1"

app = Flask(__name__)

app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
if not os.environ.get("FLASK_SECRET_KEY"):
    print(
        "WARNING: FLASK_SECRET_KEY not set -- using a random key for this "
        "process. Everyone will be logged out on the next restart/redeploy. "
        "Set FLASK_SECRET_KEY in your environment for a real deployment.",
        flush=True,
    )

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

init_auth(app)


def load_registry():
    with open(TEMPLATES_REGISTRY_PATH) as f:
        return json.load(f)["templates"]


def get_template_entry(template_id):
    for t in load_registry():
        if t["id"] == template_id:
            return t
    raise ValueError(f"Unknown template: {template_id}")


def load_layout_config(template_entry):
    with open(os.path.join(BASE_DIR, template_entry["layout_config"])) as f:
        return json.load(f)


def layout_config_path(template_entry):
    return os.path.join(BASE_DIR, template_entry["layout_config"])


def local_content_path(template_id, language):
    return os.path.join(BASE_DIR, "sample_data", template_id, f"{language}.json")


def drive_content_filename(template_id, language):
    return f"{template_id}_{language}.json"


# Fields in a layout config that the admin panel is allowed to show/edit.
# Deliberately excludes "fonts" (file paths -- a typo would break rendering
# entirely) and "layout_type"/"_comment" (structural, not visual tuning).
# category_uppercase/subgroup_uppercase are also excluded from the generic
# fields loop -- they're tri-state (True/"lower"/False), not a plain
# bool/number/string the generic UI knows how to render, so they get their
# own "casing" section (see get_layout/save_layout) mirroring the per-page
# override dropdown in the content editor.
ADMIN_EDITABLE_SKIP_KEYS = {
    "fonts", "alignment", "layout_type", "_comment",
    "category_uppercase", "subgroup_uppercase",
}
ALLOWED_ALIGNMENTS = {"left", "center", "right"}
# The three real casing values _apply_casing understands (see
# pdf_generator.py): True (ALL CAPS), "lower" (all-lowercase), False (kept
# exactly as typed).
ALLOWED_CASING_VALUES = (True, "lower", False)


def render_pdf_for_template(template_id, layout_cfg, menu_data, output_path):
    """Shared by /api/save and /api/preview so both use identical rendering."""
    layout_type = layout_cfg.get("layout_type", "tasting_menu")
    if layout_type == "price_card":
        return pdf_generator.generate_price_card_pdf(menu_data, layout_cfg, output_path, BASE_DIR)
    elif layout_type == "categorized_list":
        return pdf_generator.generate_categorized_list_pdf(menu_data, layout_cfg, output_path, BASE_DIR)
    elif layout_type == "recipe_card":
        return pdf_generator.generate_recipe_card_pdf(menu_data, layout_cfg, output_path, BASE_DIR)
    elif layout_type == "simple_recipe_card":
        return pdf_generator.generate_simple_recipe_card_pdf(menu_data, layout_cfg, output_path, BASE_DIR)
    else:
        return pdf_generator.generate_pdf(menu_data, layout_cfg, output_path, BASE_DIR)


@app.route("/")
def index():
    return render_template("index.html", drive_connected=drive_service.is_configured())


@app.route("/assets/<path:filename>")
def assets(filename):
    """Serves the brand font/icon files (assets/fonts, assets/icons) so the
    editor app's own UI can use them too -- e.g. the SHABOUR display font
    via @font-face in style.css -- not just the generated PDFs."""
    return send_from_directory(os.path.join(BASE_DIR, "assets"), filename)


@app.route("/api/templates", methods=["GET"])
def list_templates():
    templates = [
        {"id": t["id"], "name": t["name"], "languages": t.get("languages", ["en"])}
        for t in load_registry()
    ]
    return jsonify({"templates": templates})


@app.route("/api/menu", methods=["GET"])
def get_menu():
    template_id = request.args.get("template")
    language = request.args.get("language", "en")

    local_path = local_content_path(template_id, language)
    drive_filename = drive_content_filename(template_id, language)
    menu_data, source = drive_service.load_menu_json(drive_filename, local_path)
    return jsonify({"menu": menu_data, "source": source})


@app.route("/api/save", methods=["POST"])
def save_menu():
    template_id = request.args.get("template")
    language = request.args.get("language", "en")
    menu_data = request.get_json()

    local_path = local_content_path(template_id, language)
    drive_filename = drive_content_filename(template_id, language)

    # Always persist the latest edits first, so nothing is lost even if PDF
    # generation hits a snag.
    drive_service.save_menu_json(menu_data, drive_filename, local_path)

    template_entry = get_template_entry(template_id)
    layout_cfg = load_layout_config(template_entry)

    today_str = date.today().isoformat()
    # Use the template id (unique per registry entry) rather than a name
    # derived from the display name -- two templates can share the same
    # leading words (e.g. "Le Voyage Shabour (aperitifs...)" vs "(exterieur
    # card)") and would otherwise collide and overwrite each other's PDF.
    safe_name = "".join(word.capitalize() for word in template_id.split("_"))
    filename = f"{safe_name}_{language.upper()}_{today_str}.pdf"
    output_path = os.path.join(OUTPUT_DIR, filename)

    result = render_pdf_for_template(template_id, layout_cfg, menu_data, output_path)

    drive_link = None
    if drive_service.is_configured():
        drive_link = drive_service.upload_pdf(output_path, filename)

    return jsonify({
        "ok": result["ok"],
        "warnings": result["warnings"],
        "filename": filename,
        "download_url": f"/download/{filename}",
        "drive_link": drive_link,
    })


@app.route("/api/preview", methods=["POST"])
def preview_menu():
    """Renders whatever is currently in the editor (including unsaved
    changes) to a scratch PDF, without touching the saved content JSON or
    creating a new dated file. Lets the user see the print result before
    committing to Save."""
    template_id = request.args.get("template")
    language = request.args.get("language", "en")
    menu_data = request.get_json()

    template_entry = get_template_entry(template_id)
    layout_cfg = load_layout_config(template_entry)

    filename = f"_preview_{template_id}_{language}.pdf"
    output_path = os.path.join(OUTPUT_DIR, filename)

    try:
        result = render_pdf_for_template(template_id, layout_cfg, menu_data, output_path)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    return jsonify({
        "ok": result["ok"],
        "warnings": result["warnings"],
        "preview_url": f"/download/{filename}?t={date.today().isoformat()}",
    })


FONTS_DIR = os.path.join(BASE_DIR, "assets", "fonts")


_font_embeddable_cache = {}


def _is_embeddable_as_body(abs_path):
    """True if reportlab can embed this font for normal text.

    Fonts with PostScript/CFF outlines (most .otf, and some .ttf like
    Avenir Next LT Pro) cannot be embedded as body text -- reportlab raises
    'postscript outlines are not supported'. Those still work for the
    DISPLAY role, which we rasterise through PIL instead. Checking here
    means the admin panel can't set a font that would crash every render.
    """
    if abs_path in _font_embeddable_cache:
        return _font_embeddable_cache[abs_path]
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        probe = "__probe__" + os.path.basename(abs_path)
        pdfmetrics.registerFont(TTFont(probe, abs_path))
        ok = True
    except Exception:
        ok = False
    _font_embeddable_cache[abs_path] = ok
    return ok


def available_fonts(body_only=False):
    """Font files installed in assets/fonts.

    body_only=True filters to those that can be embedded as normal text.
    Some roles' drawing code (see ROLES_WITH_RASTER_FALLBACK below) can
    fall back to rasterising a font it can't embed, so they're offered the
    full list; roles without that fallback (item, note, body) would either
    crash (c.setFont(None, ...)) or silently drop the text if handed a
    PostScript/CFF-outline font reportlab can't embed, so they only get
    the body_only-filtered list.
    """
    if not os.path.isdir(FONTS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(FONTS_DIR)):
        if not name.lower().endswith((".ttf", ".otf")):
            continue
        if body_only and not _is_embeddable_as_body(os.path.join(FONTS_DIR, name)):
            continue
        out.append(f"assets/fonts/{name}")
    return out


# Roles whose drawing code (see _draw_role_text in pdf_generator.py) checks
# a font's "raster" flag and rasterises through PIL when it can't be
# embedded as live text -- so they can safely use ANY installed font, the
# same way the display/title role always could. Every other role (item,
# note, body, footer, etc.) draws with a direct c.setFont(name, ...) call
# that has no such fallback, so it's restricted to embeddable fonts only.
ROLES_WITH_RASTER_FALLBACK = {"display", "category", "subgroup"}


def fonts_for_role(role):
    return available_fonts(body_only=(role not in ROLES_WITH_RASTER_FALLBACK))


@app.route("/api/fonts", methods=["GET"])
def list_fonts():
    return jsonify({"fonts": available_fonts(), "body_fonts": available_fonts(body_only=True)})


@app.route("/api/layout", methods=["GET"])
def get_layout():
    """Returns the editable subset of a template's layout config for the
    admin panel: sizes/margins/gaps, plus which font file each text role
    uses."""
    template_id = request.args.get("template")
    template_entry = get_template_entry(template_id)
    layout_cfg = load_layout_config(template_entry)

    fields = {
        k: v for k, v in layout_cfg.items()
        if k not in ADMIN_EDITABLE_SKIP_KEYS and isinstance(v, (int, float, bool, str))
    }
    return jsonify({
        "fields": fields,
        "fonts": layout_cfg.get("fonts", {}),
        "alignment": layout_cfg.get("alignment", {}),
        # Document-wide default casing for category/subgroup headings --
        # only meaningful for the categorized-list renderer (wine list,
        # digestifs), which is the only one that reads these keys. Falls
        # back to the same defaults pdf_generator.py uses when the keys
        # aren't in the layout config at all (True / False).
        "casing": {
            "category_uppercase": layout_cfg.get("category_uppercase", True),
            "subgroup_uppercase": layout_cfg.get("subgroup_uppercase", False),
        } if layout_cfg.get("layout_type") == "categorized_list" else {},
        # display/category/subgroup can rasterise a font their drawing code
        # can't embed as live text, so they're offered every installed
        # font; other roles (item, note, body, ...) only get the ones
        # reportlab can embed directly -- see ROLES_WITH_RASTER_FALLBACK.
        "available_fonts": available_fonts(body_only=True),
        "available_display_fonts": available_fonts(),
        "raster_safe_roles": sorted(ROLES_WITH_RASTER_FALLBACK),
    })


@app.route("/api/layout", methods=["POST"])
def save_layout():
    """Overwrites the editable fields of a template's layout config on disk.
    Only touches keys already present and of a plain scalar type -- never
    font paths or layout_type, so a bad admin edit can't break which
    renderer runs or which font file loads."""
    template_id = request.args.get("template")
    template_entry = get_template_entry(template_id)
    path = layout_config_path(template_entry)

    with open(path) as f:
        layout_cfg = json.load(f)

    payload = request.get_json() or {}
    updates = payload.get("fields", payload)

    # Font assignments are validated against the files actually present in
    # assets/fonts. A name that isn't there is ignored rather than written,
    # so the admin panel can never point a template at a missing font and
    # break every render.
    font_updates = payload.get("fonts")
    if isinstance(font_updates, dict):
        fonts_cfg = dict(layout_cfg.get("fonts", {}))
        for role, rel_path in font_updates.items():
            allowed = set(fonts_for_role(role))
            if rel_path in allowed:
                fonts_cfg[role] = rel_path
        layout_cfg["fonts"] = fonts_cfg

    # Alignment is a per-role choice of "left"/"center"/"right" -- validated
    # against a fixed allow-list the same way fonts are, so a bad value
    # can't silently break a role's rendering.
    align_updates = payload.get("alignment")
    if isinstance(align_updates, dict):
        align_cfg = dict(layout_cfg.get("alignment", {}))
        for role, value in align_updates.items():
            if value in ALLOWED_ALIGNMENTS:
                align_cfg[role] = value
        layout_cfg["alignment"] = align_cfg

    # Document-wide default casing (see get_layout) -- written directly as
    # top-level keys, same as pdf_generator.py reads them.
    casing_updates = payload.get("casing")
    if isinstance(casing_updates, dict):
        for key in ("category_uppercase", "subgroup_uppercase"):
            if key in casing_updates and casing_updates[key] in ALLOWED_CASING_VALUES:
                layout_cfg[key] = casing_updates[key]

    for key, new_value in updates.items():
        if key in ADMIN_EDITABLE_SKIP_KEYS:
            continue
        if key not in layout_cfg:
            continue
        old_value = layout_cfg[key]
        if isinstance(old_value, bool):
            layout_cfg[key] = bool(new_value)
        elif isinstance(old_value, (int, float)):
            try:
                layout_cfg[key] = float(new_value)
            except (TypeError, ValueError):
                continue
        elif isinstance(old_value, str):
            layout_cfg[key] = str(new_value)

    with open(path, "w") as f:
        json.dump(layout_cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return jsonify({
        "ok": True,
        "fields": {
            k: v for k, v in layout_cfg.items()
            if k not in ADMIN_EDITABLE_SKIP_KEYS and isinstance(v, (int, float, bool, str))
        },
        "fonts": layout_cfg.get("fonts", {}),
        "alignment": layout_cfg.get("alignment", {}),
        "casing": {
            "category_uppercase": layout_cfg.get("category_uppercase", True),
            "subgroup_uppercase": layout_cfg.get("subgroup_uppercase", False),
        } if layout_cfg.get("layout_type") == "categorized_list" else {},
        "available_fonts": available_fonts(body_only=True),
        "available_display_fonts": available_fonts(),
        "raster_safe_roles": sorted(ROLES_WITH_RASTER_FALLBACK),
    })


@app.route("/download/<path:filename>")
def download(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=False)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=not IS_PRODUCTION)
