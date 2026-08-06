"""
Generates a ready-to-print PDF for a course-based tasting menu (e.g. "The
Voyage Shabour"), matching the brand's InDesign design as closely as
possible without InDesign itself.

Two things make this tricky, and how we solve them:

1. The display font (SHABOUR-SemiBold.otf) uses PostScript/CFF outlines,
   which reportlab's PDF text engine can't embed directly. We rasterize
   title/course-name text at high resolution with Pillow (which uses
   FreeType and handles the font perfectly) and place the result as a
   crisp image on the PDF page -- visually identical, still print-sharp
   at normal menu sizes. Body text (ingredient descriptions) uses Avenir,
   a normal TrueType font, so it's drawn as real vector text.

2. The real menu is printed two-up (two identical cards side by side on
   one sheet, meant to be cut apart). We lay out one card in a reusable
   function and call it twice at different x-offsets on the sheet.

The divider between course groups uses the real Voyage Shabour logo symbol
(assets/icons/shabour_symbol.png, extracted from shabour_logosymbol_pattern.jpg),
drawn twice side by side, matching the original design.

Because this is a fixed template, add/remove of courses doesn't move
boxes -- everything just flows top-to-bottom on the card. If the content
no longer fits, generate_pdf() returns a warning instead of silently
overflowing off the card.
"""
import io
import os
import re

from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit, ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

RENDER_SCALE = 300 / 72.0  # rasterize display-font text at 300dpi equivalent

_registered_fonts = set()

# reportlab bakes these 14 fonts into every PDF reader -- no file, no
# registration, just use the name directly with c.setFont(). Used for the
# wine list's serif text roles (category headings + item lines), which
# match the original InDesign design's classic book-serif look without
# needing to source and embed an external font file.
_STANDARD_PDF_FONTS = {
    "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic",
    "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique",
    "Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique",
    "Symbol", "ZapfDingbats",
}


def _hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _register_body_font(path):
    # A bare standard-font name (not a file path) -- reportlab already
    # knows it, so there's nothing to register.
    if path in _STANDARD_PDF_FONTS:
        return path
    name = os.path.splitext(os.path.basename(path))[0]
    if name not in _registered_fonts:
        pdfmetrics.registerFont(TTFont(name, path))
        _registered_fonts.add(name)
    return name


def _render_display_text(text, font_path, size_pt):
    """Rasterizes text with the brand display font. Returns (ImageReader,
    width_pt, height_pt) ready to draw on a reportlab canvas."""
    text = _sanitize_for_display_font(text, font_path)
    px_size = int(round(size_pt * RENDER_SCALE))
    font = ImageFont.truetype(font_path, px_size)

    # Measure first, with padding so accents/dots above letters aren't clipped
    tmp = Image.new("RGBA", (10, 10), (255, 255, 255, 0))
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), text, font=font)
    pad = int(px_size * 0.15)
    w = (bbox[2] - bbox[0]) + pad * 2
    h = (bbox[3] - bbox[1]) + pad * 2

    img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    d.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=(17, 17, 17, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf), w / RENDER_SCALE, h / RENDER_SCALE


def _draw_display_centered(c, text, font_path, size_pt, center_x, top_y):
    """Draws rasterized display-font text centered horizontally, top edge
    at top_y. Returns the y position just below the drawn text."""
    if not text.strip():
        return top_y
    img, w, h = _render_display_text(text, font_path, size_pt)
    x = center_x - w / 2
    y = top_y - h
    c.drawImage(img, x, y, width=w, height=h, mask="auto")
    return y


def _draw_display_left(c, text, font_path, size_pt, left_x, baseline_y):
    """Draws rasterized display-font text left-aligned, sitting on the given
    baseline so it lines up with text drawn normally on the same line.

    Needed because the brand display font (SHABOUR) has PostScript outlines
    that reportlab cannot embed as live text -- it has to be rasterised. The
    wine list's category headings are set in it, so they take this path
    rather than setFont().
    """
    if not text.strip():
        return
    img, w, h = _render_display_text(text, font_path, size_pt)
    # _render_display_text returns the full inked box; sit it on the baseline
    # with a small descender allowance so it matches adjacent live text.
    c.drawImage(img, left_x, baseline_y - h * 0.18, width=w, height=h, mask="auto")


def _draw_display_aligned(c, text, font_path, size_pt, left_x, right_x, top_y, align="center"):
    """Like _draw_display_centered(), but the alignment within [left_x,
    right_x] is a choice (left/center/right) instead of always centered --
    used for page titles, whose alignment is now admin-editable. Returns
    the y position just below the drawn text."""
    if not text.strip():
        return top_y
    img, w, h = _render_display_text(text, font_path, size_pt)
    if align == "left":
        x = left_x
    elif align == "right":
        x = right_x - w
    else:
        x = (left_x + right_x) / 2 - w / 2
    y = top_y - h
    c.drawImage(img, x, y, width=w, height=h, mask="auto")
    return y


def _draw_role_text(c, text, font_info, size_pt, left_x, right_x, baseline_y, align="left"):
    """Draws one line of text for a text role that may be either a live
    registered font or a rasterised display font (see _resolve_role_fonts),
    at the given horizontal alignment within [left_x, right_x], sitting on
    baseline_y. Used for the categorized-list engine's category/subgroup
    headings, where the same role can be either kind of font depending on
    which font file the template's config points it at."""
    if not text.strip():
        return
    if font_info["raster"]:
        img, w, h = _render_display_text(text, font_info["path"], size_pt)
        if align == "left":
            x = left_x
        elif align == "right":
            x = right_x - w
        else:
            x = (left_x + right_x) / 2 - w / 2
        c.drawImage(img, x, baseline_y - h * 0.18, width=w, height=h, mask="auto")
    else:
        c.setFont(font_info["name"], size_pt)
        if align == "left":
            c.drawString(left_x, baseline_y, text)
        elif align == "right":
            c.drawRightString(right_x, baseline_y, text)
        else:
            c.drawCentredString((left_x + right_x) / 2, baseline_y, text)


_display_font_cmap_cache = {}

# The brand display font (SHABOUR-SemiBold) is a stylized headline face with
# a limited glyph set -- it covers A-Z/0-9/basic punctuation and accented
# Latin letters, but is missing a few ordinary characters (no "+", no "°").
# Rather than let those render as a missing-glyph tofu box when a whole
# recipe card's body text is set in it, swap in a close, legible substitute
# before rasterizing.
_DISPLAY_FONT_SUBSTITUTIONS = {"+": "&", "°": " C"}


def _get_display_font_cmap(font_path):
    if font_path not in _display_font_cmap_cache:
        try:
            from fontTools.ttLib import TTFont as _FTFont
            _display_font_cmap_cache[font_path] = set(_FTFont(font_path).getBestCmap().keys())
        except Exception:
            _display_font_cmap_cache[font_path] = None  # unknown -> don't sanitize
    return _display_font_cmap_cache[font_path]


def _sanitize_for_display_font(text, font_path):
    cmap = _get_display_font_cmap(font_path)
    if not cmap:
        return text
    out = []
    for ch in text:
        if ord(ch) in cmap:
            out.append(ch)
        elif ch in _DISPLAY_FONT_SUBSTITUTIONS:
            out.append(_DISPLAY_FONT_SUBSTITUTIONS[ch])
        # else: silently drop a character the font truly has no glyph for
    return "".join(out)


_display_font_cache = {}


def _get_display_pil_font(font_path, size_pt):
    """Cached PIL font object at a given point size, used for measuring
    (not drawing) rasterized display-font text -- e.g. to word-wrap it
    before calling _render_display_text() line by line."""
    key = (font_path, size_pt)
    if key not in _display_font_cache:
        px_size = int(round(size_pt * RENDER_SCALE))
        _display_font_cache[key] = ImageFont.truetype(font_path, px_size)
    return _display_font_cache[key]


def _display_text_width(text, font_path, size_pt):
    text = _sanitize_for_display_font(text, font_path)
    font = _get_display_pil_font(font_path, size_pt)
    bbox = font.getbbox(text)
    return (bbox[2] - bbox[0]) / RENDER_SCALE


def _wrap_text_for_display_font(text, font_path, size_pt, max_width_pt):
    """Word-wraps plain text (no bold markup) to fit max_width_pt, measuring
    with the actual brand display font's metrics -- since SHABOUR's glyph
    widths differ from any live font, reportlab's simpleSplit() can't be
    used for it. Returns a list of line strings (never empty)."""
    words = text.split()
    if not words:
        return [""]
    lines = []
    current = []
    for word in words:
        trial = " ".join(current + [word])
        if current and _display_text_width(trial, font_path, size_pt) > max_width_pt:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


_divider_image_cache = {}


def _get_divider_image(icon_path):
    if icon_path not in _divider_image_cache:
        img = Image.open(icon_path)
        _divider_image_cache[icon_path] = (ImageReader(img), img.width, img.height)
    return _divider_image_cache[icon_path]


def _draw_divider(c, center_x, top_y, icon_path, icon_height, gap_between=6):
    """Draws the real Voyage Shabour logo symbol (diamond outline with an
    8-point star), two copies side by side, matching the original design."""
    reader, px_w, px_h = _get_divider_image(icon_path)
    h = icon_height
    w = h * (px_w / px_h)

    y = top_y - h
    c.drawImage(reader, center_x - gap_between / 2 - w, y, width=w, height=h, mask="auto")
    c.drawImage(reader, center_x + gap_between / 2, y, width=w, height=h, mask="auto")
    return y


def _draw_wrapped_centered(c, text, center_x, top_y, max_width, font_name, size, leading, color):
    c.setFont(font_name, size)
    c.setFillColorRGB(*_hex_to_rgb(color))
    lines = simpleSplit(text, font_name, size, max_width)
    y = top_y
    for line in lines:
        c.drawCentredString(center_x, y - size, line)
        y -= leading
    c.setFillColorRGB(0, 0, 0)
    return y


def _draw_wrapped_aligned(c, text, center_x, top_y, max_width, font_name, size, leading, color, align="center"):
    """Like _draw_wrapped_centered(), but the alignment of each wrapped
    line is a choice (left/center/right) instead of always centered --
    used for the tasting-menu card's text, whose alignment is now
    admin-editable."""
    c.setFont(font_name, size)
    c.setFillColorRGB(*_hex_to_rgb(color))
    lines = simpleSplit(text, font_name, size, max_width)
    y = top_y
    for line in lines:
        if align == "left":
            c.drawString(center_x - max_width / 2, y - size, line)
        elif align == "right":
            c.drawRightString(center_x + max_width / 2, y - size, line)
        else:
            c.drawCentredString(center_x, y - size, line)
        y -= leading
    c.setFillColorRGB(0, 0, 0)
    return y


def _draw_crop_marks(c, x, y, w, h, sheet_w, length=5, gap=2, mid_mark=False):
    """Small, subtle corner tick marks, so the print shop (or a guillotine)
    has a cut reference. Off by default -- turned on per-template via
    cfg["crop_marks"] (visible as a checkbox in the admin panel).

    On these templates the printed sheet is exactly the size of the card(s)
    (no bleed margin around the outside), so marks drawn just outside the
    trim edge -- the traditional way -- would fall off the page and never
    print. Instead each mark is a tiny L-shaped bracket sitting just inside
    the corner, in the card's own margin whitespace.

    mid_mark also adds a small tick at the sheet's horizontal centre, top
    and bottom -- only meaningful for two-up layouts, where that's the cut
    between the two cards."""
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.setLineWidth(0.3)
    top = y + h

    def corner(cx, cy, dx, dy):
        c.line(cx, cy, cx + dx * length, cy)
        c.line(cx, cy, cx, cy + dy * length)

    corner(x + gap, y + gap, 1, 1)          # bottom-left
    corner(x + w - gap, y + gap, -1, 1)     # bottom-right
    corner(x + gap, top - gap, 1, -1)       # top-left
    corner(x + w - gap, top - gap, -1, -1)  # top-right

    if mid_mark:
        mid = sheet_w / 2.0
        c.line(mid, y + gap, mid, y + gap + length)
        c.line(mid, top - gap, mid, top - gap - length)

    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(1)


def render_card(c, origin_x, cfg, menu_data, body_font, origin_y=0, wine_font=None):
    """Draws one full menu card at the given offset on the sheet.

    origin_y lets the caller centre the card block vertically on a sheet
    that is taller than the card (e.g. cards on a real A4 page).

    wine_font: bold face used for the per-course wine line on wine-pairing
    menus. Falls back to body_font (regular weight) if not given.

    Returns True if content overflowed the card height."""
    wine_font = wine_font or body_font
    cw = cfg["card_width"]
    ch = cfg["card_height"]
    center_x = origin_x + cw / 2
    max_width = cw - 2 * cfg["margin_side"]
    bottom_limit = origin_y + cfg["margin_bottom"]
    display_font = cfg["fonts"]["display"]
    align = cfg.get("alignment", {})

    y = origin_y + ch - cfg["margin_top"]
    overflowed = False

    icon_path = cfg["divider_icon_path"]
    icon_height = cfg.get("divider_icon_height", 16)

    y = _draw_display_aligned(c, menu_data.get("title", ""), display_font, cfg["title_size"],
                              center_x - max_width / 2, center_x + max_width / 2, y,
                              align.get("title", "center"))
    y -= cfg["gap_after_title"]

    if menu_data.get("subtitle"):
        subtitle_size = cfg.get("subtitle_size", cfg.get("description_size", 10))
        y = _draw_wrapped_aligned(
            c, menu_data["subtitle"], center_x, y, max_width, body_font,
            subtitle_size, cfg.get("description_line_height", subtitle_size + 3),
            cfg.get("subtitle_color", "#555555"), align.get("subtitle", "center"),
        )
        y -= cfg.get("gap_after_subtitle", cfg["gap_after_title"])

    y = _draw_divider(c, center_x, y, icon_path, icon_height)
    y -= cfg["gap_after_divider"]

    def draw_course_group(items):
        nonlocal y, overflowed
        for item in items:
            name = (item.get("name") or "").strip()
            desc = (item.get("description") or "").strip()
            wine = (item.get("wine") or "").strip()
            if not name and not desc:
                continue
            if y < bottom_limit:
                overflowed = True
                return
            if name:
                y = _draw_display_aligned(c, name, display_font, cfg["course_name_size"],
                                          center_x - max_width / 2, center_x + max_width / 2, y,
                                          align.get("course_name", "center"))
                y -= cfg["gap_name_to_desc"]
            if desc:
                y = _draw_wrapped_aligned(
                    c, desc, center_x, y, max_width, body_font,
                    cfg["description_size"], cfg["description_line_height"],
                    cfg["description_color"], align.get("description", "center"),
                )
            # Wine-pairing menus carry an extra line per course naming the
            # wine served with it. Set slightly smaller and lighter than the
            # dish description so the two don't compete.
            if wine:
                y -= cfg.get("gap_desc_to_wine", 4)
                y = _draw_wrapped_aligned(
                    c, wine, center_x, y, max_width, wine_font,
                    cfg.get("wine_size", cfg["description_size"] - 0.5),
                    cfg["description_line_height"],
                    cfg.get("wine_color", "#6b5a45"), align.get("description", "center"),
                )
            y -= cfg["gap_between_courses"]

    draw_course_group(menu_data.get("courses", []))

    if menu_data.get("dessert"):
        if y < bottom_limit:
            overflowed = True
        else:
            y = _draw_divider(c, center_x, y, icon_path, icon_height)
            y -= cfg["gap_after_divider"]
            draw_course_group(menu_data["dessert"])

    if y < bottom_limit:
        overflowed = True

    # Report where the content finished so the caller can measure how tall
    # the block actually is and re-draw it optically centred on the card.
    return overflowed, y


def generate_pdf(menu_data, cfg, output_path, base_dir):
    """
    menu_data: dict with title/courses/dessert (see sample_data)
    cfg: dict loaded from config/templates/<template>.json
    output_path: where to write the final PDF
    base_dir: app root, so font paths in cfg (relative) resolve correctly

    Returns: {"ok": bool, "warnings": [str, ...]}
    """
    body_font_path = os.path.join(base_dir, cfg["fonts"]["body"])
    body_font = _register_body_font(body_font_path)

    # Wine-pairing menus set the per-course wine line in a bold weight so it
    # stands out from the dish description above it. Falls back to the
    # regular body font if a template doesn't specify a bold face.
    wine_bold_rel = cfg["fonts"].get("wine_bold")
    if wine_bold_rel:
        wine_font = _register_body_font(os.path.join(base_dir, wine_bold_rel))
    else:
        wine_font = body_font

    display_font_path = os.path.join(base_dir, cfg["fonts"]["display"])
    cfg = dict(cfg)
    cfg["fonts"] = {"display": display_font_path, "body": body_font_path}
    cfg["divider_icon_path"] = os.path.join(base_dir, cfg["divider_icon"])

    card_w, card_h = cfg["card_width"], cfg["card_height"]

    # The printed sheet is a real paper size (A4 landscape by default), NOT
    # simply "two cards wide". Emitting a non-standard page made every
    # printer scale and shift the artwork to fit A4, so nothing landed
    # centred and the cut line drifted off the fold. We now lay the cards
    # out on a true sheet and centre them on it.
    sheet_w = cfg.get("sheet_width", card_w * 2)
    sheet_h = cfg.get("sheet_height", card_h)

    block_w = card_w * 2
    offset_x = (sheet_w - block_w) / 2.0
    offset_y = (sheet_h - card_h) / 2.0

    # Menus vary in length, so a fixed top margin leaves a short menu
    # stranded at the top of the card with a big gap underneath. Measure the
    # block on a throwaway canvas first, then shift it so the whitespace is
    # shared evenly top and bottom -- which is what "centred" looks like
    # once the card is cut out.
    if cfg.get("vertical_center", True):
        probe = canvas.Canvas(io.BytesIO(), pagesize=(sheet_w, sheet_h))
        _, end_y = render_card(probe, offset_x, cfg, menu_data, body_font, offset_y, wine_font)
        content_top = offset_y + card_h - cfg["margin_top"]
        used = content_top - end_y
        slack = (card_h - cfg["margin_top"] - cfg["margin_bottom"]) - used
        if slack > 0:
            offset_y -= slack / 2.0

    c = canvas.Canvas(output_path, pagesize=(sheet_w, sheet_h))

    overflow_1, _ = render_card(c, offset_x, cfg, menu_data, body_font, offset_y, wine_font)
    overflow_2, _ = render_card(c, offset_x + card_w, cfg, menu_data, body_font, offset_y, wine_font)

    if cfg.get("crop_marks", False):
        _draw_crop_marks(c, offset_x, offset_y, block_w, card_h, sheet_w, mid_mark=True)

    c.showPage()
    c.save()

    warnings = []
    if overflow_1 or overflow_2:
        warnings.append(
            "This menu has more text than fits on the printed card. "
            "Shorten a course description or two before printing."
        )

    return {"ok": True, "warnings": warnings, "path": output_path}


# ---------------------------------------------------------------------------
# "Price card" layout -- for the Aperitifs / Digestifs-style menus, which are
# a flowing sequence of: title, a price line, a divider, a section header,
# another price line, an item list (name + price per line, grouped in blocks
# with blank spacers), and a footer. Covers both the two-up cards (Aperitifs
# Voyage/Voyagette) and the single-page summary cards (Exterieur
# Voyage/Voyagette), which are really the same content shape with fewer
# lines filled in. Exact per-field font sizes came from the real IDML data
# (title 34pt Shabour, price 18pt Avenir, section header 24pt Shabour,
# accord price 15pt Avenir); item/footer sizes are close estimates from the
# rendered proportions since the source frame reported flowing text as a
# single run rather than per-line styling.
# ---------------------------------------------------------------------------

def _draw_left_or_center_line(c, text, center_x, y, max_width, font_name, size, color):
    c.setFont(font_name, size)
    c.setFillColorRGB(*_hex_to_rgb(color))
    c.drawCentredString(center_x, y, text)
    c.setFillColorRGB(0, 0, 0)


def render_price_card(c, origin_x, cfg, content, body_font, origin_y=0, heading_font=None):
    """Draws one price-card at the given offset. origin_y allows centring the
    card on a sheet taller than the card. Returns True if content overflowed
    the card height."""
    heading_font = heading_font or body_font
    cw = cfg["card_width"]
    ch = cfg["card_height"]
    center_x = origin_x + cw / 2
    max_width = cw - 2 * cfg["margin_side"]
    bottom_limit = origin_y + cfg["margin_bottom"]
    display_font = cfg["fonts"]["display"]
    icon_path = cfg["divider_icon_path"]
    icon_height = cfg.get("divider_icon_height", 14)
    overflowed = False

    y = origin_y + ch - cfg["margin_top"]

    if cfg.get("top_icon"):
        y = _draw_divider(c, center_x, y, icon_path, icon_height)
        y -= cfg["gap_after_top_icon"]

    if content.get("title"):
        y = _draw_display_centered(c, content["title"], display_font, cfg["title_size"], center_x, y)
        y -= cfg["gap_after_title"]

    if content.get("subtitle"):
        subtitle_size = cfg.get("subtitle_size", cfg["price_size"])
        y -= subtitle_size
        _draw_left_or_center_line(c, content["subtitle"], center_x, y, max_width, body_font, subtitle_size, "#555555")
        y -= cfg.get("gap_after_subtitle", cfg["gap_after_price"])

    if content.get("price"):
        y -= cfg["price_size"]
        _draw_left_or_center_line(c, content["price"], center_x, y, max_width, body_font, cfg["price_size"], "#111111")
        y -= cfg["gap_after_price"]

    if content.get("subprice"):
        y -= cfg["price_size"]
        _draw_left_or_center_line(c, content["subprice"], center_x, y, max_width, body_font, cfg["price_size"], "#111111")
        y -= cfg["gap_after_price"]

    if cfg.get("mid_icon"):
        y = _draw_divider(c, center_x, y, icon_path, icon_height)
        y -= cfg["gap_after_mid_icon"]

    if content.get("accord_header"):
        y = _draw_display_centered(c, content["accord_header"], display_font, cfg["accord_header_size"], center_x, y)
        y -= cfg["gap_after_title"]

    if content.get("accord_price"):
        y -= cfg["price_size"]
        _draw_left_or_center_line(c, content["accord_price"], center_x, y, max_width, body_font, cfg["price_size"], "#111111")
        y -= cfg["gap_after_price"]

    for extra_line in content.get("accord_extra_lines", []):
        extra_line = (extra_line or "").strip()
        if not extra_line:
            continue
        if y < bottom_limit:
            overflowed = True
            break
        y -= cfg["price_size"]
        _draw_left_or_center_line(c, extra_line, center_x, y, max_width, body_font, cfg["price_size"], "#111111")
        y -= cfg["gap_after_price"]

    if content.get("section_header"):
        if y < bottom_limit:
            overflowed = True
        else:
            y = _draw_display_centered(c, content["section_header"], display_font, cfg["section_header_size"], center_x, y)
            y -= cfg["gap_after_title"]

    for line in content.get("items", []):
        if y < bottom_limit:
            overflowed = True
            break
        if line.get("blank"):
            y -= cfg["item_blank_gap"]
            continue
        if line.get("heading"):
            heading_text = (line.get("heading") or "").strip()
            if heading_text:
                heading_size = cfg.get("item_heading_size", cfg["item_size"] + 1.5)
                y -= heading_size
                _draw_left_or_center_line(c, heading_text, center_x, y, max_width, heading_font, heading_size, "#111111")
                y -= cfg.get("item_heading_gap", cfg["item_line_gap"] + 2)
            continue
        text = (line.get("text") or "").strip()
        if not text:
            continue
        y -= cfg["item_size"]
        _draw_left_or_center_line(c, text, center_x, y, max_width, body_font, cfg["item_size"], "#111111")
        y -= cfg["item_line_gap"]

    if content.get("footer_lines"):
        y -= cfg["gap_before_footer"]
        for line in content["footer_lines"]:
            if not line.strip():
                continue
            if y < 8:
                overflowed = True
                break
            y -= cfg["footer_size"]
            _draw_left_or_center_line(c, line, center_x, y, max_width, body_font, cfg["footer_size"], "#444444")
            y -= cfg["footer_line_gap"]

    if cfg.get("bottom_icon"):
        y -= cfg["gap_before_bottom_icon"]
        y = _draw_divider(c, center_x, y, icon_path, icon_height)

    if y < 0:
        overflowed = True

    return overflowed


def generate_price_card_pdf(content, cfg, output_path, base_dir):
    """
    content: dict with title/price/subprice/accord_header/accord_price/
             section_header/items/footer_lines (see sample_data)
    cfg: dict loaded from config/templates/<template>.json
    output_path: where to write the final PDF
    base_dir: app root, so font paths in cfg (relative) resolve correctly

    Returns: {"ok": bool, "warnings": [str, ...]}
    """
    body_font_path = os.path.join(base_dir, cfg["fonts"]["body"])
    body_font = _register_body_font(body_font_path)

    # Sub-headings inside the Drinks List use a bolder weight than the
    # regular item lines so they read as group labels, not just more items.
    # Falls back to the body font if a template doesn't specify one.
    heading_rel = cfg["fonts"].get("heading")
    if heading_rel:
        heading_font = _register_body_font(os.path.join(base_dir, heading_rel))
    else:
        heading_font = body_font

    display_font_path = os.path.join(base_dir, cfg["fonts"]["display"])
    cfg = dict(cfg)
    cfg["fonts"] = {"display": display_font_path, "body": body_font_path}
    cfg["divider_icon_path"] = os.path.join(base_dir, cfg["divider_icon"])

    card_w, card_h = cfg["card_width"], cfg["card_height"]
    two_up = cfg.get("two_up", False)

    # Same reasoning as the tasting-menu sheet: print onto a real paper size
    # and centre the card(s) on it, rather than emitting a page the exact
    # size of the artwork (which every printer then rescales off-centre).
    block_w = card_w * 2 if two_up else card_w
    sheet_w = cfg.get("sheet_width", block_w)
    sheet_h = cfg.get("sheet_height", card_h)
    offset_x = (sheet_w - block_w) / 2.0
    offset_y = (sheet_h - card_h) / 2.0

    c = canvas.Canvas(output_path, pagesize=(sheet_w, sheet_h))

    overflow = render_price_card(c, offset_x, cfg, content, body_font, offset_y, heading_font)
    if two_up:
        overflow_2 = render_price_card(c, offset_x + card_w, cfg, content, body_font, offset_y, heading_font)
        overflow = overflow or overflow_2

    if cfg.get("crop_marks", False):
        _draw_crop_marks(c, offset_x, offset_y, block_w, card_h, sheet_w, mid_mark=two_up)

    c.showPage()
    c.save()

    warnings = []
    if overflow:
        warnings.append(
            "This menu has more text than fits on the printed card. "
            "Shorten the item list before printing."
        )

    return {"ok": True, "warnings": warnings, "path": output_path}


# ---------------------------------------------------------------------------
# "Categorized list" layout -- for big structured price lists like the Wine
# List and Digestifs: a document made of pages, each with a title, and a
# sequence of categories (e.g. "blanc", "whisky"); each category has one or
# more named groups (e.g. a region or country like "France"), and each group
# is a list of name+price lines. Unlike the price-card layout, this one
# auto-paginates: if a page's content runs long (very likely once someone
# adds wines), it continues onto an extra PDF page automatically rather than
# overflowing or warning -- there's no fixed card size to run out of.
# ---------------------------------------------------------------------------

def _wrap_text_to_width(c, text, font_name, size, max_width):
    """Greedy word-wrap of `text` into lines that each fit within
    max_width at the given font/size."""
    words = text.split(" ")
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or c.stringWidth(candidate, font_name, size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def _plan_item_line(c, name, price, avail_width, font_name, size, price_suffix=" €"):
    """Decide how to lay out one "name ......... price" row within
    avail_width. In a narrow column (see the 2-column fallback in
    _CategorizedListFlow) a long wine name can run right into the price at
    the row's normal size, so:
      1. try it on one line at normal size,
      2. if that overlaps, shrink this one line slightly (down to a gentle
         floor) -- most long-but-not-extreme lines resolve here,
      3. if it's still too long even shrunk, wrap the name onto extra
         lines instead of shrinking further into illegibility, with the
         price on the last line.

    Returns (lines, font_size, price_text): `lines` is drawn top-to-bottom
    at font_size, and price_text is right-aligned alongside the last line.
    """
    price_text = f"{price}{price_suffix}" if price else ""
    gap = 6  # minimum breathing room between the name and the price
    usable = avail_width - gap

    name_w = c.stringWidth(name, font_name, size)
    price_w = c.stringWidth(price_text, font_name, size) if price_text else 0

    if usable <= 0 or name_w + price_w <= usable:
        return [name], size, price_text

    floor = 0.6
    shrunk_scale = usable / (name_w + price_w) if (name_w + price_w) > 0 else 1.0
    if shrunk_scale >= floor:
        return [name], size * shrunk_scale, price_text

    # Still doesn't fit even at the floor -- wrap instead of shrinking
    # further into illegibility.
    wrap_size = size * floor
    lines = _wrap_text_to_width(c, name, font_name, wrap_size, avail_width)
    last_w = c.stringWidth(lines[-1], font_name, wrap_size) if lines else 0
    if price_text and last_w + price_w > usable:
        lines.append("")  # price doesn't even fit next to the last wrapped line -- give it its own
    return lines, wrap_size, price_text


def _draw_item_line(c, name, price, x_left, x_right, y_top, item_size, font_name, price_suffix=" €"):
    """Draws one item row (possibly wrapped across multiple lines -- see
    _plan_item_line) with its first line's baseline at y_top, each
    subsequent line item_size below the last. Returns the y just below the
    last line drawn, i.e. where the next row/gap should start from."""
    lines, line_size, price_text = _plan_item_line(c, name, price, x_right - x_left, font_name, item_size, price_suffix)
    c.setFont(font_name, line_size)
    c.setFillColorRGB(0.05, 0.05, 0.05)
    y = y_top
    for i, line in enumerate(lines):
        c.drawString(x_left, y, line)
        if i == len(lines) - 1 and price_text:
            c.drawRightString(x_right, y, price_text)
        y -= item_size
    c.setFillColorRGB(0, 0, 0)
    return len(lines)


class _CategorizedListFlow:
    """Tracks the y-cursor for one output PDF page and starts a new page
    (with a '(suite)' continuation title) automatically on overflow.

    A page that's too dense to fit in a single column first falls back to a
    second column on the SAME physical page (see n_columns / _new_column)
    before ever spilling onto an extra "(suite)" page -- see
    generate_categorized_list_pdf for how a page's column count is decided."""

    # Fixed gutter between the two columns when a page needs them. Not part
    # of _SCALABLE_KEYS -- it's a layout gap, not text, so it stays constant
    # regardless of the shared font shrink scale.
    COLUMN_GAP = 26

    def __init__(self, c, cfg, role_fonts, display_font_path, title_text, already_started=False, n_columns=1):
        self.c = c
        self.cfg = cfg
        # One registered font name per text role (category / subgroup / item
        # / note), so a list can mix Avenir weights the way the original
        # InDesign document does.
        self.fonts = role_fonts
        self.body_font = role_fonts["item"]["name"]
        self.display_font_path = display_font_path
        self.title_text = title_text
        self.page_w = cfg["page_width"]
        self.page_h = cfg["page_height"]
        self.margin_side = cfg["margin_side"]
        self.bottom_limit = cfg["margin_bottom"]
        self.n_columns = max(1, n_columns)
        self.column_index = 0
        self.col_bounds = self._compute_column_bounds()
        self.col_left, self.col_right = self.col_bounds[0]
        # needs_showpage: whether the canvas already has a page in progress
        # (i.e. this is not the very first page of the whole document) --
        # if so, the first _new_page() call here must still emit a showPage()
        # to end that prior page before starting this logical page's title.
        self.needs_showpage = already_started
        # is_overflow: becomes True once this flow has started a second (or
        # later) physical page for its OWN content overflowing -- that's the
        # only case that gets a "(suite)" label, not just "another logical
        # page is starting".
        self.is_overflow = False
        self.overflowed = False
        self._new_page()

    def _compute_column_bounds(self):
        """Left/right x for each column. With n_columns=1 this is just the
        page's normal margins; with 2, the content width is split in half
        around a fixed gutter so item rows still line up cleanly."""
        if self.n_columns <= 1:
            return [(self.margin_side, self.page_w - self.margin_side)]
        content_w = (self.page_w - 2 * self.margin_side) - self.COLUMN_GAP
        col_w = content_w / self.n_columns
        bounds = []
        x = self.margin_side
        for _ in range(self.n_columns):
            bounds.append((x, x + col_w))
            x += col_w + self.COLUMN_GAP
        return bounds

    def _new_page(self):
        if self.needs_showpage:
            self.c.showPage()
        cfg = self.cfg
        align = cfg.get("alignment", {})
        y = self.page_h - cfg["margin_top"]
        title = self.title_text + (" (suite)" if self.is_overflow else "")
        y = _draw_display_aligned(
            self.c, title, self.display_font_path, cfg["page_title_size"],
            self.margin_side, self.page_w - self.margin_side, y,
            align.get("page_title", "center"),
        )
        self.top_y = y - cfg["gap_after_page_title"]
        self.y = self.top_y
        self.column_index = 0
        self.col_left, self.col_right = self.col_bounds[0]
        self.needs_showpage = True
        self.is_overflow = True

    def _new_column(self):
        self.column_index += 1
        self.col_left, self.col_right = self.col_bounds[self.column_index]
        self.y = self.top_y

    def ensure_space(self, needed):
        if self.y - needed < self.bottom_limit:
            if self.column_index + 1 < self.n_columns:
                # Same physical page, next column over -- not an overflow.
                self._new_column()
            else:
                self.overflowed = True  # more than one page was needed -- expected for long lists, not an error
                self._new_page()

    def draw_category(self, category):
        cfg = self.cfg
        align = cfg.get("alignment", {})
        def _apply_casing(text, mode):
            # mode: True -> ALL CAPS, "lower" -> all lowercase ("latin small
            # letter" forms -- e.g. useful with Shabour Semibold, whose caps
            # get a decorative dot per letter but lowercase glyphs render
            # clean/undotted, see the font's cmap), False/anything else ->
            # keep the name exactly as typed. str.upper()/.lower() both
            # handle accented French letters correctly.
            if mode is True:
                return text.upper()
            if mode == "lower":
                return text.lower()
            return text

        # A category with a price note (e.g. "verre 10cl") assumes the name
        # sits at the left with the note anchored to the right -- centering
        # or right-aligning the name in that case would run the two
        # together, so the note pins the name to "left" regardless of the
        # configured alignment.
        cat_align = "left" if category.get("note") else align.get("category", "left")

        self.ensure_space(cfg["category_size"] + cfg["gap_after_category"])
        self.y -= cfg["category_size"]
        cat_font = self.fonts["category"]
        self.c.setFillColorRGB(0.05, 0.05, 0.05)
        # Category headings render in caps by default, regardless of how
        # the name is typed in the editor (e.g. "champagne et effervescent"
        # -> "CHAMPAGNE ET EFFERVESCENT") -- works whether the role ends up
        # live text or the raster SHABOUR path (see
        # _resolve_role_fonts/_draw_role_text). A page (or the document)
        # can override via cfg["category_uppercase"]: false keeps the
        # name's original typed casing, "lower" forces all-lowercase (see
        # _apply_casing) -- e.g. for Shabour Semibold, whose lowercase
        # letterforms render clean/undotted versus the fully-dotted caps.
        cat_name = _apply_casing(category.get("name", ""), cfg.get("category_uppercase", True))
        _draw_role_text(self.c, cat_name, cat_font, cfg["category_size"],
                        self.col_left, self.col_right, self.y, cat_align)

        if category.get("note"):
            note_font = self.fonts["note"]
            if not note_font["raster"]:
                self.c.setFont(note_font["name"], cfg["note_size"])
                self.c.drawRightString(self.col_right, self.y, category["note"])
        self.c.setFillColorRGB(0, 0, 0)
        self.y -= cfg["gap_after_category"]

        for group_idx, group in enumerate(category.get("groups", [])):
            if group.get("name"):
                # Breathing room ABOVE each subgroup label (separating it
                # from the previous subgroup's last item), not just below it
                # -- the label should sit close to its own wines, not float
                # in the middle of a gap. Skipped for the very first
                # subgroup in a category, since gap_after_category already
                # provides that separation from the category header.
                gap_before = cfg.get("gap_before_subgroup", 0) if group_idx > 0 else 0
                self.ensure_space(gap_before + cfg["subgroup_size"] + cfg["gap_after_subgroup"])
                self.y -= gap_before
                self.y -= cfg["subgroup_size"]
                sub_font = self.fonts["subgroup"]
                self.c.setFillColorRGB(0.15, 0.15, 0.15)
                # Subgroup headings keep their typed casing by default --
                # unlike category, which defaults to forced caps. A page
                # (or the document) can override via cfg["subgroup_uppercase"]:
                # true forces ALL CAPS, "lower" forces all-lowercase (see
                # _apply_casing above). Mirrors category_uppercase, just
                # with the opposite default.
                sub_name = _apply_casing(group["name"], cfg.get("subgroup_uppercase", False))
                _draw_role_text(self.c, sub_name, sub_font, cfg["subgroup_size"],
                                self.col_left, self.col_right, self.y, align.get("subgroup", "left"))
                self.c.setFillColorRGB(0, 0, 0)
                self.y -= cfg["gap_after_subgroup"]

            for item in group.get("items", []):
                text = (item.get("text") or "").strip()
                if not text:
                    continue
                # Plan first (an exceptionally long name+price can wrap onto
                # an extra line -- see _plan_item_line) so ensure_space
                # reserves the right amount of room before anything is
                # drawn, rather than drawing a wrapped row that runs past
                # the bottom margin.
                plan_lines, _, _ = _plan_item_line(
                    self.c, text, item.get("price", ""), self.col_right - self.col_left,
                    self.body_font, cfg["item_size"]
                )
                row_h = cfg["item_size"] * len(plan_lines)
                self.ensure_space(row_h + cfg["gap_after_item"])
                self.y -= cfg["item_size"]
                n_lines = _draw_item_line(
                    self.c, text, item.get("price", ""),
                    self.col_left, self.col_right,
                    self.y, cfg["item_size"], self.body_font,
                )
                self.y -= cfg["item_size"] * (n_lines - 1)
                self.y -= cfg["gap_after_item"]

        self.y -= cfg["gap_after_group_block"]


def _resolve_role_fonts(cfg, base_dir, roles, fallback_key="body"):
    """Resolve a font per text role.

    Returns {role: {"name": registered_name_or_None, "path": abs_path,
                    "raster": bool}}.

    The wine list and digestifs mix several faces: Avenir Light for the long
    wine lines, and the brand SHABOUR face for the category headings.
    SHABOUR has PostScript outlines that reportlab cannot embed as live
    text, so any role using it is flagged raster=True and gets drawn as a
    rasterised image instead. That's what lets a heading use the brand font
    at all.
    """
    fonts_cfg = cfg.get("fonts", {})
    fallback_path = os.path.join(base_dir, fonts_cfg[fallback_key])

    resolved = {}
    for role in roles:
        rel = fonts_cfg.get(role)
        if rel in _STANDARD_PDF_FONTS:
            # Bare standard-font name -- not a file, nothing to join/register.
            resolved[role] = {"name": rel, "path": None, "raster": False}
            continue
        path = os.path.join(base_dir, rel) if rel else fallback_path
        try:
            name = _register_body_font(path)
            raster = False
        except Exception:
            # PostScript/CFF outlines -- rasterise this role instead.
            name, raster = None, True
        resolved[role] = {"name": name, "path": path, "raster": raster}
    return resolved


# Fields a single page is allowed to override via page["layout_overrides"]
# (see generate_categorized_list_pdf): sizes/gaps, plus category_uppercase /
# subgroup_uppercase (bool -- whether that role's names get forced to caps,
# see draw_category). Page dimensions/margins stay document-wide on
# purpose: those affect print alignment across the whole booklet, so
# letting one page drift there would misalign the physical pages when
# printed/cut. This is the escape hatch for "this one page runs long/short
# at the shared size" (or needs different heading casing) without anyone
# needing to touch every other page.
_PAGE_OVERRIDABLE_KEYS = {
    "page_title_size", "category_size", "subgroup_size", "item_size", "note_size",
    "gap_after_page_title", "gap_after_category", "gap_before_subgroup",
    "gap_after_subgroup", "gap_after_item", "gap_after_group_block",
    "category_uppercase", "subgroup_uppercase",
}

# Font roles a single page is allowed to override via
# page["layout_overrides"]["fonts"]. Unlike the numeric keys above, this
# exists specifically because the winelist's category/subgroup roles carry
# different real-world meaning on different pages -- on the "Vins au
# Verre" overview page, category=wine style (Champagne/Blanc/Rose/Rouge)
# and subgroup=country, but on every other page category=country and
# subgroup=sub-region. The two page types need opposite fonts on those two
# roles, so the font can't just be a single document-wide setting.
_PAGE_OVERRIDABLE_FONT_ROLES = {"category", "subgroup", "item", "note"}


def _page_effective_cfg(cfg, page):
    """Shallow-merges a page's optional layout_overrides on top of the
    document-wide cfg: numeric size/gap keys (_PAGE_OVERRIDABLE_KEYS) and,
    separately, a "fonts" sub-dict for role font paths
    (_PAGE_OVERRIDABLE_FONT_ROLES). Unknown keys are ignored (defensive
    against stray/typo'd keys reaching reportlab). Returns cfg unchanged
    (no copy) if the page has no overrides, so the common case stays
    cheap."""
    overrides = page.get("layout_overrides")
    if not overrides:
        return cfg
    clean = {k: v for k, v in overrides.items() if k in _PAGE_OVERRIDABLE_KEYS and v is not None}
    font_overrides = overrides.get("fonts") or {}
    clean_fonts = {k: v for k, v in font_overrides.items() if k in _PAGE_OVERRIDABLE_FONT_ROLES and v}
    if not clean and not clean_fonts:
        return cfg
    page_cfg = dict(cfg)
    page_cfg.update(clean)
    if clean_fonts:
        page_cfg["fonts"] = {**cfg.get("fonts", {}), **clean_fonts}
    return page_cfg


def generate_categorized_list_pdf(content, cfg, output_path, base_dir):
    """
    content: dict with "pages": [{title, categories: [{name, note?, groups:
             [{name?, items: [{text, price}]}]}], layout_overrides?: {...}}]
    cfg: dict loaded from config/templates/<template>.json
    output_path: where to write the final PDF
    base_dir: app root, so font paths in cfg (relative) resolve correctly

    Returns: {"ok": bool, "warnings": [str, ...]}

    Every page uses the SAME font sizes and spacing from cfg by default --
    no automatic per-page shrinking. A page whose content doesn't fit
    spills onto an automatic "(suite)" continuation page instead (see
    ensure_space/_new_page on _CategorizedListFlow), so the list stays
    legible and visually consistent even if that means one section runs
    long. If a specific page needs different sizing (e.g. it's the one
    page that overflows, or its content is short and could run larger),
    it can set its own "layout_overrides" dict with any of
    _PAGE_OVERRIDABLE_KEYS -- only that page is affected. A page can also
    override which font file backs the category/subgroup/item/note roles
    via layout_overrides["fonts"] (see _PAGE_OVERRIDABLE_FONT_ROLES) --
    needed because those two roles mean different things on different
    pages (wine style vs. country vs. sub-region) and so need different
    fonts depending on the page.
    """
    display_font_path = os.path.join(base_dir, cfg["fonts"]["display"])
    c = canvas.Canvas(output_path, pagesize=(cfg["page_width"], cfg["page_height"]))
    pages = content.get("pages", [])
    # Resolved once per distinct fonts-dict (not once globally), since a
    # page's layout_overrides["fonts"] can point roles at different files
    # than the document default -- cheap to redo, and _register_body_font
    # is itself idempotent per font file.
    role_fonts_cache = {}

    any_overflow = False
    for i, page in enumerate(pages):
        categories = page.get("categories", [])
        title = page.get("title", "")
        page_cfg = _page_effective_cfg(cfg, page)
        fonts_key = tuple(sorted(page_cfg.get("fonts", {}).items()))
        if fonts_key not in role_fonts_cache:
            role_fonts_cache[fonts_key] = _resolve_role_fonts(
                page_cfg, base_dir, ("category", "subgroup", "item", "note")
            )
        role_fonts = role_fonts_cache[fonts_key]
        flow = _CategorizedListFlow(
            c, page_cfg, role_fonts, display_font_path, title,
            already_started=(i > 0),
        )
        for category in categories:
            flow.draw_category(category)
        if flow.overflowed:
            any_overflow = True
    c.showPage()
    c.save()

    warnings = []
    if any_overflow:
        warnings.append(
            "One or more sections were too long to fit on a single page at "
            "this font size, so they continue onto a '(suite)' page -- "
            "shorten the list or lower the font size in Layout settings if "
            "you'd rather it stayed on one page."
        )

    return {"ok": True, "warnings": warnings, "path": output_path}


# ---------------------------------------------------------------------------
# Recipe cards (e.g. "Shabour x Licoük" collab cards): a landscape card with
# a rotated brand/title "spine" on the left, an ingredient table, and a
# bulleted method -- repeated several times on one A4 sheet with crop marks,
# so the kitchen can cut out one card per copy.
# ---------------------------------------------------------------------------

def _parse_bold_segments(text):
    """Splits text on **bold** markers into [(chunk, is_bold), ...]. Lets a
    non-technical editor mark a word bold (e.g. a temperature or a time)
    without any rich-text UI -- they just wrap it in ** in the plain text
    field, same convention as Markdown."""
    parts = re.split(r"\*\*(.+?)\*\*", text)
    return [(part, i % 2 == 1) for i, part in enumerate(parts) if part]


def _wrap_bold_segments(c, segments, regular_font, bold_font, size, max_width):
    """Greedy word-wrap across mixed regular/bold runs. Returns a list of
    lines, each a list of (token, is_bold) -- tokens include the spaces
    between words so drawing them back-to-back reproduces normal spacing."""
    tokens = []
    for text, is_bold in segments:
        for tok in re.split(r"(\s+)", text):
            if tok:
                tokens.append((tok, is_bold))

    def token_w(tok, is_bold):
        return c.stringWidth(tok, bold_font if is_bold else regular_font, size)

    def rstrip_line(line):
        while line and line[-1][0].isspace():
            line.pop()
        return line

    lines = []
    current = []
    current_w = 0.0
    for tok, is_bold in tokens:
        w = token_w(tok, is_bold)
        if tok.isspace():
            if current:
                current.append((tok, is_bold))
                current_w += w
            continue
        if current_w + w > max_width and current:
            lines.append(rstrip_line(current))
            current, current_w = [], 0.0
        current.append((tok, is_bold))
        current_w += w
    if current:
        lines.append(rstrip_line(current))
    return lines or [[]]


def _draw_bold_wrapped_line(c, line, x, y, regular_font, bold_font, size):
    cx = x
    for tok, is_bold in line:
        font = bold_font if is_bold else regular_font
        c.setFont(font, size)
        c.drawString(cx, y, tok)
        cx += c.stringWidth(tok, font, size)


def _draw_rotated90(c, x, y, draw_fn):
    """Runs draw_fn(c) with the canvas origin moved to (x, y) and rotated
    90 degrees counter-clockwise, so draw_fn can draw normally starting at
    (0, 0) -- what it draws going "right" ends up running bottom-to-top at
    (x, y) on the real page. Used for the recipe card's vertical spine."""
    c.saveState()
    c.translate(x, y)
    c.rotate(90)
    draw_fn(c)
    c.restoreState()


def _draw_recipe_card(c, x_left, x_right, y_bottom, y_top, cfg, data, fonts, icon_reader_wh):
    """Draws one recipe card in the given box. Returns True if the
    ingredient list or method overflowed the card.

    Everything on the card -- byline, title, ingredients, method, footer --
    reads in ONE consistent direction: rotated 90 degrees bottom-to-top,
    same as the brand title. Rather than hand-deriving rotated coordinates
    per element, the whole card is authored in plain top-to-bottom /
    left-to-right "local" coordinates (exactly like any other normal page
    in this file) inside a single saveState/translate/rotate block -- see
    _draw_rotated90. Reportlab applies that rotation to every drawString /
    drawImage call automatically, so the local code below reads just like
    the rest of this module's layout functions:
      - local "a" (the x-argument) is the reading direction -> ends up
        running bottom-to-top on the printed card (0 = card bottom,
        content_h = card top).
      - local "b" (the y-argument, always <= 0 here) is depth into the
        card, spine -> title -> ingredients -> method (0 = left/spine
        edge, -content_w = right/method edge).
    """
    content_top = y_top - cfg["card_margin_top"]
    content_bottom = y_bottom + cfg["card_margin_bottom"]
    content_h = content_top - content_bottom
    content_w = x_right - x_left
    overflowed = False

    name_font = fonts["body"]["name"]
    bold_font = fonts["bold"]["name"]
    footer_font = fonts["footer"]["name"]
    display_font_path = fonts["display_path"]

    collab = (data.get("collab") or "").strip()
    title_text = (data.get("title") or "").strip()
    footer = (data.get("footer") or "").strip()

    title_img, title_w, title_h = (None, 0.0, 0.0)
    if title_text:
        title_img, title_w, title_h = _render_display_text(title_text, display_font_path, cfg["title_size"])

    icon_reader, icon_px_w, icon_px_h = icon_reader_wh
    icon_thick = cfg.get("spine_icon_height", 7)
    icon_len = icon_thick * (icon_px_w / icon_px_h)

    label_text = "INGREDIENTS:"
    label_size = cfg["ingredients_label_size"]

    overflow_flag = {"v": False}

    def draw_fn(cc):
        # --- byline, centered in the spine band ---
        collab_b = -(cfg["spine_width"] / 2.0)
        if collab:
            size = cfg["collab_size"]
            cc.setFont(bold_font, size)
            text_len = cc.stringWidth(collab, bold_font, size)
            a0 = (content_h - text_len) / 2.0
            cc.drawString(a0, collab_b - size * 0.32, collab)

        # rule between spine and title column
        rule_b = -cfg["spine_width"]
        cc.setStrokeColorRGB(0.15, 0.15, 0.15)
        cc.setLineWidth(0.75)
        cc.line(0, rule_b, content_h, rule_b)
        cc.setStrokeColorRGB(0, 0, 0)
        cc.setLineWidth(1)

        # --- title column: LEMON TART (raster) + icon + "INGREDIENTS:" ---
        label_len = cc.stringWidth(label_text, bold_font, label_size)
        total_len = title_w + cfg["gap_title_to_icon"] + icon_len + cfg["gap_icon_to_label"] + label_len
        title_col_b = -(cfg["spine_width"] + cfg["gap_after_spine"] + cfg["title_col_width"] / 2.0)
        a = (content_h - total_len) / 2.0

        if title_img is not None:
            cc.drawImage(title_img, a, title_col_b - title_h / 2.0, width=title_w, height=title_h, mask="auto")
            a += title_w + cfg["gap_title_to_icon"]

        cc.drawImage(icon_reader, a, title_col_b - icon_thick / 2.0, width=icon_len, height=icon_thick, mask="auto")
        a += icon_len + cfg["gap_icon_to_label"]

        cc.setFont(bold_font, label_size)
        cc.drawString(a, title_col_b - label_size * 0.32, label_text)

        # --- ingredients: name then right-aligned qty, same "line" each ---
        ing_size = cfg["ingredient_size"]
        b = -(cfg["spine_width"] + cfg["gap_after_spine"] + cfg["title_col_width"] + cfg["gap_after_title_col"])
        for ing in data.get("ingredients", []):
            name = (ing.get("name") or "").strip()
            qty = (ing.get("qty") or "").strip()
            if not name and not qty:
                continue
            b -= ing_size
            if -b > content_w:
                overflow_flag["v"] = True
                break
            cc.setFont(name_font, ing_size)
            cc.drawString(0, b, name)
            cc.setFont(bold_font, ing_size)
            cc.drawRightString(content_h, b, qty)
            b -= cfg["ingredient_row_gap"]

        # --- method: bulleted, wrapped, with inline **bold** support ---
        method_size = cfg["method_size"]
        line_h = cfg["method_line_height"]
        bullet_indent = cfg["method_bullet_indent"]
        max_width = content_h - bullet_indent
        b = -(cfg["spine_width"] + cfg["gap_after_spine"] + cfg["title_col_width"] + cfg["gap_after_title_col"]
              + cfg["ingredients_col_width"] + cfg["gap_after_ingredients"])
        for step in data.get("method", []):
            step = (step or "").strip()
            if not step:
                continue
            segments = _parse_bold_segments(step)
            lines = _wrap_bold_segments(cc, segments, name_font, bold_font, method_size, max_width)
            b -= method_size
            if -b > content_w:
                overflow_flag["v"] = True
                break
            cc.setFont(name_font, method_size)
            cc.drawString(0, b, "•")
            _draw_bold_wrapped_line(cc, lines[0], bullet_indent, b, name_font, bold_font, method_size)
            for line in lines[1:]:
                b -= line_h
                if -b > content_w:
                    overflow_flag["v"] = True
                    break
                _draw_bold_wrapped_line(cc, line, bullet_indent, b, name_font, bold_font, method_size)
            b -= cfg["method_gap"]

        # --- footer: small brand/address line, near the far/deep edge ---
        if footer:
            cc.setFont(footer_font, cfg["footer_size"])
            cc.setFillColorRGB(0.55, 0.55, 0.55)
            cc.drawRightString(content_h, -(content_w - 3), footer)
            cc.setFillColorRGB(0, 0, 0)

    _draw_rotated90(c, x_left, content_bottom, draw_fn)
    return overflow_flag["v"]


def generate_recipe_card_pdf(menu_data, cfg, output_path, base_dir):
    """
    menu_data: dict with collab/title/ingredients/method/footer (see
    sample_data/recipe_card).
    cfg: dict loaded from config/templates/<template>.json
    base_dir: app root, so font/icon paths in cfg (relative) resolve

    Repeats the same card cfg["cards_per_sheet"] times (default 3) stacked
    on one A4 sheet, matching the reference "Shabour x Licoük" print file --
    the kitchen cuts the sheet into identical cards.
    """
    fonts = {
        "display_path": os.path.join(base_dir, cfg["fonts"]["display"]),
        "body": {},
        "bold": {},
        "footer": {},
    }
    body_path = os.path.join(base_dir, cfg["fonts"]["body"])
    bold_path = os.path.join(base_dir, cfg["fonts"].get("bold", cfg["fonts"]["body"]))
    footer_path = os.path.join(base_dir, cfg["fonts"].get("footer", cfg["fonts"]["body"]))
    fonts["body"]["name"] = _register_body_font(body_path)
    fonts["bold"]["name"] = _register_body_font(bold_path)
    fonts["footer"]["name"] = _register_body_font(footer_path)

    icon_path = os.path.join(base_dir, cfg.get("spine_icon", "assets/icons/shabour_symbol.png"))
    icon_reader_wh = _get_divider_image(icon_path)

    page_w, page_h = cfg["page_width"], cfg["page_height"]
    cards_per_sheet = max(1, int(cfg.get("cards_per_sheet", 3)))
    card_h = page_h / cards_per_sheet
    x_left = cfg["margin_side"]
    x_right = page_w - cfg["margin_side"]

    c = canvas.Canvas(output_path, pagesize=(page_w, page_h))

    any_overflow = False
    for i in range(cards_per_sheet):
        y_top = page_h - i * card_h
        y_bottom = y_top - card_h
        overflowed = _draw_recipe_card(c, x_left, x_right, y_bottom, y_top, cfg, menu_data, fonts, icon_reader_wh)
        any_overflow = any_overflow or overflowed
        if cfg.get("crop_marks", True):
            _draw_crop_marks(c, x_left, y_bottom, x_right - x_left, card_h, page_w)

    c.showPage()
    c.save()

    warnings = []
    if any_overflow:
        warnings.append(
            "The ingredient list or method is too long for the card -- "
            "shorten it before printing."
        )

    return {"ok": True, "warnings": warnings, "path": output_path}


# ---------------------------------------------------------------------------
# Simple family-recipe cards (e.g. "La Challah Shabour", "Tahini Cookies"):
# a centered title, an "INGREDIENTS:" subtitle + list, and wrapped method
# paragraphs. The title is set in the brand display font (SHABOUR-SemiBold,
# rasterized -- it has PostScript outlines reportlab can't embed as live
# text), matching every other template's title treatment. The "INGREDIENTS:"
# subtitle and all body copy (ingredient lines, method) use a separate,
# plain readable Avenir weight -- drawn as ordinary live vector text --
# since a stylized display face isn't meant for paragraphs of body copy.
# Printed two-up on one landscape sheet, same physical layout as the
# tasting-menu cards (see render_card/generate_pdf above).
# ---------------------------------------------------------------------------

def _draw_simple_recipe_card(c, origin_x, cfg, data, display_font, subtitle_font, body_font, origin_y=0):
    """Draws one simple recipe card at the given sheet offset. Returns
    (overflowed, end_y) -- end_y lets the caller vertically re-center the
    block, same convention as render_card() above."""
    cw = cfg["card_width"]
    ch = cfg["card_height"]
    center_x = origin_x + cw / 2
    left_x = origin_x + cfg["margin_side"]
    right_x = origin_x + cw - cfg["margin_side"]
    max_width = right_x - left_x
    bottom_limit = origin_y + cfg["margin_bottom"]
    overflowed = False

    y = origin_y + ch - cfg["margin_top"]

    title = (data.get("title") or "").strip()
    if title:
        y = _draw_display_centered(c, title, display_font, cfg["title_size"], center_x, y)
    y -= cfg["gap_after_title"]

    ingredients = [ing for ing in data.get("ingredients", [])
                   if (ing.get("name") or "").strip() or (ing.get("qty") or "").strip()]
    if ingredients:
        label_size = cfg["ingredients_label_size"]
        y -= label_size
        if y < bottom_limit:
            overflowed = True
        else:
            c.setFont(subtitle_font, label_size)
            c.drawString(left_x, y, "INGREDIENTS:")
        y -= cfg["gap_after_ingredients_label"]

        ing_size = cfg["ingredient_size"]
        c.setFont(body_font, ing_size)
        for ing in ingredients:
            if overflowed:
                break
            name = (ing.get("name") or "").strip()
            qty = (ing.get("qty") or "").strip()
            line = f"{name} : {qty}" if name and qty else (name or qty)
            y -= ing_size
            if y < bottom_limit:
                overflowed = True
                break
            c.drawString(left_x, y, line)
            y -= cfg["gap_after_ingredient"]
        y -= cfg["gap_after_ingredients_block"]

    method_size = cfg["method_size"]
    line_h = cfg["method_line_height"]
    for step in data.get("method", []):
        if overflowed:
            break
        step = (step or "").strip()
        if not step:
            continue
        segments = _parse_bold_segments(step)
        lines = _wrap_bold_segments(c, segments, body_font, subtitle_font, method_size, max_width)
        y -= method_size
        if y < bottom_limit:
            overflowed = True
            break
        _draw_bold_wrapped_line(c, lines[0], left_x, y, body_font, subtitle_font, method_size)
        for line in lines[1:]:
            y -= line_h
            if y < bottom_limit:
                overflowed = True
                break
            _draw_bold_wrapped_line(c, line, left_x, y, body_font, subtitle_font, method_size)
        y -= cfg["gap_after_method_step"]

    if y < bottom_limit:
        overflowed = True

    return overflowed, y


def generate_simple_recipe_card_pdf(menu_data, cfg, output_path, base_dir):
    """
    menu_data: dict with title/ingredients/method (see sample_data/challah,
    sample_data/tahini_cookies).
    cfg: dict loaded from config/templates/simple_recipe_card.json
    base_dir: app root, so font paths in cfg (relative) resolve

    Two identical cards side by side on one landscape sheet, matching the
    reference InDesign files -- the kitchen cuts the sheet in half.
    """
    display_font = os.path.join(base_dir, cfg["fonts"]["display"])
    subtitle_path = os.path.join(base_dir, cfg["fonts"]["subtitle"])
    body_path = os.path.join(base_dir, cfg["fonts"]["body"])
    subtitle_font = _register_body_font(subtitle_path)
    body_font = _register_body_font(body_path)

    card_w, card_h = cfg["card_width"], cfg["card_height"]
    sheet_w = cfg.get("sheet_width", card_w * 2)
    sheet_h = cfg.get("sheet_height", card_h)

    block_w = card_w * 2
    offset_x = (sheet_w - block_w) / 2.0
    offset_y = (sheet_h - card_h) / 2.0

    # Recipes vary in length, so vertically re-center the block the same
    # way the tasting-menu cards do (see generate_pdf above) rather than
    # leaving a short recipe stranded at the top of the card.
    probe = canvas.Canvas(io.BytesIO(), pagesize=(sheet_w, sheet_h))
    _, end_y = _draw_simple_recipe_card(probe, offset_x, cfg, menu_data, display_font, subtitle_font, body_font, offset_y)
    content_top = offset_y + card_h - cfg["margin_top"]
    used = content_top - end_y
    slack = (card_h - cfg["margin_top"] - cfg["margin_bottom"]) - used
    if slack > 0:
        offset_y -= slack / 2.0

    c = canvas.Canvas(output_path, pagesize=(sheet_w, sheet_h))

    overflow_1, _ = _draw_simple_recipe_card(c, offset_x, cfg, menu_data, display_font, subtitle_font, body_font, offset_y)
    overflow_2, _ = _draw_simple_recipe_card(c, offset_x + card_w, cfg, menu_data, display_font, subtitle_font, body_font, offset_y)

    if cfg.get("crop_marks", True):
        _draw_crop_marks(c, offset_x, offset_y, block_w, card_h, sheet_w, mid_mark=True)

    c.showPage()
    c.save()

    warnings = []
    if overflow_1 or overflow_2:
        warnings.append(
            "The ingredient list or method is too long for the card -- "
            "shorten it before printing."
        )

    return {"ok": True, "warnings": warnings, "path": output_path}
