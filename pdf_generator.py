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

from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit, ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

RENDER_SCALE = 300 / 72.0  # rasterize display-font text at 300dpi equivalent

_registered_fonts = set()


def _hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _register_body_font(path):
    name = os.path.splitext(os.path.basename(path))[0]
    if name not in _registered_fonts:
        pdfmetrics.registerFont(TTFont(name, path))
        _registered_fonts.add(name)
    return name


def _render_display_text(text, font_path, size_pt):
    """Rasterizes text with the brand display font. Returns (ImageReader,
    width_pt, height_pt) ready to draw on a reportlab canvas."""
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


def render_card(c, origin_x, cfg, menu_data, body_font, origin_y=0):
    """Draws one full menu card at the given offset on the sheet.

    origin_y lets the caller centre the card block vertically on a sheet
    that is taller than the card (e.g. cards on a real A4 page).

    Returns True if content overflowed the card height."""
    cw = cfg["card_width"]
    ch = cfg["card_height"]
    center_x = origin_x + cw / 2
    max_width = cw - 2 * cfg["margin_side"]
    bottom_limit = origin_y + cfg["margin_bottom"]
    display_font = cfg["fonts"]["display"]

    y = origin_y + ch - cfg["margin_top"]
    overflowed = False

    icon_path = cfg["divider_icon_path"]
    icon_height = cfg.get("divider_icon_height", 16)

    y = _draw_display_centered(c, menu_data.get("title", ""), display_font, cfg["title_size"], center_x, y)
    y -= cfg["gap_after_title"]

    if menu_data.get("subtitle"):
        subtitle_size = cfg.get("subtitle_size", cfg.get("description_size", 10))
        y = _draw_wrapped_centered(
            c, menu_data["subtitle"], center_x, y, max_width, body_font,
            subtitle_size, cfg.get("description_line_height", subtitle_size + 3),
            cfg.get("subtitle_color", "#555555")
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
                y = _draw_display_centered(c, name, display_font, cfg["course_name_size"], center_x, y)
                y -= cfg["gap_name_to_desc"]
            if desc:
                y = _draw_wrapped_centered(
                    c, desc, center_x, y, max_width, body_font,
                    cfg["description_size"], cfg["description_line_height"],
                    cfg["description_color"]
                )
            # Wine-pairing menus carry an extra line per course naming the
            # wine served with it. Set slightly smaller and lighter than the
            # dish description so the two don't compete.
            if wine:
                y -= cfg.get("gap_desc_to_wine", 4)
                y = _draw_wrapped_centered(
                    c, wine, center_x, y, max_width, body_font,
                    cfg.get("wine_size", cfg["description_size"] - 0.5),
                    cfg["description_line_height"],
                    cfg.get("wine_color", "#6b5a45"),
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
        _, end_y = render_card(probe, offset_x, cfg, menu_data, body_font, offset_y)
        content_top = offset_y + card_h - cfg["margin_top"]
        used = content_top - end_y
        slack = (card_h - cfg["margin_top"] - cfg["margin_bottom"]) - used
        if slack > 0:
            offset_y -= slack / 2.0

    c = canvas.Canvas(output_path, pagesize=(sheet_w, sheet_h))

    overflow_1, _ = render_card(c, offset_x, cfg, menu_data, body_font, offset_y)
    overflow_2, _ = render_card(c, offset_x + card_w, cfg, menu_data, body_font, offset_y)

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

def _draw_line_name_price(c, name, price, x_left, x_right, y, font_name, size, price_suffix=" €"):
    c.setFont(font_name, size)
    c.setFillColorRGB(0.05, 0.05, 0.05)
    c.drawString(x_left, y, name)
    if price:
        c.drawRightString(x_right, y, f"{price}{price_suffix}")
    c.setFillColorRGB(0, 0, 0)


class _CategorizedListFlow:
    """Tracks the y-cursor for one output PDF page and starts a new page
    (with a '(suite)' continuation title) automatically on overflow."""

    def __init__(self, c, cfg, role_fonts, display_font_path, title_text, already_started=False):
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

    def _new_page(self):
        if self.needs_showpage:
            self.c.showPage()
        cfg = self.cfg
        center_x = self.page_w / 2
        y = self.page_h - cfg["margin_top"]
        title = self.title_text + (" (suite)" if self.is_overflow else "")
        y = _draw_display_centered(self.c, title, self.display_font_path, cfg["page_title_size"], center_x, y)
        self.y = y - cfg["gap_after_page_title"]
        self.needs_showpage = True
        self.is_overflow = True

    def ensure_space(self, needed):
        if self.y - needed < self.bottom_limit:
            self.overflowed = True  # more than one page was needed -- expected for long lists, not an error
            self._new_page()

    def draw_category(self, category):
        cfg = self.cfg
        self.ensure_space(cfg["category_size"] + cfg["gap_after_category"])
        self.y -= cfg["category_size"]
        cat_font = self.fonts["category"]
        self.c.setFillColorRGB(0.05, 0.05, 0.05)
        if cat_font["raster"]:
            # Brand display face -- drawn as an image, see _draw_display_left.
            _draw_display_left(self.c, category.get("name", ""), cat_font["path"],
                               cfg["category_size"], self.margin_side, self.y)
        else:
            self.c.setFont(cat_font["name"], cfg["category_size"])
            self.c.drawString(self.margin_side, self.y, category.get("name", ""))

        if category.get("note"):
            note_font = self.fonts["note"]
            if not note_font["raster"]:
                self.c.setFont(note_font["name"], cfg["note_size"])
                self.c.drawRightString(self.page_w - self.margin_side, self.y, category["note"])
        self.c.setFillColorRGB(0, 0, 0)
        self.y -= cfg["gap_after_category"]

        for group in category.get("groups", []):
            if group.get("name"):
                self.ensure_space(cfg["subgroup_size"] + cfg["gap_after_subgroup"])
                self.y -= cfg["subgroup_size"]
                sub_font = self.fonts["subgroup"]
                if sub_font["raster"]:
                    _draw_display_left(self.c, group["name"], sub_font["path"],
                                       cfg["subgroup_size"], self.margin_side, self.y)
                else:
                    self.c.setFont(sub_font["name"], cfg["subgroup_size"])
                    self.c.setFillColorRGB(0.15, 0.15, 0.15)
                    self.c.drawString(self.margin_side, self.y, group["name"])
                    self.c.setFillColorRGB(0, 0, 0)
                self.y -= cfg["gap_after_subgroup"]

            for item in group.get("items", []):
                text = (item.get("text") or "").strip()
                if not text:
                    continue
                self.ensure_space(cfg["item_size"] + cfg["gap_after_item"])
                self.y -= cfg["item_size"]
                _draw_line_name_price(
                    self.c, text, item.get("price", ""),
                    self.margin_side, self.page_w - self.margin_side,
                    self.y, self.body_font, cfg["item_size"]
                )
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
        path = os.path.join(base_dir, rel) if rel else fallback_path
        try:
            name = _register_body_font(path)
            raster = False
        except Exception:
            # PostScript/CFF outlines -- rasterise this role instead.
            name, raster = None, True
        resolved[role] = {"name": name, "path": path, "raster": raster}
    return resolved


_SCALABLE_KEYS = (
    "category_size", "subgroup_size", "item_size", "note_size",
    "gap_after_category", "gap_after_subgroup", "gap_after_item",
    "gap_after_group_block",
)
# How far we'll shrink text/spacing on a page before giving up and letting it
# spill onto an extra page -- below this it would stop being legible.
_MIN_SHRINK_SCALE = 0.62


def _measure_categories_height(categories, cfg):
    """Dry-run of the same vertical decrements draw_category() makes, so we
    can tell -- before drawing anything -- whether a logical page's content
    fits in the space available, without needing a new PDF page for it."""
    h = 0.0
    for category in categories:
        h += cfg["category_size"] + cfg["gap_after_category"]
        for group in category.get("groups", []):
            if group.get("name"):
                h += cfg["subgroup_size"] + cfg["gap_after_subgroup"]
            for item in group.get("items", []):
                if not (item.get("text") or "").strip():
                    continue
                h += cfg["item_size"] + cfg["gap_after_item"]
        h += cfg["gap_after_group_block"]
    return h


def _fit_page_cfg(categories, cfg, title_text, display_font_path):
    """Like the original InDesign file, each logical page should stay one
    printed page -- so instead of overflowing onto a "(suite)" page when
    edits make a section run long, shrink its text/spacing just enough to
    still fit. Falls back to the original sizes if the content already fits,
    and only lets the old overflow safety net kick in if even the smallest
    readable size wouldn't be enough.

    The title is a rasterised display-font image, not a plain text line --
    its real inked height (with accents/descenders) can run noticeably
    taller than page_title_size, so it's measured directly rather than
    assumed, or the fit estimate would under-count used space and still
    let borderline pages overflow.
    """
    title_h = 0.0
    if title_text and title_text.strip():
        _, _, title_h = _render_display_text(title_text, display_font_path, cfg["page_title_size"])
    available = (cfg["page_height"] - cfg["margin_top"] - cfg["margin_bottom"]
                 - title_h - cfg["gap_after_page_title"])
    needed = _measure_categories_height(categories, cfg)
    if needed <= available or needed <= 0:
        return cfg
    scale = max(_MIN_SHRINK_SCALE, available / needed)
    page_cfg = dict(cfg)
    for key in _SCALABLE_KEYS:
        page_cfg[key] = cfg[key] * scale
    return page_cfg


def generate_categorized_list_pdf(content, cfg, output_path, base_dir):
    """
    content: dict with "pages": [{title, categories: [{name, note?, groups:
             [{name?, items: [{text, price}]}]}]}]
    cfg: dict loaded from config/templates/<template>.json
    output_path: where to write the final PDF
    base_dir: app root, so font paths in cfg (relative) resolve correctly

    Returns: {"ok": bool, "warnings": [str, ...]}
    """
    display_font_path = os.path.join(base_dir, cfg["fonts"]["display"])

    c = canvas.Canvas(output_path, pagesize=(cfg["page_width"], cfg["page_height"]))

    any_overflow = False
    pages = content.get("pages", [])
    for i, page in enumerate(pages):
        categories = page.get("categories", [])
        # Fit this page's content to its one printed page (shrinking text
        # and spacing together) rather than spilling onto an extra page --
        # the user does not want new pages created automatically.
        page_cfg = _fit_page_cfg(categories, cfg, page.get("title", ""), display_font_path)
        role_fonts = _resolve_role_fonts(page_cfg, base_dir, ("category", "subgroup", "item", "note"))
        flow = _CategorizedListFlow(
            c, page_cfg, role_fonts, display_font_path, page.get("title", ""),
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
            "Even after shrinking to fit, one or more sections still ran onto "
            "an extra page -- consider trimming the list for that page."
        )

    return {"ok": True, "warnings": warnings, "path": output_path}
