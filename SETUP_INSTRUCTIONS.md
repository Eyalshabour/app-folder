# Menu Editor — Setup Instructions

This app now covers 5 of your real menus, built from actual InDesign data (uploaded via the Adobe file picker, not screenshots), with your real brand fonts. Every save writes into this app's folder on your Desktop, which syncs to Google Drive automatically via Google Drive for Desktop.

## What's already built

**5 menus in the "Menu" dropdown:**
1. **The Voyage Shabour** — tasting menu (title, courses, dessert)
2. **Le Voyage Shabour (aperitifs & pricing)** — price/wine-pairing lines + drinks list, two-up
3. **La Voyagette (aperitifs & pricing)** — same style, shorter menu
4. **Le Voyage Shabour (exterieur card)** — single-page summary/table-tent card
5. **La Voyagette (exterieur card)** — same, shorter menu

For menus 2–5, the layout and every font size came directly from the real IDML data Adobe's InDesign service extracted from your `.indd` files (title 34pt Shabour SemiBold, prices 18pt/15pt Avenir Book, etc.) — not guesswork from a screenshot. Item-list and footer sizes are close estimates, since the source reported those as one flowing text block rather than per-line styling.

**Still to build: Digestifs.** That file (`MENU DIGESTIFS.indd`) is a much bigger two-column document with many nested categories (eau-de-vie, whisky, rhum/cachaca, cognac, calvados, mezcal, gin, vodka...). It needs its own editor design rather than reusing the price-card layout — happy to build it next when you're ready.

**Other things in place:**
- Your real fonts (SHABOUR-SemiBold, Avenir) built into every generated PDF
- The real Voyage Shabour logo symbol used as the divider graphic on every menu (not an approximation)
- A language switcher — currently English/French for the tasting menu, French-only for the other 4 (add an "en" entry in `config/templates.json` + an `en.json` content file if you want English versions of those too)
- PDF filenames are unique per menu + language + date (e.g. `AperitifsVoyage_FR_2026-07-24.pdf`), so different menus never overwrite each other
- Files save into this app's folder, which Google Drive for Desktop syncs to your Drive automatically

## What's still approximate
- **Exact spacing/margins** for the two-up "aperitifs" cards — the IDML reported these as one flowing text frame, so I estimated proportions rather than reading exact per-line coordinates.
- **The divider icon's exact crop** — I use your real logo image, drawn as two symbols side by side; the original file's precise crop/scale transform wasn't available in the data I pulled.

## Google Drive — already connected (no setup needed)

Turns out the simplest path applies here: this app's folder (`indes_claude`) lives on the Desktop, and Google Drive for Desktop is syncing the whole Desktop to Drive. That means every time the app saves — the editable content and the finished dated PDF — it's writing into a folder that's already being backed up to Google Drive automatically, in the background. Nothing further to configure.

You can confirm this any time by checking drive.google.com — your Desktop files, including this app's `generated_pdfs` folder, should appear there.

<details>
<summary>Alternative: the Google Cloud API route (not needed for your setup, kept here for reference)</summary>

If you ever move the app off a Drive-synced folder and want it to write to a specific Drive folder directly via Google's API instead:

1. Go to https://console.cloud.google.com/ and create a project (or use an existing one).
2. Enable the **Google Drive API** for that project (APIs & Services → Enable APIs → search "Google Drive API").
3. Go to **APIs & Services → Credentials → Create Credentials → Service Account**. Give it any name (e.g. "menu-editor").
4. Open the new service account → **Keys → Add Key → Create new key → JSON**. This downloads a `.json` file — save it as `drive/service_account.json` inside this app folder.
5. Copy the service account's email address (looks like `menu-editor@your-project.iam.gserviceaccount.com`).
6. In Google Drive, open (or create) the folder where your menu files live, click **Share**, and share it with that email address as an **Editor**.
7. Open that folder's URL in your browser — the long string after `/folders/` is the folder ID. Set it as an environment variable before starting the app:
   ```
   export MENU_DRIVE_FOLDER_ID="paste_the_folder_id_here"
   ```

</details>

## Running the app

```
cd menu-editor-app
pip install -r requirements.txt --break-system-packages
python3 app.py
```

Then open **http://localhost:5050** in a browser.

## Adding another menu style later
1. Add a new layout file at `config/templates/<new_id>.json`. If it's a course-list style like Voyage Shabour, copy `voyage_shabour.json`; if it's a price/drinks-list style like Aperitifs/Exterieur, copy `aperitifs_voyage.json` or `exterieur_voyage.json`.
2. Add sample content at `sample_data/<new_id>/<language>.json`.
3. Add an entry to `config/templates.json` pointing at both.

It'll show up automatically in the "Menu" dropdown. If you can get me the `.indd` uploaded the same way (via the Adobe file picker in chat), I can pull exact layout data again rather than estimating from a screenshot.

## Notes on the "fixed template" behavior
- Everything flows top-to-bottom in a fixed order (title, divider, sections, items, footer). Adding/removing items never breaks the layout — if content no longer fits, the app shows a warning instead of silently overflowing.
- On the price-card menus, "blank space" rows let you group drinks visually the same way the original does (e.g. separating champagnes from cocktails), without needing a heading for every group.
