#!/usr/bin/env python3
"""
Extract the readable menu text out of an InDesign .indd file, without
needing InDesign or Adobe's cloud service.

Why this exists: .indd is a proprietary binary format, but the story text is
stored inside it as plain cp1252 (Windows Latin-1) byte runs. Adobe's
InDesign automation service is the "proper" way to read these files, but
it's an external dependency that can go down -- this is an offline fallback
that recovers the dish names, descriptions and wine pairings exactly.

Important: do NOT use the `strings` utility for this. It stops a run at any
byte >= 0x80, which is exactly where the accented characters live -- so
"carotte fumée" comes back as "carotte fum" + "e", silently mangling every
French word. We read the bytes ourselves and decode them as cp1252 so
accents survive intact.

What it does NOT recover: font sizes, frame positions, or styling. For those
we reuse an existing layout config from a same-style menu -- fine for the
Voyage/Voyagette family, where every variant shares one layout and only the
dish content differs.

Usage:
    python3 extract_indd_text.py <file.indd>            # human-readable
    python3 extract_indd_text.py <file.indd> --json     # JSON list
"""

import json
import re
import sys

# Bytes that can legitimately appear inside menu text once decoded as cp1252:
# printable ASCII, plus the accented Latin range, plus the typographic quotes
# and guillemets InDesign uses (0x91-0x94 curly quotes, 0xAB/0xBB « »).
TEXT_BYTES = set(range(0x20, 0x7F)) | set(range(0xA0, 0x100)) | {
    0x91, 0x92, 0x93, 0x94, 0x85,
}

MIN_RUN = 4          # shorter runs are almost always binary coincidence

# InDesign leaves a couple of stray bytes then '@' in front of many story
# fragments, e.g. "I@OREZ VE AFUnA". Menu text never contains '@'.
LEADING_JUNK = re.compile(r"^.{0,3}@")

# Internal plumbing that is never menu content. InDesign embeds large tables
# of these (per-language index sections, plugin names, font metadata, colour
# swatches) and they are dense enough to fool a naive "biggest block of text"
# search, so they must be filtered before locating the story block.
NOISE = re.compile(
    r"(?i)("
    r"\.(rpln|apln|idrc|pln|otf|ttf)\b"
    r"|^k[A-Z]|kIndex|kWRIndex|^IDX_"
    r"|_"
    r"|^(process |pantone|c=\d)"
    r"|^(adobe|indesign|xmp|uuid|minion|avenir|helvetica|myriad)"
    r"|^[0-9a-f]{8}-[0-9a-f]{4}"
    r"|version \d|hotconv|swop|8bim|web coated"
    r"|paragraphe|ancre de texte|utilisateur inconnu|unknown user"
    r"|notes de fin|^document$"
    # InDesign's default style names and the embedded sRGB colour profile
    r"|^\[(no |none|basic)|\[none\]"
    r"|dernier num|en-t.te continu|nom de (fichier|l'image)|num.ro de chapitre"
    r"|^tv xref|^iec |iec\d|colour space|viewing condition|^desc$|^view$"
    r"|^xyz$|^sig$|crt curv|^meas$"
    r"|^(regular|book|roman|light|medium|semibold|bold|italic|oblique)\b"
    r"|(light|book|medium|bold|black) oblique"
    r"|^(black|cyan|magenta|yellow)$"
    r")"
)


def byte_runs(path):
    """Yield decoded strings for each run of text-like bytes in the file."""
    data = open(path, "rb").read()
    out, cur = [], bytearray()
    for b in data:
        if b in TEXT_BYTES:
            cur.append(b)
        else:
            if len(cur) >= MIN_RUN:
                out.append(cur.decode("cp1252", errors="replace"))
            cur = bytearray()
    if len(cur) >= MIN_RUN:
        out.append(cur.decode("cp1252", errors="replace"))
    return out


def clean(line):
    line = LEADING_JUNK.sub("", line)
    line = line.replace("\x00", "")
    # InDesign's undo history leaves partial older copies of paragraphs,
    # padded with 0xFF bytes (ÿ). Strip that padding; the dedup step then
    # drops the fragment if we already have the full paragraph.
    line = line.lstrip("ÿ").lstrip()
    # Normalise InDesign's curly quotes to plain ones for consistency with
    # the rest of the app's content files.
    line = line.replace("’", "'").replace("‘", "'")
    line = line.replace("“", '"').replace("”", '"')
    line = re.sub(r"\s{2,}", " ", line)
    line = re.sub(r"\s+([,;:])", r"\1", line)
    return line.strip()


def story_score(line):
    """Higher = more likely to be real menu text.

    Menu text is natural language: several words, spaces, often commas.
    InDesign's internal strings are single CamelCase/underscore identifiers.
    Requiring multiple real words separates the two reliably.
    """
    if NOISE.search(line):
        return 0
    letters = len(re.findall(r"[A-Za-zÀ-ÿ]", line))
    if letters < 4:
        return 0

    words = [w for w in line.split() if re.search(r"[A-Za-zÀ-ÿ]", w)]
    if len(words) < 2:
        return 0
    if max(len(w) for w in words) > 24:
        return 0
    if letters / max(len(line), 1) < 0.55:
        return 0

    score = letters
    if len(words) >= 3:
        score += 20
    if "," in line:
        score += 25          # ingredient lists are the strongest signal
    return score


def find_story_block(lines, gap_tolerance=8, keep_ratio=1.0):
    """Return the parts of `lines` that hold the menu's text, in file order.

    The menu body sits in regions of the file separated by binary noise.
    We split into candidate blocks and keep every block scoring at least
    `keep_ratio` of the best one.

    keep_ratio defaults to 1.0 -- i.e. the single densest block only. That
    is deliberate: InDesign keeps undo history and superseded drafts in the
    same file, and lowering the threshold to catch secondary text frames
    also drags in those old drafts, producing menus with duplicated or
    long-removed courses. A clean read of the live story, with the odd
    genuinely-unrecoverable line left blank for a human to fill in, beats a
    fuller read contaminated with stale content.
    """
    blocks = []
    cur_score, cur_start, gap = 0, None, 0

    for i, line in enumerate(lines):
        s = story_score(line)
        if s:
            if cur_start is None:
                cur_start = i
            cur_score += s
            gap = 0
        elif cur_start is not None:
            gap += 1
            if gap > gap_tolerance:
                blocks.append((cur_score, cur_start, i - gap))
                cur_score, cur_start, gap = 0, None, 0

    if cur_start is not None:
        blocks.append((cur_score, cur_start, len(lines)))

    if not blocks:
        return []

    threshold = max(b[0] for b in blocks) * keep_ratio
    kept = [b for b in blocks if b[0] >= threshold]

    out = []
    for _, start, end in sorted(kept, key=lambda b: b[1]):
        out.extend(lines[start:end + 1])
    return out


def split_paragraphs(lines):
    """InDesign separates paragraphs with \\r inside one text run, so a single
    run often holds a dish name AND its description. Split those apart."""
    out = []
    for line in lines:
        for part in re.split(r"[\r\n]+", line):
            part = part.strip()
            if part:
                out.append(part)
    return out


def extract(path):
    raw = byte_runs(path)
    cleaned = [clean(l) for l in raw]
    block = find_story_block(cleaned)
    block = split_paragraphs(block)

    # Within the located block we relax the filter: dish NAMES are often a
    # single word ("Bisqotec", "Haminados") and would score 0 alone, but
    # inside the story block they are real content.
    seen, ordered = set(), []
    for line in block:
        if not line or NOISE.search(line):
            continue
        if len(re.findall(r"[A-Za-zÀ-ÿ]", line)) < 3:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(line)

    return ordered


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    lines = extract(sys.argv[1])
    if "--json" in sys.argv:
        print(json.dumps(lines, ensure_ascii=False, indent=2))
    else:
        for i, line in enumerate(lines, 1):
            print(f"{i:3d}  {line}")


if __name__ == "__main__":
    main()
