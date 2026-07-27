#!/usr/bin/env python3
"""
Install a font into the menu app so it becomes selectable in the Admin panel.

Handles the three shapes fonts arrive in on a Mac:
  .ttf / .otf   -- copied straight in
  .ttc          -- a *collection* holding many faces in one file. PDF
                   embedding needs a single face, so every face is unpacked
                   into its own .ttf named after its PostScript name.

Usage:
    python3 tools/install_font.py "/System/Library/Fonts/Avenir Next.ttc"
    python3 tools/install_font.py ~/Library/Fonts/SomeFont.otf
    python3 tools/install_font.py --list          # show what's installed

Anything installed here appears in the Admin panel's font dropdowns the
next time the app starts.
"""

import os
import shutil
import sys

FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "assets", "fonts")


def list_installed():
    if not os.path.isdir(FONTS_DIR):
        print("no fonts installed yet")
        return
    names = sorted(f for f in os.listdir(FONTS_DIR)
                   if f.lower().endswith((".ttf", ".otf")))
    print(f"{len(names)} font(s) installed in assets/fonts:")
    for n in names:
        print("   ", n)


def install_collection(path):
    """Unpack every face of a .ttc into its own .ttf."""
    from fontTools.ttLib import TTCollection

    collection = TTCollection(path)
    written = []
    for font in collection.fonts:
        name_table = font["name"]
        ps_name = name_table.getDebugName(6) or name_table.getDebugName(4)
        if not ps_name:
            continue
        safe = "".join(ch for ch in ps_name if ch.isalnum() or ch in "-_")
        out = os.path.join(FONTS_DIR, f"{safe}.ttf")
        font.save(out)
        written.append(os.path.basename(out))
    return written


def install_single(path):
    out = os.path.join(FONTS_DIR, os.path.basename(path))
    shutil.copy2(path, out)
    return [os.path.basename(out)]


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    if sys.argv[1] == "--list":
        list_installed()
        return

    os.makedirs(FONTS_DIR, exist_ok=True)

    for src in sys.argv[1:]:
        src = os.path.expanduser(src)
        if not os.path.isfile(src):
            print(f"!! not found: {src}")
            continue
        ext = os.path.splitext(src)[1].lower()
        try:
            written = install_collection(src) if ext == ".ttc" else install_single(src)
        except Exception as e:
            print(f"!! could not install {os.path.basename(src)}: {e}")
            continue
        print(f"{os.path.basename(src)} -> {len(written)} face(s):")
        for w in written:
            print("     ", w)

    print()
    list_installed()
    print("\nRestart the app, then pick these in Admin > Fonts.")


if __name__ == "__main__":
    main()
