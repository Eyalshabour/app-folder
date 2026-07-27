#!/usr/bin/env python3
"""
Build the app's menu templates directly from the restaurant's own
"menu up to date" folder, so the app's menu list mirrors that folder
instead of names typed in by hand.

Folder convention this reads (as organised by the restaurant):

    menu up to date/
        dinner en/     ENG - Menu VOYAGE ....indd
        dinner fr/     Menu VOYAGE ....indd
        lunch en/      ENG - Menu VOYAGETTE ....indd
        lunch fr/      Menu VOYAGETTE ....indd
        wine pairing dinner/   both languages, EN files prefixed "ENG - "
        wine pairing lunch/    both languages, EN files prefixed "ENG - "

Language is taken from the folder name ("... en" / "... fr") when present,
otherwise from the "ENG - " filename prefix. Each menu's EN and FR files are
paired by their normalised name, so "Menu VOYAGETTE KOSHER 6 TEMPS" (fr) and
"ENG - Menu VOYAGETTE 6 TEMPS KOSHER" (en) match despite the word order.

Output: sample_data/<menu_id>/<lang>.json in the tasting-menu shape
(title / courses[] / dessert[]) plus a templates.json registry entry.

Usage:
    python3 build_menus_from_folder.py "<path to menu up to date>" [--write]

Without --write it prints what it would do (dry run).
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_indd_text import extract, byte_runs, clean  # noqa: E402


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Which layout each source folder's menus should render with. Every one of
# these is the same one-column tasting-menu layout as Voyage Shabour; the
# pairing menus add a wine line per course but share the same geometry.
FOLDER_META = {
    "dinner":            {"service": "Dinner",  "pairing": False},
    "lunch":             {"service": "Lunch",   "pairing": False},
    "wine pairing dinner": {"service": "Dinner Wine Pairing", "pairing": True},
    "wine pairing lunch":  {"service": "Lunch Wine Pairing",  "pairing": True},
}

# Words that mark a dish NAME line rather than a description. Names are the
# all-caps (or near) headings; descriptions are lowercase ingredient lists.
DESSERT_NAMES = {"PARIS-JERUSALEM", "EASY PEASY LEMON FREEKEH",
                 "EASY PEASY LEMOn FREEKEH"}


def language_of(folder_name, file_name):
    f = folder_name.lower()
    if f.endswith(" en"):
        return "en"
    if f.endswith(" fr"):
        return "fr"
    # Shared folders (the wine-pairing ones) rely on the filename prefix.
    return "en" if file_name.upper().startswith("ENG") else "fr"


def service_of(folder_name):
    key = folder_name.strip().lower()
    for prefix, meta in FOLDER_META.items():
        if key.startswith(prefix):
            return prefix, meta
    return None, None


def menu_key(file_name):
    """Normalise a filename into a key that matches across languages.

    Strips the "ENG - " prefix, the "Menu " word, the ".indd" extension and
    any date suffix, then sorts the remaining words -- so "KOSHER 6 TEMPS"
    and "6 TEMPS KOSHER" collapse to the same key.
    """
    name = os.path.splitext(file_name)[0]
    name = re.sub(r"(?i)^eng\s*-\s*", "", name)
    name = re.sub(r"(?i)^menu\s+", "", name)
    name = re.sub(r"\d{2}\.\d{4}", "", name)          # "06.2026"
    name = re.sub(r"(?i)art de la table", "", name)   # present on some, not others
    name = re.sub(r"[^A-Za-z0-9 ]", " ", name)
    words = sorted(w.upper() for w in name.split() if w)
    return " ".join(words)


def display_name(file_name, service):
    """Human-facing menu name, derived from the restaurant's own filename."""
    name = os.path.splitext(file_name)[0]
    name = re.sub(r"(?i)^eng\s*-\s*", "", name)
    name = re.sub(r"(?i)^menu\s+", "", name)
    name = re.sub(r"\s*\d{2}\.\d{4}", "", name)
    name = re.sub(r"\s{2,}", " ", name).strip()
    return f"{name} ({service})"


def is_name_line(line):
    """Dish names are headings; descriptions are comma-separated ingredients.

    On these menus a dish name is either SHOUTED ("TOUR IN THE OLD CITY",
    "PARIS-JERUSALEM") or set entirely in lowercase ("bisqotec",
    "ris d'orloff") -- both are styled headings in the original layout.

    Wine lines on the pairing menus are Title Case ("Hakutsuru", "Vision",
    "Lopez de Heredia"), which is exactly what this rule excludes, so wines
    don't get mistaken for courses.
    """
    if "," in line:
        return False
    if len(line.split()) > 5:
        return False
    letters = [c for c in line if c.isalpha()]
    if not letters:
        return False

    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    all_lower = upper_ratio == 0
    return upper_ratio > 0.5 or all_lower


def to_courses(lines, pairing):
    """Fold the flat extracted lines into course objects.

    Non-pairing menus alternate NAME / description. Pairing menus add up to
    three wine lines after the description (producer, cuvée, vintage+region),
    which we join into one 'wine' string kept on the course.
    """
    courses = []
    seen_names = set()
    i = 0

    # On the lunch menus the "AMUSE-BOUCHE" heading sits in its own text
    # frame, which sometimes falls outside the main story block -- so the
    # file can open with a description that has no name above it. Restore
    # the heading rather than dropping the course.
    if lines and not is_name_line(lines[0]):
        courses.append({"name": "AMUSE-BOUCHE", "description": lines[0]})
        seen_names.add("AMUSE-BOUCHE")
        i = 1

    while i < len(lines):
        line = lines[i]
        if not is_name_line(line):
            i += 1
            continue

        course = {"name": line, "description": ""}
        i += 1
        if i < len(lines) and not is_name_line(lines[i]):
            course["description"] = lines[i]
            i += 1

        if pairing:
            wine_bits = []
            while i < len(lines) and not is_name_line(lines[i]) and len(wine_bits) < 3:
                wine_bits.append(lines[i])
                i += 1
            if wine_bits:
                course["wine"] = " ".join(wine_bits)

        # InDesign keeps undo history in the file, so an older draft of a
        # course can reappear later with a stale description. The first
        # occurrence is the live one, so ignore any repeat of a name we've
        # already taken.
        key = course["name"].upper()
        if key in seen_names:
            continue
        seen_names.add(key)
        courses.append(course)

        # The dessert always closes these menus -- anything after it is
        # leftover undo history from a previous version of the document.
        if key in {n.upper() for n in DESSERT_NAMES}:
            break

    return courses


# The printed masthead, e.g. "LE VOYAGE SHABOUR" / "LA VOYAGETTE". It lives
# in its own text frame, outside the main story block, so we look for it
# across the whole file rather than in the extracted courses.
TITLE_RE = re.compile(r"^(LE |LA |THE )?VOYAGE(TTE)?( SHABOUR)?$", re.I)


def find_title(path, lang, is_voyagette):
    """Read the menu's own masthead out of the file.

    Some English files store the masthead in styled fragments that don't
    survive as one run, so we fall back to the house naming convention for
    that language rather than inventing something.
    """
    candidates = []
    for run in byte_runs(path):
        line = clean(run)
        if TITLE_RE.match(line) and line.isupper():
            candidates.append(line)
    if candidates:
        return max(candidates, key=len)

    if is_voyagette:
        return "LA VOYAGETTE" if lang == "fr" else "THE VOYAGETTE"
    return "LE VOYAGE SHABOUR" if lang == "fr" else "THE VOYAGE SHABOUR"


def merge_apostrophe_splits(courses):
    """Repair names broken by a styled apostrophe.

    InDesign stores the apostrophe in "RIS D'ORLOFF" as an inline glyph
    override rather than a character, which splits the name into two
    fragments -- the first ending in a lone letter and carrying no
    description. Stitch those back together.
    """
    out = []
    i = 0
    while i < len(courses):
        cur = courses[i]
        nxt = courses[i + 1] if i + 1 < len(courses) else None
        words = cur["name"].split()
        ends_with_lone_letter = len(words) > 1 and len(words[-1]) == 1

        if nxt and not cur["description"] and ends_with_lone_letter:
            merged = dict(nxt)
            merged["name"] = f"{cur['name']}'{nxt['name']}"
            out.append(merged)
            i += 2
            continue

        out.append(cur)
        i += 1
    return out


def split_dessert(courses):
    """The last course is the dessert on every menu in this family."""
    if not courses:
        return courses, []
    for idx, c in enumerate(courses):
        if c["name"].upper().replace("N", "N") in DESSERT_NAMES:
            return courses[:idx], courses[idx:]
    return courses[:-1], courses[-1:]


def slugify(key):
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    root = sys.argv[1]
    write = "--write" in sys.argv

    # menu_key -> {"service","pairing","display","langs":{lang: path}}
    menus = {}

    for folder in sorted(os.listdir(root)):
        folder_path = os.path.join(root, folder)
        if not os.path.isdir(folder_path):
            continue
        prefix, meta = service_of(folder)
        if not meta:
            continue

        for fname in sorted(os.listdir(folder_path)):
            if not fname.lower().endswith(".indd") or fname.startswith("~"):
                continue
            if fname.lower().startswith("untitled"):
                continue          # drafts -- not published menus

            key = menu_key(fname)
            lang = language_of(folder, fname)
            entry = menus.setdefault(key, {
                "service": meta["service"],
                "pairing": meta["pairing"],
                "display": display_name(fname, meta["service"]),
                "langs": {},
            })
            entry["langs"][lang] = os.path.join(folder_path, fname)
            # Prefer the French filename for the display name -- it is the
            # restaurant's primary naming and has no "ENG - " prefix.
            if lang == "fr":
                entry["display"] = display_name(fname, meta["service"])

    registry = []
    for key, entry in sorted(menus.items()):
        menu_id = slugify(key)
        langs_built = []
        for lang, path in sorted(entry["langs"].items()):
            lines = extract(path)
            courses = to_courses(lines, entry["pairing"])
            courses = merge_apostrophe_splits(courses)
            main_courses, dessert = split_dessert(courses)
            if not main_courses:
                print(f"  !! no courses parsed from {os.path.basename(path)}")
                continue

            content = {
                "title": find_title(path, lang, "VOYAGETTE" in key),
                "courses": main_courses,
                "dessert": dessert,
            }
            out_dir = os.path.join(BASE_DIR, "sample_data", menu_id)
            out_path = os.path.join(out_dir, f"{lang}.json")
            if write:
                os.makedirs(out_dir, exist_ok=True)
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(content, f, ensure_ascii=False, indent=2)
                    f.write("\n")
            langs_built.append(lang)
            print(f"  {menu_id}/{lang}.json  ({len(main_courses)} courses"
                  f"{', +wine' if entry['pairing'] else ''})")

        if langs_built:
            registry.append({
                "id": menu_id,
                "name": entry["display"],
                "layout_config": "config/templates/voyage_shabour.json",
                "languages": langs_built,
            })

    print(f"\n{len(registry)} menus, "
          f"{sum(len(r['languages']) for r in registry)} language files")

    if write:
        reg_path = os.path.join(BASE_DIR, "config", "templates.json")
        with open(reg_path) as f:
            data = json.load(f)
        existing_ids = {t["id"] for t in data["templates"]}
        added = [r for r in registry if r["id"] not in existing_ids]
        data["templates"].extend(added)
        with open(reg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"registered {len(added)} new templates")
    else:
        print("(dry run -- pass --write to save)")


if __name__ == "__main__":
    main()
