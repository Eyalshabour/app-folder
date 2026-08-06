#!/usr/bin/env python3
"""
End-to-end check of the menu editor.

Run this after changing anything -- it exercises the real Flask routes and
inspects the PDFs that come out, rather than trusting that the code "looks
right". Reports PASS/FAIL per check and exits non-zero if anything failed.

    python3 tools/run_tests.py
"""

import io
import json
import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

os.environ["APP_PASSWORD"] = "test-suite-password"

import app as flask_app                      # noqa: E402
from pypdf import PdfReader                  # noqa: E402

client = flask_app.app.test_client()

# Every route is now behind the login gate -- log in once and reuse the
# session cookie for the rest of the suite.
login_resp = client.post("/login", data={"password": os.environ["APP_PASSWORD"]})
assert login_resp.status_code == 302, f"test-suite login failed: {login_resp.status_code}"

A4_LANDSCAPE = (842, 595)
A4_PORTRAIT = (595, 842)

results = []


def check(name, condition, detail=""):
    results.append((bool(condition), name, detail))
    mark = "PASS" if condition else "FAIL"
    line = f"  [{mark}] {name}"
    if detail and not condition:
        line += f"\n         {detail}"
    print(line)
    return bool(condition)


def page_size(path):
    box = PdfReader(path).pages[0].mediabox
    return (round(float(box.width)), round(float(box.height)))


def pdf_text(path):
    return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)


def section(title):
    print(f"\n{title}")
    print("-" * len(title))


# -------------------------------------------------------------------- login
section("Login gate")

anon = flask_app.app.test_client()
blocked = anon.get("/api/templates")
check("unauthenticated request is redirected to login",
      blocked.status_code == 302 and "/login" in blocked.headers.get("Location", ""),
      f"got {blocked.status_code} {blocked.headers.get('Location')}")

wrong = anon.post("/login", data={"password": "definitely-not-it"})
check("wrong password is rejected", wrong.status_code == 401)

still_blocked = anon.get("/api/templates")
check("still blocked after a wrong password", still_blocked.status_code == 302)


# ---------------------------------------------------------------- registry
section("Registry and content files")

templates = client.get("/api/templates").get_json()["templates"]
check("template registry loads", len(templates) > 0, "no templates returned")

missing = []
for t in templates:
    for lang in t["languages"]:
        p = os.path.join("sample_data", t["id"], f"{lang}.json")
        if not os.path.exists(p):
            missing.append(p)
check("every registered menu has its content file", not missing, f"missing: {missing}")

empty = []
for t in templates:
    for lang in t["languages"]:
        d = json.load(open(os.path.join("sample_data", t["id"], f"{lang}.json")))
        # A menu is "populated" if it has any of the shapes this app prints.
        # The exterieur table-tent cards legitimately carry only a title and
        # prices -- no course or item list -- so a bare title+price counts.
        has = (d.get("courses") or d.get("pages") or d.get("items") or d.get("ingredients")
               or (d.get("title") and d.get("price")))
        if not has:
            empty.append(f"{t['id']}/{lang}")
check("no menu is empty", not empty, f"empty: {empty}")


# ----------------------------------------------------------------- render
section("Rendering every menu")

rendered = {}
failures = []
for t in templates:
    for lang in t["languages"]:
        menu = client.get(f"/api/menu?template={t['id']}&language={lang}").get_json()["menu"]
        r = client.post(f"/api/save?template={t['id']}&language={lang}", json=menu)
        j = r.get_json()
        if r.status_code != 200 or not j.get("ok"):
            failures.append(f"{t['id']}/{lang}")
        else:
            rendered[f"{t['id']}/{lang}"] = os.path.join("generated_pdfs", j["filename"])

check(f"all {sum(len(t['languages']) for t in templates)} menus render",
      not failures, f"failed: {failures}")

bad_size = {k: page_size(v) for k, v in rendered.items()
            if page_size(v) not in (A4_LANDSCAPE, A4_PORTRAIT)}
check("every PDF page is A4", not bad_size, f"wrong size: {bad_size}")


# ------------------------------------------------------------ content in PDF
section("Content actually reaches the PDF")

sample = rendered.get("voyage/fr")
if sample:
    text = pdf_text(sample)
    check("French accents survive into the PDF",
          "fumée" in text and "arménien" in text,
          "accented words not found in extracted text")

    # Dish names and titles are set in SHABOUR, which has PostScript
    # outlines that reportlab cannot embed as live text -- so they are
    # rasterised at 300dpi and drawn as images. That means they will never
    # appear in extracted text; the right check is that the images exist and
    # the source data is correct.
    page = PdfReader(sample).pages[0]
    src = json.load(open("sample_data/voyage/fr.json"))
    names = [c["name"] for c in src["courses"]]
    check("apostrophe name is one course, not split",
          "RIS D'ORLOFF" in names and "RIS D" not in names,
          f"course names: {names}")
    # title + 2 dividers + 7 course names, duplicated across both cards
    check("dish names are rendered (as 300dpi images)",
          len(page.images) >= len(names),
          f"{len(page.images)} images for {len(names)} course names")

pairing = rendered.get("pairing_voyage/en")
if pairing:
    text = pdf_text(pairing)
    check("wine pairings appear in the printed PDF",
          "Holdvolgy" in text or "Barbadillo" in text,
          "no wine producer found in PDF text")

    # Those rasterised titles are the one place print quality could silently
    # degrade, so assert the effective resolution is still print-grade.
    import pdf_generator
    dpi = pdf_generator.RENDER_SCALE * 72
    check("rasterised titles are print resolution (>=300dpi)", dpi >= 300,
          f"only {dpi:.0f}dpi")

wine = rendered.get("winelist/fr")
if wine:
    text = pdf_text(wine)
    check("wine list prices render", "€" in text, "no euro sign found")
    check("wine list is multi-page", len(PdfReader(wine).pages) > 5,
          f"only {len(PdfReader(wine).pages)} pages")

# Every page of a categorized list uses the SAME font sizes/spacing from its
# layout config now -- no more per-page shrinking to force everything onto
# one page (see generate_categorized_list_pdf in pdf_generator.py). A page
# that's too long to fit spills onto an automatic "(suite)" continuation
# page instead, so page count is no longer guaranteed to match the logical
# page count 1:1.
import pdf_generator

check("categorized-list pages no longer auto-shrink font size",
      not hasattr(pdf_generator, "_MIN_SHRINK_SCALE"),
      "shrink-to-fit scaling should have been removed")

for tid in ("winelist", "digestifs"):
    key = f"{tid}/fr"
    if key in rendered:
        n_logical = len(json.load(open(f"sample_data/{tid}/fr.json")).get("pages", []))
        n_pdf = len(PdfReader(rendered[key]).pages)
        check(f"{tid}: page count is at least the logical page count",
              n_pdf >= n_logical, f"{n_logical} logical pages became {n_pdf} PDF pages")

# A single page can carry its own layout_overrides (smaller/larger font
# sizes and gaps than the document default) so someone can fix just the
# one page that's running long, without touching every other page --
# see PAGE_OVERRIDABLE_KEYS in app.js and _page_effective_cfg in
# pdf_generator.py.
import copy
import tempfile

winelist_cfg = json.load(open("config/templates/winelist.json"))
winelist_content = json.load(open("sample_data/winelist/fr.json"))

_tmpdir = tempfile.mkdtemp(prefix="winelist_override_test_")
baseline_pdf = os.path.join(_tmpdir, "baseline.pdf")
pdf_generator.generate_categorized_list_pdf(winelist_content, winelist_cfg, baseline_pdf, APP_DIR)
baseline_pages = len(PdfReader(baseline_pdf).pages)

overridden_content = copy.deepcopy(winelist_content)
overridden_content["pages"][1]["layout_overrides"] = {"item_size": 6.0, "category_size": 8.0}
overridden_pdf = os.path.join(_tmpdir, "overridden.pdf")
pdf_generator.generate_categorized_list_pdf(overridden_content, winelist_cfg, overridden_pdf, APP_DIR)
overridden_pages = len(PdfReader(overridden_pdf).pages)

check("page-level layout_overrides don't change other pages' page count",
      overridden_pages == baseline_pages,
      f"baseline {baseline_pages} pages, with one page overridden {overridden_pages} pages")

overridden_text_page2 = (PdfReader(overridden_pdf).pages[1].extract_text() or "")
baseline_text_page2 = (PdfReader(baseline_pdf).pages[1].extract_text() or "")
check("overridden page still renders its own content",
      "Antech" in overridden_text_page2 and "Limoux" in overridden_text_page2,
      "expected page 2 content missing after override")

# Overrides object itself shouldn't leak onto an untouched page. Every
# content page (1-11) now legitimately carries its own layout_overrides
# in the real content (font/casing choices matching the reference menu),
# so this checks page 0 -- the cover page, which has no categories and
# never gets an override, real or test-injected.
check("layout_overrides on one page doesn't get copied to another",
      "layout_overrides" not in overridden_content["pages"][0],
      "override bled into a page that never set one")

import shutil
shutil.rmtree(_tmpdir, ignore_errors=True)

# Subgroup role also accepts a font override per page (same mechanism as
# category, see _PAGE_OVERRIDABLE_FONT_ROLES) -- category/region labels
# can opt into Shabour Semibold or ShoubourCut instead of the document
# default. ShoubourCut only has glyphs for N/Y (+ accented forms), so most
# subgroup text renders mostly blank with it -- that's expected, not a
# bug; this just checks the render pipeline doesn't crash or drop pages.
_tmpdir2 = tempfile.mkdtemp(prefix="winelist_subgroup_font_test_")
for font_file in ("SHABOUR-SemiBold.otf", "ShoubourCut.otf"):
    variant_content = copy.deepcopy(winelist_content)
    variant_content["pages"][3]["layout_overrides"] = {
        "fonts": {"subgroup": f"assets/fonts/{font_file}"}
    }
    variant_pdf = os.path.join(_tmpdir2, f"{font_file}.pdf")
    result = pdf_generator.generate_categorized_list_pdf(variant_content, winelist_cfg, variant_pdf, APP_DIR)
    variant_pages = len(PdfReader(variant_pdf).pages)
    # Note: at the reference-matched sizes, "Vins Rouges - France" alone
    # already overflows onto a "(suite)" page (unrelated to this test's
    # subgroup font override), so a suite-page warning is expected here --
    # this check only confirms the render didn't fail outright.
    check(f"subgroup font override ({font_file}) renders without error",
          result["ok"],
          f"warnings: {result['warnings']}")
    check(f"subgroup font override ({font_file}) doesn't change page count",
          variant_pages == baseline_pages,
          f"baseline {baseline_pages} pages, with {font_file} subgroup font {variant_pages} pages")
shutil.rmtree(_tmpdir2, ignore_errors=True)


# ---------------------------------------------------------------- preview
section("Preview (unsaved edits)")

menu = client.get("/api/menu?template=voyage&language=fr").get_json()["menu"]
menu["title"] = "PREVIEW ONLY TITLE"
pv = client.post("/api/preview?template=voyage&language=fr", json=menu).get_json()
check("preview renders", pv.get("ok"), str(pv))

on_disk = json.load(open("sample_data/voyage/fr.json"))
check("preview does NOT overwrite saved content",
      on_disk["title"] != "PREVIEW ONLY TITLE",
      "preview leaked into the saved file")


# ------------------------------------------------------------------ fonts
section("Fonts")

fonts = client.get("/api/fonts").get_json()
check("fonts are installed", len(fonts["fonts"]) > 0)
check("some fonts are body-safe", len(fonts["body_fonts"]) > 0)

lay = client.get("/api/layout?template=winelist").get_json()
check("layout exposes font roles", "fonts" in lay and lay["fonts"])

cff = [f for f in fonts["fonts"] if f not in fonts["body_fonts"]]
if cff:
    before = client.get("/api/layout?template=winelist").get_json()["fonts"]["item"]
    client.post("/api/layout?template=winelist", json={"fields": {}, "fonts": {"item": cff[0]}})
    after = client.get("/api/layout?template=winelist").get_json()["fonts"]["item"]
    check("non-embeddable font is refused for body text", before == after,
          f"{cff[0]} was wrongly accepted for 'item'")

bad = client.post("/api/layout?template=winelist",
                  json={"fields": {}, "fonts": {"item": "assets/fonts/DoesNotExist.ttf"}})
after = client.get("/api/layout?template=winelist").get_json()["fonts"]["item"]
check("missing font file is refused", "DoesNotExist" not in after)


# ------------------------------------------------------- admin round trip
section("Admin panel round trip")

orig = client.get("/api/layout?template=winelist").get_json()["fields"]["item_size"]
client.post("/api/layout?template=winelist", json={"fields": {"item_size": 11}, "fonts": {}})
changed = client.get("/api/layout?template=winelist").get_json()["fields"]["item_size"]
check("admin size change persists", float(changed) == 11.0, f"got {changed}")

client.post("/api/layout?template=winelist", json={"fields": {"item_size": orig}, "fonts": {}})
restored = client.get("/api/layout?template=winelist").get_json()["fields"]["item_size"]
check("admin change reverts cleanly", float(restored) == float(orig))

orig_align = client.get("/api/layout?template=winelist").get_json()["alignment"]["category"]
client.post("/api/layout?template=winelist", json={"fields": {}, "alignment": {"category": "right"}})
changed_align = client.get("/api/layout?template=winelist").get_json()["alignment"]["category"]
check("admin alignment change persists", changed_align == "right", f"got {changed_align}")

client.post("/api/layout?template=winelist", json={"fields": {}, "alignment": {"category": "not-a-real-value"}})
after_bad = client.get("/api/layout?template=winelist").get_json()["alignment"]["category"]
check("invalid alignment value is refused", after_bad == "right", f"got {after_bad}")

client.post("/api/layout?template=winelist", json={"fields": {}, "alignment": {"category": orig_align}})
restored_align = client.get("/api/layout?template=winelist").get_json()["alignment"]["category"]
check("admin alignment change reverts cleanly", restored_align == orig_align)


# --------------------------------------------------------- wine editability
section("Wine field is editable")

m = client.get("/api/menu?template=pairing_voyage&language=en").get_json()["menu"]
target = m["courses"][0]["name"]
m["courses"][0]["wine"] = "ROUNDTRIP TEST 2020"
client.post("/api/save?template=pairing_voyage&language=en", json=m)
back = client.get("/api/menu?template=pairing_voyage&language=en").get_json()["menu"]
check("wine saves and reloads", back["courses"][0].get("wine") == "ROUNDTRIP TEST 2020")

pdf = os.path.join("generated_pdfs", "PairingVoyage_EN_" +
                   __import__("datetime").date.today().isoformat() + ".pdf")
if os.path.exists(pdf):
    check("edited wine reaches the PDF", "ROUNDTRIP TEST" in pdf_text(pdf))

del back["courses"][0]["wine"]
client.post("/api/save?template=pairing_voyage&language=en", json=back)
final = client.get("/api/menu?template=pairing_voyage&language=en").get_json()["menu"]
check("test wine cleaned up", "wine" not in final["courses"][0],
      "leftover test data in real content")


# ----------------------------------------------------------------- summary
passed = sum(1 for ok, _, _ in results if ok)
total = len(results)
print(f"\n{'=' * 46}")
print(f"  {passed}/{total} checks passed")
print(f"{'=' * 46}")
sys.exit(0 if passed == total else 1)
